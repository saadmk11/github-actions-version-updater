"""CLI tests for ``update-gha``."""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from tests.conftest import pull_request_context
from update_gha.action import has_action_extra
from update_gha.cli.main import app
from update_gha.config import Configuration
from update_gha.github import GitHubAPIError
from update_gha.log import Reporter
from update_gha.models import (
    ActionUpdate,
    FileUpdate,
    ReleaseInfo,
    ResolvedVersion,
    UpdateReport,
    UpdateVersionWith,
)

if TYPE_CHECKING:
    from update_gha.action.run import PullRequestContext

requires_action = pytest.mark.skipif(
    not has_action_extra(), reason="Requires the optional [action] integration"
)

runner = CliRunner()
_RUN_UPDATE = "update_gha.cli.main.run_update"


def _report(
    tmp_path: Path, *, changed: bool, wrote: bool | None = None
) -> UpdateReport:
    original = "- uses: actions/checkout@v3\n"
    updated = "- uses: actions/checkout@v4\n" if changed else original
    path = tmp_path / "workflow.yml"
    path.write_text(original, encoding="utf-8")
    action = ActionUpdate(
        repository="actions/checkout",
        location="actions/checkout",
        old_version="v3",
        new_version="v4",
        resolved=ResolvedVersion(
            version="v4",
            release=ReleaseInfo(
                tag_name="v4",
                html_url="https://github.com/actions/checkout/releases/tag/v4",
                published_at="2024-01-01T00:00:00Z",
            ),
        ),
        update_version_with=UpdateVersionWith.LATEST_RELEASE_TAG,
    )
    return UpdateReport(
        files=(
            FileUpdate(
                path=path,
                original=original,
                updated=updated,
                actions=(action,) if changed else (),
            ),
        ),
        wrote=changed if wrote is None else wrote,
    )


def _stub_run_update(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    changed: bool,
    wrote: bool | None = None,
) -> None:
    monkeypatch.setattr(
        _RUN_UPDATE,
        lambda _config, **_kwargs: _report(tmp_path, changed=changed, wrote=wrote),
    )


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    output = " ".join(result.stdout.replace("│", " ").split())
    assert "--pull-request" in output
    assert "--check" in output
    assert "Required for --pull-request and for private action repos" in output
    assert "Required with --pull-request" in output
    assert "release-tag (default) writes the latest stable tag" in output
    assert "# tag comment" in output
    assert "Unlike --check, a pending update is not a failure" in output
    assert "update-gha[action]" in output
    assert "OWNER/REPO" in output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_check_exits_one_when_updates_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_run_update(monkeypatch, tmp_path, changed=True)
    result = runner.invoke(app, ["--check"])
    assert result.exit_code == 1
    assert "actions/checkout" in result.stdout


def test_check_exits_zero_when_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_run_update(monkeypatch, tmp_path, changed=False)
    result = runner.invoke(app, ["--check"])
    assert result.exit_code == 0


def test_fail_on_update_writes_then_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes: list[bool] = []

    def fake_run_update(config: Configuration, *, reporter: Reporter) -> UpdateReport:
        writes.append(config.should_write())
        return _report(tmp_path, changed=True)

    monkeypatch.setattr(_RUN_UPDATE, fake_run_update)
    result = runner.invoke(app, ["--fail-on-update"])
    assert result.exit_code == 1
    assert writes == [True]
    assert "failing as requested" in result.stderr


def test_fail_on_update_exits_zero_when_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_run_update(monkeypatch, tmp_path, changed=False)
    assert runner.invoke(app, ["--fail-on-update"]).exit_code == 0


def test_fail_on_update_exits_zero_when_writes_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_run_update(monkeypatch, tmp_path, changed=True, wrote=False)
    result = runner.invoke(app, ["--fail-on-update"])
    assert result.exit_code == 0


def test_fail_on_update_rejects_pull_request_before_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[bool] = []
    monkeypatch.setattr(
        _RUN_UPDATE,
        lambda *_args, **_kwargs: called.append(True),
    )
    result = runner.invoke(app, ["--fail-on-update", "--pull-request"])
    assert result.exit_code == 2
    assert called == []


def test_fail_on_update_rejects_no_write_modes() -> None:
    result = runner.invoke(app, ["--fail-on-update", "--check"])
    assert result.exit_code == 2
    assert "requires file writing" in result.output


def test_json_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_run_update(monkeypatch, tmp_path, changed=True)
    result = runner.invoke(app, ["--format", "json", "--dry-run"])
    assert result.exit_code == 0
    assert '"old_version": "v3"' in result.stdout


