"""Git operations for committing and pushing workflow updates."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, Repo

from update_gha.config import Configuration
from update_gha.log import Reporter


def open_repo(reporter: Reporter) -> Repo:
    try:
        return Repo(search_parent_directories=True)
    except InvalidGitRepositoryError as exc:
        reporter.error("Not a git repository.")
        raise SystemExit(1) from exc


def resolve_base_branch(config: Configuration, repo: Repo) -> str:
    """Prefer GitHub branch refs; otherwise the current local branch."""
    if (
        config.github_base_ref
        or config.github_ref.startswith("refs/heads/")
        or (
            not config.github_ref
            and config.github_ref_name
            and not config.github_ref_name.endswith("/merge")
        )
    ):
        return config.base_branch
    try:
        if repo.head.is_valid() and not repo.head.is_detached:
            return repo.active_branch.name
    except (TypeError, ValueError):
        pass
    return config.base_branch


def validate_branches(
    repo: Repo, reporter: Reporter, *, base_branch: str, new_branch: str
) -> None:
    """Validate both refs without changing the working tree."""
    run_git(repo, reporter, "check-ref-format", "--branch", new_branch)
    run_git(repo, reporter, "rev-parse", "--verify", f"{base_branch}^{{commit}}")


def create_branch(
    repo: Repo,
    reporter: Reporter,
    *,
    base_branch: str,
    new_branch: str,
    reset: bool,
) -> str | None:
    reporter.info(f"Create New Branch ({base_branch} -> {new_branch})")
    run_git(repo, reporter, "checkout", base_branch)
    if reset:
        lease_sha = fetch_remote_branch(repo, reporter, new_branch)
        run_git(repo, reporter, "checkout", "-B", new_branch)
        return lease_sha
    run_git(repo, reporter, "checkout", "-b", new_branch)
    return None


def fetch_remote_branch(repo: Repo, reporter: Reporter, branch: str) -> str | None:
    try:
        stdout = repo.git.execute(
            [
                "git",
                "fetch",
                "origin",
                f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
            ]
        )
    except GitCommandError as exc:
        message = (_as_text(exc.stderr) or str(exc)).rstrip()
        if "couldn't find remote ref" in message.lower():
            reporter.info(f"Remote branch origin/{branch} does not exist yet.")
            run_git(
                repo,
                reporter,
                "update-ref",
                "-d",
                f"refs/remotes/origin/{branch}",
            )
            return None
        reporter.error(message)
        status = exc.status
        raise SystemExit(status if isinstance(status, int) else 1) from exc
    if text := _as_text(stdout):
        reporter.info(text.rstrip())
    return run_git(
        repo,
        reporter,
        "rev-parse",
        "--verify",
        f"refs/remotes/origin/{branch}^{{commit}}",
    )


def commit_and_push(
    repo: Repo,
    config: Configuration,
    reporter: Reporter,
    *,
    branch: str,
    force_push: bool,
    paths: Sequence[Path],
    lease_sha: str | None = None,
) -> None:
    relative_paths = _repo_relative_paths(repo, paths, reporter)
    if not relative_paths:
        reporter.error("No workflow files were provided for the update commit.")
        raise SystemExit(1)
    run_git(repo, reporter, "add", "--", *relative_paths)
    reporter.info(f"Setting Git Commit User to '{config.committer_username}'.")
    reporter.info(f"Setting Git Commit email to '{config.committer_email}'.")
    with repo.git.custom_environment(
        GIT_COMMITTER_NAME=config.committer_username,
        GIT_COMMITTER_EMAIL=config.committer_email,
    ):
        run_git(
            repo,
            reporter,
            "commit",
            f"--author={config.author}",
            "-m",
            config.commit_message,
        )
    push = ["push", "-u"]
    if force_push:
        expected = lease_sha if lease_sha is not None else ""
        push.append(f"--force-with-lease=refs/heads/{branch}:{expected}")
    push.extend(["origin", branch])
    run_git(repo, reporter, *push)


def _repo_relative_paths(
    repo: Repo, paths: Sequence[Path], reporter: Reporter
) -> tuple[str, ...]:
    if repo.working_tree_dir is None:
        reporter.error("The git repository has no working tree.")
        raise SystemExit(1)
    root = Path(repo.working_tree_dir).resolve()
    relative: list[str] = []
    for path in paths:
        try:
            relative.append(path.resolve().relative_to(root).as_posix())
        except ValueError as exc:
            reporter.error(f"Cannot commit workflow outside the repository: {path}")
            raise SystemExit(1) from exc
    return tuple(relative)


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def run_git(repo: Repo, reporter: Reporter, *args: str) -> str:
    try:
        stdout = repo.git.execute(["git", *args])
    except GitCommandError as exc:
        reporter.error((_as_text(exc.stderr) or str(exc)).rstrip())
        status = exc.status
        raise SystemExit(status if isinstance(status, int) else 1) from exc
    text = _as_text(stdout).rstrip()
    if text:
        reporter.info(text)
    return text
