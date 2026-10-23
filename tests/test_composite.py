"""Public action inputs, outputs, and CLI invocation."""

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import NotRequired

import pytest
import yaml
from pydantic import SecretStr, TypeAdapter
from typer.testing import CliRunner
from typing_extensions import TypedDict

from tests.conftest import pull_request_context
from tests.packaging.check import project_version, validate_release
from update_gha.action import has_action_extra
from update_gha.cli import app
from update_gha.config import Configuration
from update_gha.log import Reporter
from update_gha.models import ReleaseType, UpdateReport, UpdateVersionWith

ROOT = Path(__file__).resolve().parents[1]


class ActionInput(TypedDict):
    required: bool
    default: NotRequired[str]


ActionStep = TypedDict(
    "ActionStep",
    {
        "id": NotRequired[str],
        "uses": NotRequired[str],
        "with": NotRequired[dict[str, str]],
        "shell": NotRequired[str],
        "env": NotRequired[dict[str, str]],
        "run": NotRequired[str],
    },
)


class ActionRuns(TypedDict):
    using: str
    steps: list[ActionStep]


class ActionMetadata(TypedDict):
    inputs: dict[str, ActionInput]
    outputs: dict[str, dict[str, str]]
    runs: ActionRuns


def _action() -> ActionMetadata:
    return TypeAdapter(ActionMetadata).validate_python(
        yaml.safe_load((ROOT / "action.yaml").read_text()),
        strict=True,
    )


def _update_step(action: ActionMetadata) -> ActionStep:
    return next(step for step in action["runs"]["steps"] if step.get("id") == "update")


def test_composite_input_output_contract() -> None:
    # Published v1.0.1, source commit a5ab9b51373a6dbfd2732a985e60ef23e172792a.
    expected = {
        "committer_username": (False, "github-actions[bot]"),
        "committer_email": (False, "github-actions[bot]@users.noreply.github.com"),
        "commit_message": (False, "Update GitHub Action Versions"),
        "pull_request_title": (False, "Update GitHub Action Versions"),
        "pull_request_branch": (False, ""),
        "ignore": (False, ""),
        "token": (True, ""),
        "skip_pull_request": (False, "false"),
        "update_version_with": (False, "release-tag"),
        "release_types": (False, "all"),
        "pull_request_user_reviewers": (False, ""),
        "pull_request_team_reviewers": (False, ""),
        "pull_request_labels": (False, ""),
        "extra_workflow_locations": (False, ""),
    }
    action = _action()
    assert {
        name: (item["required"], item.get("default", ""))
        for name, item in action["inputs"].items()
    } == expected
    assert set(action["outputs"]) == {"GHA_UPDATE_PR_NUMBER", "pull-request-number"}
    assert action["runs"]["using"] == "composite"
    setup = next(step for step in action["runs"]["steps"] if step.get("id") == "uv")
    invoke = _update_step(action)
    assert re.search(r"@[0-9a-f]{40}$", setup["uses"])
    assert setup["with"]["enable-cache"] == "false"
    for name in action["inputs"]:
        assert "${{ inputs." + name + " }}" in invoke["env"].values()
    for name, output in action["outputs"].items():
        assert output["value"] == "${{ steps.update.outputs." + name + " }}"
    assert invoke["shell"] == "bash"
    assert "${{" not in invoke["run"]


