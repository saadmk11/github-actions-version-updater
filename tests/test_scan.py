"""End-to-end updater tests with a fake version lookup."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from tests.conftest import (
    FakeResponse,
    FakeSession,
    RecordingReporter,
    silent_reporter,
    write_workflow,
)
from update_gha.config import Configuration
from update_gha.github import GitHubAPIError, GitHubClient, HttpSession
from update_gha.log import Reporter
from update_gha.models import (
    CommitInfo,
    ReleaseInfo,
    ReleaseType,
    ResolvedVersion,
    UpdateVersionWith,
)
from update_gha.scan import (
    _release_tag_comment,
    _split_action,
    _write_text_preserving_newlines,
    run_update,
)

CHECKOUT_V3 = "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v3\n"


class FakeLookup:
    def __init__(
        self,
        versions: dict[tuple[str, str], ResolvedVersion | None],
    ) -> None:
        self._versions = versions

    def resolve_new_version(
        self,
        action_repository: str,
        current_version: str,
        update_with: UpdateVersionWith,
        release_types: frozenset[ReleaseType],
    ) -> ResolvedVersion | None:
        return self._versions.get((action_repository, current_version))


class RaisingLookup(FakeLookup):
    def resolve_new_version(
        self,
        action_repository: str,
        current_version: str,
        update_with: UpdateVersionWith,
        release_types: frozenset[ReleaseType],
    ) -> ResolvedVersion | None:
        if action_repository == "actions/missing":
            raise GitHubAPIError("HTTP 404: Not Found")
        return super().resolve_new_version(
            action_repository, current_version, update_with, release_types
        )


CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"


def _checkout_v4() -> ResolvedVersion:
    return ResolvedVersion(
        version="v4",
        release=ReleaseInfo(
            tag_name="v4",
            html_url="https://github.com/actions/checkout/releases/tag/v4",
            published_at="2024-01-01T00:00:00Z",
        ),
    )


def _checkout_sha(tag: str = "v4.2.2") -> ResolvedVersion:
    return ResolvedVersion(
        version=CHECKOUT_SHA,
        release=ReleaseInfo(
            tag_name=tag,
            html_url=f"https://github.com/actions/checkout/releases/tag/{tag}",
            published_at="2024-01-01T00:00:00Z",
        ),
        commit=CommitInfo(
            sha=CHECKOUT_SHA,
            url=f"https://github.com/actions/checkout/commit/{CHECKOUT_SHA}",
            date="2024-01-01T00:00:00Z",
        ),
    )


def test_writes_only_changed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[Path] = []

    def write(path: Path, text: str) -> None:
        written.append(path)
        _write_text_preserving_newlines(path, text)

    monkeypatch.setattr("update_gha.scan._write_text_preserving_newlines", write)
    workflow = write_workflow(tmp_path, "ci.yml", CHECKOUT_V3)
    other = write_workflow(
        tmp_path,
        "ok.yml",
        "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n",
    )
    report = run_update(
        Configuration(write=True),
        reporter=silent_reporter(),
        client=FakeLookup({("actions/checkout", "v3"): _checkout_v4()}),
        workspace=tmp_path,
    )
    assert "actions/checkout@v4" in workflow.read_text(encoding="utf-8")
    assert other.read_text(encoding="utf-8").count("actions/checkout@v4") == 1
    assert [item.path.name for item in report.files if item.changed] == ["ci.yml"]
    assert written == [workflow]
    assert report.wrote is True


def test_preserves_crlf_through_real_io(tmp_path: Path) -> None:
    workflow = write_workflow(tmp_path, "ci.yml", "")
    original = (
        "name: CI\r\non: push\r\njobs:\r\n  a:\r\n    runs-on: ubuntu-latest\r\n"
        "    steps:\r\n      - uses: actions/checkout@v3\r\n"
    )
    workflow.write_bytes(original.encode("utf-8"))
    run_update(
        Configuration(write=True),
        reporter=silent_reporter(),
        client=FakeLookup({("actions/checkout", "v3"): _checkout_v4()}),
        workspace=tmp_path,
    )
    result = workflow.read_bytes().decode("utf-8")
    assert "actions/checkout@v4\r\n" in result
    assert result.count("\r\n") == original.count("\r\n")


@pytest.mark.parametrize(
    "settings", [{"write": False}, {"dry_run": True}, {"check": True}]
)
def test_no_write_modes_preserve_files(
    tmp_path: Path, settings: dict[str, bool]
) -> None:
    workflow = write_workflow(tmp_path, "ci.yml", CHECKOUT_V3)
    report = run_update(
        Configuration.model_validate(settings),
        reporter=silent_reporter(),
        client=FakeLookup({("actions/checkout", "v3"): _checkout_v4()}),
        workspace=tmp_path,
    )
    assert workflow.read_text(encoding="utf-8") == CHECKOUT_V3
    assert report.has_updates is True
    assert report.wrote is False
    assert report.files[0].updated == CHECKOUT_V3.replace("@v3", "@v4")


def test_empty_workspace_returns_empty_report(tmp_path: Path) -> None:
    reporter = RecordingReporter()
    report = run_update(
        Configuration(write=False),
        reporter=reporter,
        client=FakeLookup({}),
        workspace=tmp_path,
    )
    assert report.files == ()
    assert any("No workflow files found" in message for message in reporter.warnings)


def test_skips_local_and_ignored_actions(tmp_path: Path) -> None:
    workflow = write_workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  a:\n    steps:\n"
        "      - uses: ./local\n"
        "      - uses: actions/cache@v3\n"
        "      - uses: actions/checkout@v3\n",
    )
    report = run_update(
        Configuration(write=True, ignore_actions=frozenset({"actions/cache@v3"})),
        reporter=silent_reporter(),
        client=FakeLookup(
            {
                ("actions/checkout", "v3"): _checkout_v4(),
                ("actions/cache", "v3"): _checkout_v4(),
            }
        ),
        workspace=tmp_path,
    )
    updated = workflow.read_text(encoding="utf-8")
    assert "uses: ./local" in updated
    assert "actions/cache@v3" in updated
    assert "actions/checkout@v4" in updated
    assert report.has_updates is True


def test_unresolved_and_current_actions_leave_files_unchanged(tmp_path: Path) -> None:
    write_workflow(
        tmp_path,
        "none.yml",
        "jobs:\n  a:\n    steps:\n      - uses: actions/cache@v3\n",
    )
    current = write_workflow(
        tmp_path,
        "same.yml",
        "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n",
    )
    original = current.read_text(encoding="utf-8")
    report = run_update(
        Configuration(write=True),
        reporter=silent_reporter(),
        client=FakeLookup(
            {
                ("actions/cache", "v3"): None,
                ("actions/checkout", "v4"): ResolvedVersion(version="v4"),
            }
        ),
        workspace=tmp_path,
    )
    assert report.has_updates is False
    assert current.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    "value",
    [
        "docker://alpine",
        "./local/action@v1",
        "nope",
        "@",
        "owner@v1",
        "owner//@v1",
        "owner/repo@",
    ],
)
def test_split_action_rejects_unsupported_refs(value: str) -> None:
    assert _split_action(value) is None


def test_diff_is_escaped_in_job_summary(tmp_path: Path) -> None:
    write_workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v3 # <old>\n",
    )
    reporter = RecordingReporter()
    run_update(
        Configuration(write=False, show_diff=True),
        reporter=reporter,
        client=FakeLookup({("actions/checkout", "v3"): _checkout_v4()}),
        workspace=tmp_path,
    )
    assert "<summary>Git Diff</summary>" in reporter.summaries[0]
    assert "&lt;old&gt;" in reporter.summaries[0]


def test_write_preserves_mode_and_cleans_up_failed_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tmp_path / "created.yml"
    _write_text_preserving_newlines(created, "ok\n")
    assert created.read_text(encoding="utf-8") == "ok\n"

    target = tmp_path / "w.yml"
    target.write_text("old\n", encoding="utf-8")
    target.chmod(0o751)
    _write_text_preserving_newlines(target, "new\n")
    assert target.read_text(encoding="utf-8") == "new\n"
    assert target.stat().st_mode & 0o777 == 0o751

    def fail(_src: str, _dst: str) -> None:
        raise OSError("nope")

    monkeypatch.setattr("update_gha.scan.os.replace", fail)
    with pytest.raises(OSError, match="nope"):
        _write_text_preserving_newlines(target, "x")
    assert target.read_text(encoding="utf-8") == "new\n"
    assert list(tmp_path.glob(".w.yml.*.tmp")) == []


def test_invalid_yaml_skips_file_and_continues(tmp_path: Path) -> None:
    write_workflow(tmp_path, "bad.yml", "not: [valid: yaml: {{{}}\n")
    good = write_workflow(tmp_path, "good.yml", CHECKOUT_V3)
    reporter = RecordingReporter()
    report = run_update(
        Configuration(write=True),
        reporter=reporter,
        client=FakeLookup({("actions/checkout", "v3"): _checkout_v4()}),
        workspace=tmp_path,
    )
    assert any("Invalid YAML" in message for message in reporter.errors)
    assert report.has_updates is True
    assert "actions/checkout@v4" in good.read_text(encoding="utf-8")


def test_unrewritable_token_does_not_block_other_actions(tmp_path: Path) -> None:
    workflow = write_workflow(
        tmp_path,
        "split.yml",
        "jobs:\n  a:\n    steps:\n"
        "      - uses: actions/setup-python@v3\n"
        '      - uses: "actions/checkout@\\\nv3"\n',
    )
    other = write_workflow(
        tmp_path,
        "other.yml",
        "jobs:\n  a:\n    steps:\n      - uses: actions/cache@v3\n",
    )
    reporter = RecordingReporter()
    report = run_update(
        Configuration(write=True),
        reporter=reporter,
        client=FakeLookup(
            {
                ("actions/setup-python", "v3"): ResolvedVersion(version="v4"),
                ("actions/checkout", "v3"): _checkout_v4(),
                ("actions/cache", "v3"): ResolvedVersion(version="v4"),
            }
        ),
        workspace=tmp_path,
    )
    updated = workflow.read_text(encoding="utf-8")
    assert "actions/setup-python@v4" in updated
    assert "actions/checkout@v4" not in updated
    assert "actions/cache@v4" in other.read_text(encoding="utf-8")
    assert any("Could not rewrite" in message for message in reporter.errors)
    assert {item.path.name for item in report.files if item.changed} == {
        "split.yml",
        "other.yml",
    }


def test_invalid_rewrite_skips_that_file_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = write_workflow(tmp_path, "broken.yml", CHECKOUT_V3)
    good = write_workflow(
        tmp_path,
        "good.yml",
        "steps:\n  - uses: actions/setup-python@v3\n",
    )

    def rewrite(
        text: str,
        updates: dict[str, str],
        *,
        spans: tuple[tuple[int, int, str, str | None], ...] | None = None,
    ) -> str:
        if "actions/checkout@v3" in text:
            return "["
        from update_gha.rewrite import apply_version_updates

        return apply_version_updates(text, updates, spans=spans)

    monkeypatch.setattr("update_gha.scan.apply_version_updates", rewrite)
    reporter = RecordingReporter()
    report = run_update(
        Configuration(write=True),
        reporter=reporter,
        client=FakeLookup(
            {
                ("actions/checkout", "v3"): _checkout_v4(),
                ("actions/setup-python", "v3"): ResolvedVersion(version="v4"),
            }
        ),
        workspace=tmp_path,
    )
    assert any("produced invalid YAML" in message for message in reporter.errors)
    assert broken.read_text(encoding="utf-8") == CHECKOUT_V3
    assert "actions/setup-python@v4" in good.read_text(encoding="utf-8")
    assert report.has_updates is True


def test_existing_target_pin_does_not_hide_an_unrewritable_pin(tmp_path: Path) -> None:
    original = (
        '- uses: "actions/checkout@\\\nv3"\n'
        "- uses: actions/checkout@v4\n"
        "- uses: actions/setup-python@v3\n"
    )
    workflow = write_workflow(tmp_path, "ci.yml", original)
    reporter = RecordingReporter()
    report = run_update(
        Configuration(),
        reporter=reporter,
        client=FakeLookup(
            {
                ("actions/checkout", "v3"): _checkout_v4(),
                ("actions/setup-python", "v3"): ResolvedVersion(version="v4"),
            }
        ),
        workspace=tmp_path,
    )
    assert workflow.read_text() == original.replace(
        "setup-python@v3", "setup-python@v4"
    )
    assert [item.repository for item in report.action_updates] == [
        "actions/setup-python"
    ]
    assert any("Could not rewrite" in message for message in reporter.errors)


def test_run_update_creates_and_closes_owned_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[bool] = []

    class Tracking(GitHubClient):
        def __init__(
            self,
            token: SecretStr | None,
            reporter: Reporter,
            session: HttpSession | None = None,
        ) -> None:
            super().__init__(SecretStr("t"), silent_reporter(), session=FakeSession({}))
            closed.append(False)

        def close(self) -> None:
            closed[:] = [True]
            super().close()

    monkeypatch.setattr("update_gha.scan.GitHubClient", Tracking)
    run_update(Configuration(write=False), workspace=tmp_path)
    assert closed == [True]


def test_github_lookup_failure_skips_action_not_others(tmp_path: Path) -> None:
    workflow = write_workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  a:\n    steps:\n"
        "      - uses: actions/missing@v1\n"
        "      - uses: actions/checkout@v3\n",
    )
    write_workflow(
        tmp_path,
        "other.yml",
        "jobs:\n  a:\n    steps:\n      - uses: actions/missing@v1\n",
    )
    reporter = RecordingReporter()
    report = run_update(
        Configuration(write=True),
        reporter=reporter,
        client=RaisingLookup({("actions/checkout", "v3"): _checkout_v4()}),
        workspace=tmp_path,
    )
    updated = workflow.read_text(encoding="utf-8")
    assert "actions/missing@v1" in updated
    assert "actions/checkout@v4" in updated
    assert report.has_updates is True
    assert (
        reporter.errors.count(
            'Could not check "actions/missing" for updates: HTTP 404: Not Found'
        )
        == 1
    )


def test_write_error_skips_file_not_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = write_workflow(tmp_path, "bad.yml", CHECKOUT_V3)
    good = write_workflow(
        tmp_path,
        "good.yml",
        "steps:\n  - uses: actions/setup-python@v3\n",
    )
    original_replace = os.replace

    def replace(src: str, dst: str) -> None:
        if Path(dst).name == "bad.yml":
            raise OSError("disk full")
        original_replace(src, dst)

    monkeypatch.setattr("update_gha.scan.os.replace", replace)
    reporter = RecordingReporter()
    report = run_update(
        Configuration(write=True),
        reporter=reporter,
        client=FakeLookup(
            {
                ("actions/checkout", "v3"): _checkout_v4(),
                ("actions/setup-python", "v3"): ResolvedVersion(version="v4"),
            }
        ),
        workspace=tmp_path,
    )
    assert any("Could not write" in message for message in reporter.errors)
    assert "actions/checkout@v3" in bad.read_text(encoding="utf-8")
    assert "actions/setup-python@v4" in good.read_text(encoding="utf-8")
    assert report.wrote is True


def test_unreadable_file_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = write_workflow(tmp_path, "blocked.yml", CHECKOUT_V3)
    good = write_workflow(tmp_path, "good.yml", CHECKOUT_V3)
    original_read = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        if self.name == "blocked.yml":
            raise PermissionError("denied")
        return original_read(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    reporter = RecordingReporter()
    report = run_update(
        Configuration(write=True),
        reporter=reporter,
        client=FakeLookup({("actions/checkout", "v3"): _checkout_v4()}),
        workspace=tmp_path,
    )
    assert any("Could not read" in message for message in reporter.errors)
    assert "actions/checkout@v3" in blocked.read_text(encoding="utf-8")
    assert "actions/checkout@v4" in good.read_text(encoding="utf-8")
    assert report.has_updates is True


def test_release_commit_sha_writes_tag_comment(tmp_path: Path) -> None:
    workflow = write_workflow(tmp_path, "ci.yml", CHECKOUT_V3)
    report = run_update(
        Configuration(
            write=True,
            update_version_with=UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
        ),
        reporter=silent_reporter(),
        client=FakeLookup({("actions/checkout", "v3"): _checkout_sha()}),
        workspace=tmp_path,
    )
    assert workflow.read_text(encoding="utf-8") == (
        f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{CHECKOUT_SHA}"
        "  # v4.2.2\n"
    )
    assert report.has_updates is True
    assert report.action_updates[0].new_version == CHECKOUT_SHA


def test_release_commit_sha_updates_existing_tag_comment(tmp_path: Path) -> None:
    workflow = write_workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v3  # 0.3.1\n",
    )
    run_update(
        Configuration(
            write=True,
            update_version_with=UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
        ),
        reporter=silent_reporter(),
        client=FakeLookup({("actions/checkout", "v3"): _checkout_sha("1.0.0")}),
        workspace=tmp_path,
    )
    assert workflow.read_text(encoding="utf-8") == (
        f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{CHECKOUT_SHA}"
        "  # 1.0.0\n"
    )


def test_release_commit_sha_keeps_custom_comment(tmp_path: Path) -> None:
    workflow = write_workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v3 # keep me\n",
    )
    run_update(
        Configuration(
            write=True,
            update_version_with=UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
        ),
        reporter=silent_reporter(),
        client=FakeLookup({("actions/checkout", "v3"): _checkout_sha()}),
        workspace=tmp_path,
    )
    assert workflow.read_text(encoding="utf-8") == (
        f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{CHECKOUT_SHA}"
        " # keep me\n"
    )


def test_release_tag_mode_does_not_add_comment(tmp_path: Path) -> None:
    workflow = write_workflow(tmp_path, "ci.yml", CHECKOUT_V3)
    run_update(
        Configuration(write=True),
        reporter=silent_reporter(),
        client=FakeLookup({("actions/checkout", "v3"): _checkout_v4()}),
        workspace=tmp_path,
    )
    assert workflow.read_text(encoding="utf-8") == (
        "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n"
    )


def test_default_branch_sha_does_not_add_comment(tmp_path: Path) -> None:
    workflow = write_workflow(tmp_path, "ci.yml", CHECKOUT_V3)
    resolved = ResolvedVersion(
        version=CHECKOUT_SHA,
        commit=CommitInfo(sha=CHECKOUT_SHA, url="u", date="d"),
    )
    run_update(
        Configuration(
            write=True,
            update_version_with=UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA,
        ),
        reporter=silent_reporter(),
        client=FakeLookup({("actions/checkout", "v3"): resolved}),
        workspace=tmp_path,
    )
    assert workflow.read_text(encoding="utf-8") == (
        f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{CHECKOUT_SHA}\n"
    )


def test_stale_tag_comment_on_current_sha_is_replaced(tmp_path: Path) -> None:
    workflow = write_workflow(
        tmp_path,
        "ci.yml",
        f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{CHECKOUT_SHA}"
        " # v3.5.0\n",
    )
    report = run_update(
        Configuration(
            write=True,
            update_version_with=UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
        ),
        reporter=silent_reporter(),
        client=FakeLookup(
            {("actions/checkout", CHECKOUT_SHA): _checkout_sha("v4.2.2")}
        ),
        workspace=tmp_path,
    )
    assert workflow.read_text(encoding="utf-8") == (
        f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{CHECKOUT_SHA}"
        "  # v4.2.2\n"
    )
    assert report.has_updates is True
    assert report.action_updates[0].old_version == CHECKOUT_SHA
    assert report.action_updates[0].new_version == CHECKOUT_SHA


def test_current_sha_with_correct_comment_is_unchanged(tmp_path: Path) -> None:
    original = (
        f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{CHECKOUT_SHA}"
        "  # v4.2.2\n"
    )
    workflow = write_workflow(tmp_path, "ci.yml", original)
    report = run_update(
        Configuration(
            write=True,
            update_version_with=UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
        ),
        reporter=silent_reporter(),
        client=FakeLookup(
            {("actions/checkout", CHECKOUT_SHA): _checkout_sha("v4.2.2")}
        ),
        workspace=tmp_path,
    )
    assert workflow.read_text(encoding="utf-8") == original
    assert report.has_updates is False
    assert report.action_updates == ()


def test_current_sha_without_comment_gets_tag_comment(tmp_path: Path) -> None:
    workflow = write_workflow(
        tmp_path,
        "ci.yml",
        f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{CHECKOUT_SHA}\n",
    )
    report = run_update(
        Configuration(
            write=True,
            update_version_with=UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
        ),
        reporter=silent_reporter(),
        client=FakeLookup(
            {("actions/checkout", CHECKOUT_SHA): _checkout_sha("v4.2.2")}
        ),
        workspace=tmp_path,
    )
    assert workflow.read_text(encoding="utf-8") == (
        f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{CHECKOUT_SHA}"
        "  # v4.2.2\n"
    )
    assert report.has_updates is True


@pytest.mark.parametrize("comment", ["  # v4.2.2", "  # pin for security"])
def test_unchanged_sha_is_not_reported_when_another_pin_changes(
    tmp_path: Path, comment: str
) -> None:
    workflow = write_workflow(
        tmp_path,
        "ci.yml",
        f"- uses: actions/checkout@{CHECKOUT_SHA}{comment}\n- uses: other/action@v1\n",
    )
    reporter = RecordingReporter()
    report = run_update(
        Configuration(update_version_with=UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA),
        reporter=reporter,
        client=FakeLookup(
            {
                ("actions/checkout", CHECKOUT_SHA): _checkout_sha(),
                ("other/action", "v1"): _checkout_sha(),
            }
        ),
        workspace=tmp_path,
    )
    assert workflow.read_text() == (
        f"- uses: actions/checkout@{CHECKOUT_SHA}{comment}\n"
        f"- uses: other/action@{CHECKOUT_SHA}  # v4.2.2\n"
    )
    assert [update.repository for update in report.action_updates] == ["other/action"]
    assert "Updated 1 actions in 1 files." in report.text_summary()
    assert "* **[actions/checkout]" not in report.pull_request_body()


def test_example_tokens_do_not_prevent_workflow_updates(
    tmp_path: Path,
) -> None:
    example = "ghp_" + "A" * 40
    original = f"# Example: {example}\n{CHECKOUT_V3}"
    workflow = write_workflow(tmp_path, "ci.yml", original)
    reporter = RecordingReporter()
    report = run_update(
        Configuration(show_diff=True),
        reporter=reporter,
        client=FakeLookup({("actions/checkout", "v3"): _checkout_v4()}),
        workspace=tmp_path,
    )
    assert report.has_updates is True
    assert report.wrote is True
    assert workflow.read_text() == original.replace("checkout@v3", "checkout@v4")
    assert reporter.errors == []


def test_release_tag_comment_helper() -> None:
    sha = _checkout_sha()
    assert (
        _release_tag_comment(UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA, sha)
        == "v4.2.2"
    )
    assert _release_tag_comment(UpdateVersionWith.LATEST_RELEASE_TAG, sha) is None
    assert (
        _release_tag_comment(
            UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
            ResolvedVersion(version=CHECKOUT_SHA),
        )
        is None
    )
    assert (
        _release_tag_comment(
            UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
            ResolvedVersion(
                version=CHECKOUT_SHA,
                release=ReleaseInfo(tag_name="  ", html_url="u", published_at="p"),
            ),
        )
        is None
    )
    assert (
        _release_tag_comment(
            UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
            ResolvedVersion(
                version=CHECKOUT_SHA,
                release=ReleaseInfo(
                    tag_name="v4\n.2.2", html_url="u", published_at="p"
                ),
            ),
        )
        is None
    )


def test_scanner_omits_api_response_body(tmp_path: Path) -> None:
    secret = "fixture-sensitive-token"
    write_workflow(tmp_path, "ci.yml", CHECKOUT_V3)
    reporter = RecordingReporter()
    url = "https://api.github.com/repos/actions/checkout/releases?per_page=100"
    report = run_update(
        Configuration.model_validate({"token": secret}),
        reporter=reporter,
        session=FakeSession(
            {url: FakeResponse(401, {"message": "response-sensitive-value"})}
        ),
        workspace=tmp_path,
    )
    assert report.has_updates is False
    assert "HTTP 401: authentication failed" in reporter.errors[0]
    assert "response-sensitive-value" not in "".join(reporter.errors)
