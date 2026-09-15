"""Orchestrate commit, push, and pull-request creation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from git import Repo

from update_gha.action.git import (
    commit_and_push,
    create_branch,
    open_repo,
    resolve_base_branch,
    validate_branches,
)
from update_gha.action.pulls import add_labels, add_reviewers, create_pull_request
from update_gha.config import Configuration
from update_gha.log import Reporter


@dataclass(frozen=True)
class PullRequestContext:
    repo: Repo
    head: str
    base: str
    force_push: bool


def prepare(config: Configuration, reporter: Reporter) -> PullRequestContext | None:
    """Validate pull-request settings and git state without changing files."""
    if not config.token or not config.repository:
        reporter.error("A GitHub token and repository are required for --pull-request.")
        return None
    try:
        head, force_push = config.resolve_head()
    except ValueError as exc:
        reporter.error(str(exc))
        return None

    repo = open_repo(reporter)
    if repo.is_dirty(
        index=True, working_tree=True, untracked_files=False, submodules=False
    ):
        reporter.error(
            "Tracked files must be clean before running with --pull-request."
        )
        return None
    base = resolve_base_branch(config, repo)
    if head == base:
        reporter.error(
            f"Invalid pull_request_branch: `{head}` is the repository base branch."
        )
        return None
    validate_branches(repo, reporter, base_branch=base, new_branch=head)
    return PullRequestContext(repo=repo, head=head, base=base, force_push=force_push)


def run(
    config: Configuration,
    reporter: Reporter,
    *,
    body: str,
    paths: Sequence[Path] = (),
    context: PullRequestContext | None = None,
) -> int:
    """Commit, push, and open the pull request. Returns a process exit code."""
    active = context if context is not None else prepare(config, reporter)
    if active is None:
        return 1
    repo = active.repo
    lease_sha = create_branch(
        repo,
        reporter,
        base_branch=active.base,
        new_branch=active.head,
        reset=active.force_push,
    )
    commit_and_push(
        repo,
        config,
        reporter,
        branch=active.head,
        force_push=active.force_push,
        paths=paths,
        lease_sha=lease_sha,
    )
    number = create_pull_request(
        config,
        reporter,
        head=active.head,
        base=active.base,
        body=body,
    )
    if number is not None:
        write_outputs(config, number)
        add_reviewers(
            config,
            reporter,
            pull_request_number=number,
            users=config.user_reviewers,
            teams=config.team_reviewers,
        )
        add_labels(
            config,
            reporter,
            pull_request_number=number,
            labels=config.labels,
        )
    return 0


def write_outputs(config: Configuration, number: int) -> None:
    if (path := config.github_output) is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"GHA_UPDATE_PR_NUMBER={number}\n")
        handle.write(f"pull-request-number={number}\n")