def _invoke_composite(
    tmp_path: Path, **inputs: str
) -> tuple[list[str], dict[str, str]]:
    action = _action()
    invoke = _update_step(action)
    values = {
        name: input_.get("default", "") for name, input_ in action["inputs"].items()
    } | inputs
    env = {}
    for name, value in invoke["env"].items():
        match = re.fullmatch(r"\$\{\{ inputs\.(\w+) }}", value)
        env[name] = values[match[1]] if match else value
    fake_uv = tmp_path / "uv with spaces"
    capture = (
        "import json, os, sys; print(json.dumps([sys.argv[1:], "
        "{k: v for k, v in os.environ.items() "
        'if k.startswith(("GITHUB_", "GHA_UPDATE_"))}]))'
    )
    fake_uv.write_text(
        "#!/bin/bash\nset -eu\n"
        'test -z "${UV_INDEX-}${PIP_INDEX_URL-}${PYTHONPATH-}${VIRTUAL_ENV-}"\n'
        'test "$UV_CACHE_DIR" = "$RUNNER_TEMP/update-gha/uv-cache"\n'
        'test "$UV_PYTHON_INSTALL_DIR" = "$RUNNER_TEMP/update-gha/python"\n'
        'test "$UV_TOOL_DIR" = "$RUNNER_TEMP/update-gha/tools"\n'
        f'exec {shlex.quote(sys.executable)} -c {shlex.quote(capture)} "$@"\n'
    )
    fake_uv.chmod(0o755)
    env = dict(
        os.environ,
        **env,
    )
    env.update(
        UPDATE_GHA_UV=str(fake_uv),
        RUNNER_TEMP=str(tmp_path),
        UV_INDEX="https://example.com/simple",
        PIP_INDEX_URL="https://example.com/simple",
        PYTHONPATH="untrusted",
        VIRTUAL_ENV="untrusted",
    )
    result = subprocess.run(
        ["bash", "-e", "-u", "-o", "pipefail", "-c", invoke["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return TypeAdapter(tuple[list[str], dict[str, str]]).validate_json(result.stdout)


@pytest.mark.skipif(
    os.name == "nt", reason="Composite action requires bash on a Unix runner"
)
@pytest.mark.parametrize("skip", ["false", "true", "True", "TRUE", "1", "yes"])
def test_composite_preserves_cli_and_skip_behavior(tmp_path: Path, skip: str) -> None:
    message = '$(touch injected); "quoted"\nUnicode: café %0A'
    arguments, _ = _invoke_composite(
        tmp_path,
        commit_message=message,
        skip_pull_request=skip,
    )
    version = project_version()
    assert {"--no-config", "--isolated", "--no-env-file", "--managed-python"} <= set(
        arguments
    )
    assert arguments[arguments.index("tool") + 1] == "run"
    assert arguments[arguments.index("--from") + 1] == f"update-gha[action]=={version}"
    assert arguments[arguments.index("--python") + 1] == "3.14"
    assert (
        arguments[arguments.index("--default-index") + 1] == "https://pypi.org/simple"
    )
    assert "update-gha" in arguments
    assert arguments[arguments.index("--commit-message") + 1] == message
    expected = (
        ["--no-pull-request", "--diff", "--fail-on-update"]
        if skip in {"true", "True", "TRUE", "1"}
        else ["--pull-request"]
    )
    assert arguments[-len(expected) :] == expected
    assert not (tmp_path / "injected").exists()


@pytest.mark.skipif(
    os.name == "nt", reason="Composite action requires bash on a Unix runner"
)
@pytest.mark.skipif(not has_action_extra(), reason="Requires [action]")
@pytest.mark.parametrize("custom_inputs", [False, True])
def test_composite_inputs_reach_cli_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, custom_inputs: bool
) -> None:
    seen: list[Configuration] = []

    def capture(config: Configuration, *, reporter: Reporter) -> UpdateReport:
        seen.append(config)
        return UpdateReport(files=())

    monkeypatch.setattr("update_gha.cli.main.run_update", capture)
    monkeypatch.setattr(
        "update_gha.action.run.prepare", lambda *_args: pull_request_context(tmp_path)
    )
    monkeypatch.setenv("GHA_UPDATE_TOKEN", "ambient-token")
    values = (
        {
            "committer_username": "Update Bot",
            "committer_email": "updates@example.com",
            "commit_message": "Update dependencies",
            "pull_request_title": "Action updates",
            "pull_request_branch": "automation/actions",
            "ignore": "ignore/one,ignore/two",
            "update_version_with": "release-commit-sha",
            "release_types": "minor,patch",
            "pull_request_user_reviewers": "alice,bob",
            "pull_request_team_reviewers": "core",
            "pull_request_labels": "dependencies,automation",
            "extra_workflow_locations": "extra.yml,ci/",
        }
        if custom_inputs
        else {}
    )
    arguments, env = _invoke_composite(tmp_path, token="test-token", **values)
    env["GITHUB_REPOSITORY"] = "owner/repo"
    result = CliRunner().invoke(
        app, arguments[arguments.index("update-gha") + 1 :], env=env
    )
    assert result.exit_code == 0, result.output
    expected = Configuration(
        token=SecretStr("test-token"), repository="owner/repo", create_pull_request=True
    )
    if custom_inputs:
        expected = Configuration(
            token=SecretStr("test-token"),
            repository="owner/repo",
            create_pull_request=True,
            committer_username="Update Bot",
            committer_email="updates@example.com",
            commit_message="Update dependencies",
            pull_request_title="Action updates",
            pull_request_branch="automation/actions",
            ignore_actions=frozenset({"ignore/one", "ignore/two"}),
            update_version_with=UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
            release_types=frozenset({ReleaseType.MINOR, ReleaseType.PATCH}),
            user_reviewers=("alice", "bob"),
            team_reviewers=("core",),
            labels=("dependencies", "automation"),
            extra_workflow_locations=frozenset({"extra.yml", "ci/"}),
        )
    assert len(seen) == 1
    assert seen[0].model_dump() == expected.model_dump()


def test_release_metadata_is_consistent() -> None:
    version = project_version()
    assert validate_release(f"v{version}") == version


@pytest.mark.parametrize("version", ["1.0.2", "1.0.2a1", "1.0.2b1", "1.0.2rc1"])
def test_release_accepts_existing_stable_and_prerelease_formats(
    version: str, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    (tmp_path / "action.yaml").write_text(f"update-gha[action]=={version}\n")
    assert validate_release(f"v{version}", tmp_path) == version


@pytest.mark.parametrize(
    ("tag", "pin"),
    [
        ("1.0.2", "1.0.2"),
        ("v1.2.0", "1.0.2"),
        ("v1.0.2\n", "1.0.2"),
        ("v1.0.2", "1.0.1"),
        ("v1.0.2", "1.0.2\nupdate-gha[action]==1.0.2"),
    ],
)
def test_release_rejects_mismatched_versions(
    tag: str, pin: str, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.2"\n')
    (tmp_path / "action.yaml").write_text(f"update-gha[action]=={pin}\n")
    with pytest.raises(ValueError):
        validate_release(tag, tmp_path)
