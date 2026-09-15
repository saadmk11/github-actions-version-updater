"""Git helpers and pull-request orchestration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import GitCommandError, InvalidGitRepositoryError
from tests.action.conftest import make_config
from tests.conftest import RecordingReporter, silent_reporter

from update_gha.action import git
from update_gha.action.run import prepare, run


def _mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.working_tree_dir = "/repo"
    repo.is_dirty.return_value = False
    repo.git.execute.return_value = ""
    return repo


WORKFLOW_PATHS = (Path("/repo/.github/workflows/ci.yml"),)


def test_commit_and_push_without_force() -> None:
    repo = _mock_repo()
    settings = make_config(commit_message="msg", committer_username="bot")
    git.commit_and_push(
        repo,
        settings,
        silent_reporter(),
        branch="feature",
        force_push=False,
        paths=WORKFLOW_PATHS,
    )
    commands = [call.args[0] for call in repo.git.execute.call_args_list]
    assert not any(command[1] == "fetch" for command in commands)
    assert commands[-1] == ["git", "push", "-u", "origin", "feature"]
    repo.git.custom_environment.assert_called_once_with(
        GIT_COMMITTER_NAME="bot",
        GIT_COMMITTER_EMAIL=settings.committer_email,
    )


def test_commit_and_push_force() -> None:
    repo = _mock_repo()
    settings = make_config(commit_message="msg")
    git.commit_and_push(
        repo,
        settings,
        silent_reporter(),
        branch="actions-update",
        force_push=True,
        paths=WORKFLOW_PATHS,
        lease_sha="abc1234",
    )
    commands = [call.args[0] for call in repo.git.execute.call_args_list]
    assert commands[0] == [
        "git",
        "add",
        "--",
        ".github/workflows/ci.yml",
    ]
    assert not any(command[1] == "fetch" for command in commands)
    assert commands[-1] == [
        "git",
        "push",
        "-u",
        "--force-with-lease=refs/heads/actions-update:abc1234",
        "origin",
        "actions-update",
    ]


def test_commit_rejects_empty_or_outside_paths() -> None:
    repo = _mock_repo()
    with pytest.raises(SystemExit):
        git.commit_and_push(
            repo,
            make_config(),
            silent_reporter(),
            branch="updates",
            force_push=False,
            paths=(),
        )
    with pytest.raises(SystemExit):
        git.commit_and_push(
            repo,
            make_config(),
            silent_reporter(),
            branch="updates",
            force_push=False,
            paths=(Path("/outside/ci.yml"),),
        )


def test_commit_requires_working_tree() -> None:
    repo = _mock_repo()
    repo.working_tree_dir = None
    with pytest.raises(SystemExit):
        git.commit_and_push(
            repo,
            make_config(),
            silent_reporter(),
            branch="updates",
            force_push=False,
            paths=WORKFLOW_PATHS,
        )


def _stub_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def noop(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("update_gha.action.run.open_repo", lambda _r: _mock_repo())
    monkeypatch.setattr("update_gha.action.run.create_branch", noop)
    monkeypatch.setattr("update_gha.action.run.commit_and_push", noop)


def test_run_writes_pr_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "github_output"
    settings = make_config(github_output=output)
    _stub_run(monkeypatch)
    monkeypatch.setattr(
        "update_gha.action.run.create_pull_request", lambda *_a, **_k: 9
    )
    monkeypatch.setattr("update_gha.action.run.add_reviewers", lambda *_a, **_k: None)
    monkeypatch.setattr("update_gha.action.run.add_labels", lambda *_a, **_k: None)
    assert run(settings, silent_reporter(), body="### body\n") == 0
    written = output.read_text(encoding="utf-8")
    assert "GHA_UPDATE_PR_NUMBER=9\n" in written
    assert "pull-request-number=9\n" in written


def test_run_without_github_output_still_notifies_reviewers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    _stub_run(monkeypatch)
    monkeypatch.setattr(
        "update_gha.action.run.create_pull_request", lambda *_a, **_k: 3
    )
    monkeypatch.setattr(
        "update_gha.action.run.add_reviewers",
        lambda *_a, **_k: called.append("reviewers"),
    )
    monkeypatch.setattr(
        "update_gha.action.run.add_labels",
        lambda *_a, **_k: called.append("labels"),
    )
    assert (
        run(make_config(github_output=None), silent_reporter(), body="### body\n") == 0
    )
    assert called == ["reviewers", "labels"]


def test_existing_pr_skips_reviewers(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    _stub_run(monkeypatch)
    monkeypatch.setattr(
        "update_gha.action.run.create_pull_request", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "update_gha.action.run.add_reviewers",
        lambda *_a, **_k: called.append("r"),
    )
    assert run(make_config(), silent_reporter(), body="### body\n") == 0
    assert called == []


def test_run_requires_token_and_repository() -> None:
    assert (
        run(make_config(token=None, repository=None), silent_reporter(), body="") == 1
    )


def test_run_rejects_main_branch() -> None:
    settings = make_config(pull_request_branch="main")
    assert run(settings, silent_reporter(), body="") == 1


def test_run_rejects_pr_branch_equal_to_resolved_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[bool] = []
    monkeypatch.setattr("update_gha.action.run.open_repo", lambda _r: _mock_repo())
    monkeypatch.setattr(
        "update_gha.action.run.create_branch",
        lambda *_args, **_kwargs: called.append(True),
    )
    settings = make_config(
        github_ref="refs/heads/develop", pull_request_branch="develop"
    )
    assert run(settings, silent_reporter(), body="") == 1
    assert called == []


def test_prepare_rejects_dirty_tracked_worktree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _mock_repo()
    repo.is_dirty.return_value = True
    monkeypatch.setattr("update_gha.action.run.open_repo", lambda _r: repo)
    assert prepare(make_config(), silent_reporter()) is None


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("ok\n", "ok"),
        (b"bytes-out\n", "bytes-out"),
        ("", ""),
    ],
)
def test_run_git_reports_stdout(stdout: str | bytes, expected: str) -> None:
    repo = MagicMock()
    reporter = RecordingReporter()
    repo.git.execute.return_value = stdout
    assert git.run_git(repo, reporter, "status") == expected
    if expected:
        assert reporter.infos == [expected]
    else:
        assert reporter.infos == []


def test_run_git_reports_stderr_and_exits() -> None:
    repo = MagicMock()
    reporter = RecordingReporter()
    repo.git.execute.side_effect = GitCommandError("git status", 1, stderr="fail")
    with pytest.raises(SystemExit) as exited:
        git.run_git(repo, reporter, "status")
    assert exited.value.code == 1
    assert any("fail" in message for message in reporter.errors)


def test_run_git_decodes_bytes_stderr() -> None:
    repo = MagicMock()
    repo.git.execute.side_effect = GitCommandError(
        "git status", "bad", stderr=b"fail-bytes"
    )
    with pytest.raises(SystemExit) as exited:
        git.run_git(repo, silent_reporter(), "status")
    assert exited.value.code == 1


def test_open_repo_requires_git_workdir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git,
        "Repo",
        lambda **_k: (_ for _ in ()).throw(InvalidGitRepositoryError("nope")),
    )
    with pytest.raises(SystemExit):
        git.open_repo(silent_reporter())


def test_commit_does_not_write_git_config() -> None:
    repo = _mock_repo()
    git.commit_and_push(
        repo,
        make_config(committer_username="bot", committer_email="bot@x"),
        silent_reporter(),
        branch="updates",
        force_push=False,
        paths=WORKFLOW_PATHS,
    )
    repo.config_writer.assert_not_called()


def test_open_repo_finds_workspace() -> None:
    repo = git.open_repo(silent_reporter())
    assert repo.working_tree_dir is not None


def test_create_branch_checks_out_base_then_new() -> None:
    repo = MagicMock()
    repo.git.execute.return_value = ""
    git.create_branch(
        repo,
        silent_reporter(),
        base_branch="main",
        new_branch="feature",
        reset=False,
    )
    commands = [call.args[0] for call in repo.git.execute.call_args_list]
    assert commands == [
        ["git", "checkout", "main"],
        ["git", "checkout", "-b", "feature"],
    ]


def test_create_branch_resets_named_branch_after_fetch() -> None:
    repo = MagicMock()

    def execute(args: list[str]) -> str:
        return "abc1234" if args[1] == "rev-parse" else "From origin"

    repo.git.execute.side_effect = execute
    lease_sha = git.create_branch(
        repo,
        silent_reporter(),
        base_branch="main",
        new_branch="actions-update",
        reset=True,
    )
    commands = [call.args[0] for call in repo.git.execute.call_args_list]
    assert lease_sha == "abc1234"
    assert commands == [
        ["git", "checkout", "main"],
        [
            "git",
            "fetch",
            "origin",
            "+refs/heads/actions-update:refs/remotes/origin/actions-update",
        ],
        [
            "git",
            "rev-parse",
            "--verify",
            "refs/remotes/origin/actions-update^{commit}",
        ],
        ["git", "checkout", "-B", "actions-update"],
    ]


def test_create_branch_reset_when_remote_missing() -> None:
    repo = MagicMock()

    def execute(args: list[str]) -> str:
        if args[1] == "fetch":
            raise GitCommandError(
                "git fetch", 128, stderr=b"fatal: couldn't find remote ref"
            )
        return ""

    repo.git.execute.side_effect = execute
    git.create_branch(
        repo,
        silent_reporter(),
        base_branch="main",
        new_branch="actions-update",
        reset=True,
    )
    commands = [call.args[0] for call in repo.git.execute.call_args_list]
    assert commands[0] == ["git", "checkout", "main"]
    assert commands[-2:] == [
        [
            "git",
            "update-ref",
            "-d",
            "refs/remotes/origin/actions-update",
        ],
        ["git", "checkout", "-B", "actions-update"],
    ]


def test_fetch_remote_branch_propagates_real_failure() -> None:
    repo = MagicMock()
    repo.git.execute.side_effect = GitCommandError(
        "git fetch", 128, stderr="fatal: authentication failed"
    )
    with pytest.raises(SystemExit):
        git.fetch_remote_branch(repo, silent_reporter(), "updates")


def test_fetch_remote_branch_still_rev_parses_when_fetch_is_quiet() -> None:
    repo = MagicMock()
    repo.git.execute.return_value = ""
    assert git.fetch_remote_branch(repo, silent_reporter(), "updates") == ""
    commands = [call.args[0] for call in repo.git.execute.call_args_list]
    assert commands[0][1] == "fetch"
    assert commands[1][1] == "rev-parse"


def test_resolve_base_branch_uses_github_ref() -> None:
    repo = MagicMock()
    config = make_config(github_ref="refs/heads/develop")
    assert git.resolve_base_branch(config, repo) == "develop"


def test_resolve_base_branch_uses_github_ref_name() -> None:
    repo = MagicMock()
    config = make_config(github_ref="", github_ref_name="release")
    assert git.resolve_base_branch(config, repo) == "release"


def test_resolve_base_branch_uses_pull_request_base_ref() -> None:
    repo = MagicMock()
    config = make_config(
        github_ref="refs/pull/1/merge",
        github_ref_name="1/merge",
        github_base_ref="develop",
    )
    assert git.resolve_base_branch(config, repo) == "develop"


def test_resolve_base_branch_ignores_tag_ref() -> None:
    repo = MagicMock()
    repo.head.is_valid.return_value = False
    config = make_config(github_ref="refs/tags/v1.0.0", github_ref_name="v1.0.0")
    assert git.resolve_base_branch(config, repo) == "main"


def test_resolve_base_branch_uses_local_branch() -> None:
    repo = MagicMock()
    repo.head.is_valid.return_value = True
    repo.head.is_detached = False
    repo.active_branch.name = "local-feature"
    config = make_config(github_ref="", github_ref_name="")
    assert git.resolve_base_branch(config, repo) == "local-feature"


def test_resolve_base_branch_skips_merge_ref_name() -> None:
    repo = MagicMock()
    repo.head.is_valid.return_value = True
    repo.head.is_detached = False
    repo.active_branch.name = "local-feature"
    config = make_config(github_ref="", github_ref_name="1/merge")
    assert git.resolve_base_branch(config, repo) == "local-feature"


def test_resolve_base_branch_falls_back_when_detached() -> None:
    repo = MagicMock()
    repo.head.is_valid.return_value = True
    repo.head.is_detached = True
    config = make_config(github_ref="", github_ref_name="")
    assert git.resolve_base_branch(config, repo) == "main"


def test_resolve_base_branch_falls_back_when_head_invalid() -> None:
    repo = MagicMock()
    repo.head.is_valid.return_value = False
    config = make_config(github_ref="", github_ref_name="")
    assert git.resolve_base_branch(config, repo) == "main"


@pytest.mark.parametrize("error", [ValueError("no head"), TypeError("no head")])
def test_resolve_base_branch_falls_back_on_error(error: Exception) -> None:
    repo = MagicMock()
    repo.head.is_valid.side_effect = error
    config = make_config(github_ref="", github_ref_name="")
    assert git.resolve_base_branch(config, repo) == "main"


def test_run_creates_named_branch_from_resolved_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def capture(
        _repo: object,
        _reporter: object,
        *,
        base_branch: str,
        new_branch: str,
        reset: bool,
    ) -> None:
        seen.update(base_branch=base_branch, new_branch=new_branch, reset=reset)

    monkeypatch.setattr("update_gha.action.run.open_repo", lambda _r: _mock_repo())
    monkeypatch.setattr("update_gha.action.run.create_branch", capture)
    monkeypatch.setattr("update_gha.action.run.commit_and_push", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "update_gha.action.run.create_pull_request", lambda *_a, **_k: None
    )
    settings = make_config(
        github_ref="refs/heads/develop", pull_request_branch="updates"
    )
    assert run(settings, silent_reporter(), body="x") == 0
    assert seen == {
        "base_branch": "develop",
        "new_branch": "updates",
        "reset": True,
    }


def test_prepare_validates_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = MagicMock()
    repo.is_dirty.return_value = False
    repo.head.is_valid.return_value = True
    repo.head.is_detached = False
    repo.active_branch.name = "develop"
    monkeypatch.setattr("update_gha.action.run.open_repo", lambda _r: repo)
    context = prepare(
        make_config(github_ref="", github_ref_name="", pull_request_branch="updates"),
        silent_reporter(),
    )
    assert context is not None
    commands = [call.args[0] for call in repo.git.execute.call_args_list]
    assert ["git", "check-ref-format", "--branch", "updates"] in commands
    assert ["git", "rev-parse", "--verify", "develop^{commit}"] in commands


def test_run_uses_local_branch_when_github_ref_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = MagicMock()
    repo.is_dirty.return_value = False
    repo.head.is_valid.return_value = True
    repo.head.is_detached = False
    repo.active_branch.name = "my-feature"
    seen: dict[str, str] = {}

    def capture(
        _repo: object,
        _reporter: object,
        *,
        base_branch: str,
        new_branch: str,
        reset: bool,
    ) -> None:
        seen["base"] = base_branch
        _ = (new_branch, reset)

    monkeypatch.setattr("update_gha.action.run.open_repo", lambda _r: repo)
    monkeypatch.setattr("update_gha.action.run.create_branch", capture)
    monkeypatch.setattr("update_gha.action.run.commit_and_push", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "update_gha.action.run.create_pull_request", lambda *_a, **_k: None
    )
    settings = make_config(
        github_ref="", github_ref_name="", pull_request_branch="updates"
    )
    assert run(settings, silent_reporter(), body="x") == 0
    assert seen["base"] == "my-feature"


def test_as_text_accepts_none_and_other_values() -> None:
    assert git._as_text(None) == ""
    assert git._as_text(12) == "12"
