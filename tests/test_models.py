"""Report formatting and serialization."""

from __future__ import annotations

from pathlib import Path

from packaging.version import Version

from update_gha.models import (
    ActionUpdate,
    BranchInfo,
    CommitInfo,
    FileUpdate,
    ReleaseInfo,
    ResolvedVersion,
    UpdateReport,
    UpdateVersionWith,
)


def _update(
    *,
    location: str = "o/r",
    old_version: str = "v1",
    new_version: str,
    resolved: ResolvedVersion,
    update_version_with: UpdateVersionWith,
) -> ActionUpdate:
    return ActionUpdate(
        repository="o/r",
        location=location,
        old_version=old_version,
        new_version=new_version,
        resolved=resolved,
        update_version_with=update_version_with,
    )


def test_markdown_line_for_release_tag() -> None:
    line = _update(
        new_version="v2",
        resolved=ResolvedVersion(
            version="v2",
            release=ReleaseInfo(tag_name="v2", html_url="r", published_at="p"),
        ),
        update_version_with=UpdateVersionWith.LATEST_RELEASE_TAG,
    ).markdown_line()
    assert line == (
        "* **[o/r](https://github.com/o/r)** published a new release **[v2](r)** on p\n"
    )


def test_markdown_line_for_release_commit() -> None:
    line = _update(
        new_version="abc",
        resolved=ResolvedVersion(
            version="abc",
            release=ReleaseInfo(tag_name="v2", html_url="r", published_at="p"),
            commit=CommitInfo(sha="a", url="u", date="d"),
        ),
        update_version_with=UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
    ).markdown_line()
    assert line == (
        "* **[o/r](https://github.com/o/r)** added a new **[commit](u)** to "
        "**[v2](r)** Tag on d\n"
    )


def test_markdown_line_for_default_branch() -> None:
    line = _update(
        new_version="def",
        resolved=ResolvedVersion(
            version="def",
            branch=BranchInfo(
                name="main",
                url="b",
                commit=CommitInfo(sha="a", url="u", date="d"),
            ),
        ),
        update_version_with=UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA,
    ).markdown_line()
    assert line == (
        "* **[o/r](https://github.com/o/r)** added a new **[commit](u)** to "
        "**[main](b)** branch on d\n"
    )


def test_markdown_line_fallback() -> None:
    line = _update(
        new_version="x",
        resolved=ResolvedVersion(version="x"),
        update_version_with=UpdateVersionWith.LATEST_RELEASE_TAG,
    ).markdown_line()
    assert line == ("* **[o/r](https://github.com/o/r)** updated from `v1` to `x`\n")


def test_report_summary_deduplicates_actions(tmp_path: Path) -> None:
    action = _update(
        location="actions/checkout",
        old_version="v3",
        new_version="v4",
        resolved=ResolvedVersion(version="v4"),
        update_version_with=UpdateVersionWith.LATEST_RELEASE_TAG,
    )
    report = UpdateReport(
        files=(
            FileUpdate(
                path=tmp_path / "a.yml",
                original="old\n",
                updated="new\n",
                actions=(action,),
            ),
            FileUpdate(
                path=tmp_path / "b.yml",
                original="old\n",
                updated="new\n",
                actions=(action,),
            ),
            FileUpdate(
                path=tmp_path / "c.yml",
                original="same\n",
                updated="same\n",
                actions=(),
            ),
        )
    )
    assert report.has_updates is True
    assert report.action_updates == (action,)
    assert report.text_summary() == (
        "actions/checkout  v3  ->  v4\n\nUpdated 1 actions in 2 files."
    )
    assert report.pull_request_body() == (
        "### GitHub Actions Version Updates\n"
        "* **[o/r](https://github.com/o/r)** updated from `v3` to `v4`\n"
    )


def test_empty_report_text_summary() -> None:
    assert UpdateReport(files=()).text_summary() == "Everything is up-to-date."
    assert UpdateReport(files=()).has_updates is False


def test_release_tag_version_serializes_to_string() -> None:
    payload = ReleaseInfo(
        tag_name="v4.1.0",
        html_url="https://example.com",
        published_at="2024-01-01T00:00:00Z",
        tag_version=Version("4.1.0"),
    ).model_dump_json()
    assert '"tag_version":"4.1.0"' in payload
    assert (
        ReleaseInfo(
            tag_name="latest",
            html_url="https://example.com",
            published_at="2024-01-01T00:00:00Z",
        ).model_dump()["tag_version"]
        is None
    )