def test_dry_run_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrote: list[bool] = []

    def fake_run_update(config: Configuration, *, reporter: Reporter) -> UpdateReport:
        wrote.append(config.should_write())
        return _report(tmp_path, changed=True)

    monkeypatch.setattr(_RUN_UPDATE, fake_run_update)
    result = runner.invoke(app, ["--dry-run"])
    assert result.exit_code == 0
    assert wrote == [False]


def test_pull_request_requires_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(
        _RUN_UPDATE,
        lambda *_args, **_kwargs: called.append(True),
    )
    monkeypatch.setattr("update_gha.cli.main.has_action_extra", lambda: False)
    result = runner.invoke(app, ["--pull-request"])
    assert result.exit_code == 2
    assert called == []


@requires_action
def test_pull_request_requires_github_values_before_updating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[bool] = []
    monkeypatch.setattr(
        _RUN_UPDATE,
        lambda *_args, **_kwargs: called.append(True),
    )
    result = runner.invoke(app, ["--pull-request"])
    assert result.exit_code == 1
    assert called == []


@requires_action
def test_pull_request_skipped_when_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[bool] = []
    _stub_run_update(monkeypatch, tmp_path, changed=True)

    def fake_run(
        _config: Configuration,
        _reporter: Reporter,
        *,
        body: str,
        paths: Sequence[Path] = (),
        context: PullRequestContext | None = None,
    ) -> int:
        called.append(True)
        return 0

    monkeypatch.setattr("update_gha.action.run.run", fake_run)
    result = runner.invoke(app, ["--pull-request", "--dry-run"])
    assert result.exit_code == 0
    assert called == []


@requires_action
def test_pull_request_runs_when_updates_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bodies: list[str] = []
    _stub_run_update(monkeypatch, tmp_path, changed=True)
    monkeypatch.setattr(
        "update_gha.action.run.prepare", lambda *_args: pull_request_context(tmp_path)
    )

    def fake_run(
        _config: Configuration,
        _reporter: Reporter,
        *,
        body: str,
        paths: Sequence[Path],
        context: PullRequestContext | None,
    ) -> int:
        bodies.append(body)
        assert paths and paths[0].name == "workflow.yml"
        assert context is not None
        return 0

    monkeypatch.setattr("update_gha.action.run.run", fake_run)
    result = runner.invoke(
        app,
        ["--pull-request", "--token", "token-token", "--repository", "o/r"],
    )
    assert result.exit_code == 0
    assert bodies
    assert bodies[0].startswith("### GitHub Actions Version Updates")


@requires_action
@pytest.mark.parametrize(
    "error",
    [
        OSError("push failed"),
        GitHubAPIError("API unavailable"),
        ValueError("invalid response"),
    ],
)
def test_pull_request_runtime_error_is_reported_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    _stub_run_update(monkeypatch, tmp_path, changed=True)
    monkeypatch.setattr(
        "update_gha.action.run.prepare", lambda *_args: pull_request_context(tmp_path)
    )

    def fail(
        config: Configuration,
        reporter: Reporter,
        *,
        body: str,
        paths: Sequence[Path],
        context: PullRequestContext | None,
    ) -> int:
        raise error

    monkeypatch.setattr("update_gha.action.run.run", fail)
    result = runner.invoke(
        app,
        ["--pull-request", "--token", "token-token", "--repository", "o/r"],
    )
    assert result.exit_code == 1
    assert str(error) in result.stderr
    assert "Traceback" not in result.output


@requires_action
def test_pull_request_skipped_when_up_to_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[bool] = []
    _stub_run_update(monkeypatch, tmp_path, changed=False)
    monkeypatch.setattr(
        "update_gha.action.run.prepare", lambda *_args: pull_request_context(tmp_path)
    )

    def fake_run(
        _config: Configuration,
        _reporter: Reporter,
        *,
        body: str,
        paths: Sequence[Path] = (),
        context: PullRequestContext | None = None,
    ) -> int:
        called.append(True)
        return 0

    monkeypatch.setattr("update_gha.action.run.run", fake_run)
    result = runner.invoke(
        app,
        ["--pull-request", "--token", "token-token", "--repository", "o/r"],
    )
    assert result.exit_code == 0
    assert called == []


def test_verbose_and_quiet_are_mutually_exclusive() -> None:
    result = runner.invoke(app, ["--verbose", "--quiet"])
    assert result.exit_code == 2


def test_verbose_and_quiet_set_log_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import logging

    _stub_run_update(monkeypatch, tmp_path, changed=False)
    assert runner.invoke(app, ["--verbose", "--dry-run"]).exit_code == 0
    assert logging.getLogger("update_gha").level == logging.DEBUG
    assert runner.invoke(app, ["--quiet", "--dry-run"]).exit_code == 0
    assert logging.getLogger("update_gha").level == logging.WARNING


