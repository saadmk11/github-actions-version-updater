"""Run the action with real Git repositories and an in-memory GitHub API."""

import json
from contextlib import ExitStack
from pathlib import Path

import github_action_utils as gha
import httpx2
import pytest
from git import Actor, Repo
from typer.testing import CliRunner

from update_gha.cli import app


@pytest.mark.parametrize("skip", [False, True])
def test_action_updates_workflows_with_real_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skip: bool
) -> None:
    with ExitStack() as repositories:
        remote = repositories.enter_context(
            Repo.init(tmp_path / "remote.git", bare=True)
        )
        workspace = tmp_path / "workspace"
        repo = repositories.enter_context(Repo.init(workspace, initial_branch="main"))
        workflow = workspace / ".github/workflows/ci.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(
            "jobs:\n  test:\n    steps:\n      - uses: owner/action@v1\n"
        )
        unrelated = workspace / "README.md"
        unrelated.write_text("Keep this file.\n")
        repo.index.add([str(workflow), str(unrelated)])
        actor = Actor("Author", "author@example.com")
        original = repo.index.commit("Initial commit", author=actor, committer=actor)
        hooks = workspace / ".git" / "hooks"
        hook = hooks / "pre-commit"
        hook.write_text('#!/bin/sh\nprintf "hook executed" > hook-ran\n')
        hook.chmod(0o755)
        repo.create_remote("origin", str(tmp_path / "remote.git"))
        repo.git.push("origin", "main")
        (workspace / "untracked.txt").write_text(
            "Keep this out of the update commit.\n"
        )
        output = tmp_path / "output"
        requests: list[httpx2.Request] = []

        def respond(request: httpx2.Request) -> httpx2.Response:
            requests.append(request)
            assert request.headers["Authorization"] == "Bearer test-token"
            match request.method, request.url.path:
                case "GET", "/repos/owner/action/releases":
                    return httpx2.Response(
                        200,
                        json=[
                            {
                                "tag_name": "v2",
                                "html_url": "https://github.com/owner/action/releases/tag/v2",
                                "published_at": "2026-10-20T00:00:00Z",
                            }
                        ],
                    )
                case "POST", "/repos/owner/repo/pulls":
                    payload = json.loads(request.content)
                    assert payload["head"] == "action-updates"
                    assert payload["base"] == "main"
                    assert payload["title"] == "Update dependencies"
                    assert "owner/action" in payload["body"]
                    return httpx2.Response(
                        201,
                        json={
                            "number": 42,
                            "html_url": "https://github.com/owner/repo/pull/42",
                        },
                    )
                case "POST", "/repos/owner/repo/pulls/42/requested_reviewers":
                    assert json.loads(request.content) == {"reviewers": ["alice"]}
                    return httpx2.Response(201, json={})
                case "POST", "/repos/owner/repo/issues/42/labels":
                    assert json.loads(request.content) == {"labels": ["dependencies"]}
                    return httpx2.Response(200, json=[])
                case _:
                    pytest.fail(
                        f"Unexpected API request: {request.method} {request.url}"
                    )

        client_factory = httpx2.Client

        def factory(
            *, timeout: httpx2.Timeout, follow_redirects: bool
        ) -> httpx2.Client:
            return client_factory(transport=httpx2.MockTransport(respond))

        with client_factory(transport=httpx2.MockTransport(respond)) as api:
            monkeypatch.setattr("update_gha.github.httpx2.Client", factory)
            monkeypatch.setattr("update_gha.action.pulls.httpx2.request", api.request)
            monkeypatch.chdir(workspace)
            result = CliRunner().invoke(
                app,
                [
                    "--no-pull-request",
                    "--diff",
                    "--fail-on-update",
                ]
                if skip
                else ["--pull-request"],
                env={
                    "GITHUB_ACTIONS": "true",
                    "GITHUB_REPOSITORY": "owner/repo",
                    "GITHUB_REF": "refs/heads/main",
                    "GITHUB_OUTPUT": str(output),
                    "GITHUB_TOKEN": "test-token",
                    "GHA_UPDATE_PULL_REQUEST_BRANCH": "action-updates",
                    "GHA_UPDATE_PULL_REQUEST_TITLE": "Update dependencies",
                    "GHA_UPDATE_PULL_REQUEST_USER_REVIEWERS": "alice",
                    "GHA_UPDATE_PULL_REQUEST_LABELS": "dependencies",
                    "GHA_UPDATE_COMMITTER_USERNAME": "Update Bot",
                    "GHA_UPDATE_COMMITTER_EMAIL": "bot@example.com",
                },
            )
        assert result.exit_code == (1 if skip else 0), result.output
        assert (workspace / "hook-ran").exists() == (not skip)
        assert "owner/action@v2" in workflow.read_text()
        assert unrelated.read_text() == "Keep this file.\n"
        if skip:
            assert repo.head.commit == original
            assert len(requests) == 1
            assert not output.exists()
        else:
            updated = remote.commit("refs/heads/action-updates")
            assert updated.parents == (original,)
            assert updated.author.name == updated.committer.name == "Update Bot"
            assert updated.author.email == "bot@example.com"
            assert updated.stats.files.keys() == {".github/workflows/ci.yml"}
            assert remote.commit("refs/heads/main") == original
            with monkeypatch.context() as environment:
                environment.setenv("GITHUB_ENV", str(output))
                assert gha.get_workflow_environment_variables() == {
                    "GHA_UPDATE_PR_NUMBER": "42",
                    "pull-request-number": "42",
                }
            assert len(requests) == 4


def test_named_branch_push_rejects_a_concurrent_remote_commit(tmp_path: Path) -> None:
    from tests.action.conftest import make_config
    from tests.conftest import RecordingReporter

    from update_gha.action.git import commit_and_push, create_branch

    with ExitStack() as repositories:
        remote = repositories.enter_context(
            Repo.init(tmp_path / "remote.git", bare=True)
        )
        repo = repositories.enter_context(
            Repo.init(tmp_path / "workspace", initial_branch="main")
        )
        workflow = Path(repo.working_dir) / "ci.yml"
        workflow.write_text("- uses: owner/action@v1\n")
        repo.index.add([str(workflow)])
        actor = Actor("Author", "author@example.com")
        original = repo.index.commit("Initial", author=actor, committer=actor)
        repo.create_remote("origin", str(remote.git_dir))
        repo.git.push("origin", "main", "main:refs/heads/updates")
        reporter = RecordingReporter()
        lease = create_branch(
            repo,
            reporter,
            base_branch="main",
            new_branch="updates",
            reset=True,
        )
        assert lease == original.hexsha

        peer = repositories.enter_context(
            Repo.clone_from(str(remote.git_dir), tmp_path / "peer", branch="updates")
        )
        (Path(peer.working_dir) / "ci.yml").write_text("# A concurrent edit\n")
        peer.index.add(["ci.yml"])
        concurrent = peer.index.commit("Concurrent edit", author=actor, committer=actor)
        peer.git.push("origin", "updates")

        workflow.write_text("- uses: owner/action@v2\n")
        with pytest.raises(SystemExit):
            commit_and_push(
                repo,
                make_config(),
                reporter,
                branch="updates",
                force_push=True,
                paths=(workflow,),
                lease_sha=lease,
            )
        assert remote.commit("refs/heads/updates") == concurrent
        assert remote.commit("refs/heads/main") == original
        assert reporter.errors