def test_no_pull_request_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Configuration] = []

    def fake_run_update(config: Configuration, *, reporter: Reporter) -> UpdateReport:
        seen.append(config)
        return _report(tmp_path, changed=True)

    monkeypatch.setenv("GHA_UPDATE_CREATE_PULL_REQUEST", "true")
    monkeypatch.setattr(_RUN_UPDATE, fake_run_update)
    result = runner.invoke(app, ["--no-pull-request"])
    assert result.exit_code == 0
    assert seen[0].create_pull_request is False


def test_check_from_environment_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_run_update(monkeypatch, tmp_path, changed=True)
    monkeypatch.setenv("GHA_UPDATE_CHECK", "true")
    result = runner.invoke(app, [])
    assert result.exit_code == 1


def test_json_stdout_is_clean_on_github_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _report(tmp_path, changed=True)

    def fake_run_update(_config: Configuration, *, reporter: Reporter) -> UpdateReport:
        reporter.info("progress")
        reporter.warning("warning")
        with reporter.group("group"):
            pass
        return report

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(_RUN_UPDATE, fake_run_update)
    result = runner.invoke(app, ["--format", "json", "--dry-run"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["files"]
    assert "progress" in result.stderr


def test_json_stdout_stays_clean_with_utility_subprocess_setting(
    tmp_path: Path,
) -> None:
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("GITHUB_", "GHA_UPDATE_"))
    }
    env.update(GITHUB_ACTIONS="true", COMMANDS_USE_SUBPROCESS="1")
    result = subprocess.run(
        [sys.executable, "-m", "update_gha", "--dry-run", "--format", "json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == {"files": [], "wrote": False}
    assert "No workflow files found" in result.stderr


def test_oserror_from_run_update_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_config: Configuration, *, reporter: Reporter) -> None:
        raise OSError("disk")

    monkeypatch.setattr(_RUN_UPDATE, boom)
    result = runner.invoke(app, ["--dry-run"])
    assert result.exit_code == 1
    assert "disk" in result.stderr


@requires_action
def test_pull_request_skipped_when_writes_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[bool] = []
    _stub_run_update(monkeypatch, tmp_path, changed=True, wrote=False)
    monkeypatch.setattr(
        "update_gha.action.run.prepare", lambda *_args: pull_request_context(tmp_path)
    )

    def fake_run(
        _config: Configuration,
        _reporter: Reporter,
        *,
        body: str,
        paths: Sequence[Path] = (),
        context: PullRequestContext | None = None,
    ) -> int:
        called.append(True)
        return 0

    monkeypatch.setattr("update_gha.action.run.run", fake_run)
    result = runner.invoke(
        app,
        ["--pull-request", "--token", "token-token", "--repository", "o/r"],
    )
    assert result.exit_code == 0
    assert called == []
    assert "no updated files could be written" in result.stderr


def test_invalid_environment_configuration_exits_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GHA_UPDATE_RELEASE_TYPES", "invalid")
    result = runner.invoke(app, [])
    assert result.exit_code == 2
    assert "Invalid value" in result.stderr


@requires_action
def test_pull_request_preflight_runs_before_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[bool] = []
    monkeypatch.setattr(_RUN_UPDATE, lambda *_args, **_kwargs: called.append(True))
    result = runner.invoke(
        app,
        [
            "--pull-request",
            "--token",
            "token-token",
            "--repository",
            "o/r",
            "--pull-request-branch",
            "main",
        ],
    )
    assert result.exit_code == 1
    assert called == []


def test_diff_prints_changed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = UpdateReport(
        files=(
            FileUpdate(
                path=tmp_path / "changed.yml",
                original="old\n",
                updated="new\n",
                actions=(),
            ),
            FileUpdate(
                path=tmp_path / "same.yml",
                original="keep\n",
                updated="keep\n",
                actions=(),
            ),
        )
    )

    monkeypatch.setattr(_RUN_UPDATE, lambda _config, **_kwargs: report)
    result = runner.invoke(app, ["--diff", "--dry-run"])
    assert result.exit_code == 0
    assert "changed.yml" in result.stdout
    assert "+new\n" in result.stdout
    assert "same.yml" not in result.stdout


@pytest.mark.parametrize("run_name", ["__main__", "imported_entrypoint"])
def test_module_entrypoint_dispatches_only_when_executed(
    run_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[bool] = []
    monkeypatch.setattr("update_gha.cli.app", lambda: called.append(True))
    runpy.run_module("update_gha.__main__", run_name=run_name)
    assert called == ([True] if run_name == "__main__" else [])
