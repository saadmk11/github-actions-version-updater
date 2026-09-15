"""Shared Typer option annotations for the ``update-gha`` command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from update_gha.models import OutputFormat, UpdateVersionWith

_UPDATE = "Update"
_OUTPUT = "Output"
_PULL = "Pull request"

TokenOption = Annotated[
    str | None,
    typer.Option(
        "--token",
        help=(
            "GitHub token for API calls. Required for --pull-request and for "
            "private action repos; optional for public lookups (avoids the "
            "unauthenticated rate limit). Also GITHUB_TOKEN / GHA_UPDATE_TOKEN."
        ),
        metavar="TOKEN",
        rich_help_panel=_UPDATE,
    ),
]

RepositoryOption = Annotated[
    str | None,
    typer.Option(
        "--repository",
        help=(
            "Required with --pull-request: owner/repo that receives the PR. "
            "Not used when only scanning or rewriting files. Also "
            "GITHUB_REPOSITORY."
        ),
        metavar="OWNER/REPO",
        rich_help_panel=_PULL,
    ),
]

IgnoreOption = Annotated[
    str | None,
    typer.Option(
        "--ignore",
        help=(
            "Leave these pins unchanged. Comma-separated exact uses values, "
            "including the current version (e.g. actions/checkout@v4)."
        ),
        metavar="PINS",
        rich_help_panel=_UPDATE,
    ),
]

UpdateWithOption = Annotated[
    UpdateVersionWith | None,
    typer.Option(
        "--update-version-with",
        help=(
            "What replaces each pin. release-tag (default) writes the latest "
            "stable tag; release-commit-sha writes that tag's commit and a "
            "# tag comment; default-branch-sha writes the tip of the "
            "action's default branch."
        ),
        metavar="SOURCE",
        rich_help_panel=_UPDATE,
    ),
]

ReleaseTypesOption = Annotated[
    str | None,
    typer.Option(
        "--release-types",
        help=(
            "Restrict release-tag / release-commit-sha updates to these SemVer "
            "bumps of the current pin: major, minor, patch, or all (default). "
            "No effect with default-branch-sha. A non-semver pin is skipped "
            "when this is not all."
        ),
        metavar="TYPES",
        rich_help_panel=_UPDATE,
    ),
]

ExtraLocationsOption = Annotated[
    str | None,
    typer.Option(
        "--extra-workflow-locations",
        help=(
            "Extra workflow files or directories to scan, comma-separated, "
            "in addition to .github/workflows and PATHS. Directories are "
            "searched recursively. Same role as PATHS, for env/config."
        ),
        metavar="PATHS",
        rich_help_panel=_UPDATE,
    ),
]

CheckOption = Annotated[
    bool,
    typer.Option(
        "--check",
        help=(
            "Do not write files. Exit 1 if any pin would change; exit 0 if "
            "everything is current. Incompatible with --fail-on-update."
        ),
        rich_help_panel=_OUTPUT,
    ),
]

DryRunOption = Annotated[
    bool,
    typer.Option(
        "--dry-run",
        help=(
            "Do not write files. Print the planned updates and exit 0 "
            "(unless a hard error). Unlike --check, a pending update is "
            "not a failure."
        ),
        rich_help_panel=_OUTPUT,
    ),
]

DiffOption = Annotated[
    bool,
    typer.Option(
        "--diff",
        help=(
            "Also print a unified diff of files that would change. Works "
            "with writing, --check, and --dry-run."
        ),
        rich_help_panel=_OUTPUT,
    ),
]

FailOnUpdateOption = Annotated[
    bool,
    typer.Option(
        "--fail-on-update",
        help=(
            "Write updates as usual, then exit 1 if any file was written "
            "(exit 0 if nothing changed). Incompatible with --pull-request, "
            "--check, and --dry-run."
        ),
        rich_help_panel=_OUTPUT,
    ),
]

FormatOption = Annotated[
    OutputFormat | None,
    typer.Option(
        "--format",
        help=(
            "Summary on stdout: text (default) or json. json sends progress "
            "logs to stderr so stdout stays parseable."
        ),
        rich_help_panel=_OUTPUT,
    ),
]

VerboseOption = Annotated[
    bool,
    typer.Option(
        "--verbose",
        "-v",
        help="Include debug logs. Cannot be combined with --quiet.",
        rich_help_panel=_OUTPUT,
    ),
]

QuietOption = Annotated[
    bool,
    typer.Option(
        "--quiet",
        "-q",
        help="Warnings and errors only. Cannot be combined with --verbose.",
        rich_help_panel=_OUTPUT,
    ),
]

PullRequestOption = Annotated[
    bool | None,
    typer.Option(
        "--pull-request/--no-pull-request",
        help=(
            "After writing updates, commit, push, and open a pull request. "
            "Requires update-gha\\[action], --token, --repository, and a "
            "clean tracked working tree. Skipped if nothing was written."
        ),
        rich_help_panel=_PULL,
    ),
]

CommitterUsernameOption = Annotated[
    str | None,
    typer.Option(
        "--committer-username",
        help=(
            "Git author name for the --pull-request commit. "
            "Default: github-actions\\[bot]."
        ),
        metavar="NAME",
        rich_help_panel=_PULL,
    ),
]

CommitterEmailOption = Annotated[
    str | None,
    typer.Option(
        "--committer-email",
        help=(
            "Git author email for the --pull-request commit. "
            "Default: github-actions\\[bot]@users.noreply.github.com."
        ),
        metavar="EMAIL",
        rich_help_panel=_PULL,
    ),
]

CommitMessageOption = Annotated[
    str | None,
    typer.Option(
        "--commit-message",
        help=(
            "Message for the --pull-request commit. "
            "Default: Update GitHub Action Versions."
        ),
        metavar="TEXT",
        rich_help_panel=_PULL,
    ),
]

PullRequestTitleOption = Annotated[
    str | None,
    typer.Option(
        "--pull-request-title",
        help=(
            "Title of the pull request opened by --pull-request. "
            "Default: Update GitHub Action Versions."
        ),
        metavar="TEXT",
        rich_help_panel=_PULL,
    ),
]

PullRequestBranchOption = Annotated[
    str | None,
    typer.Option(
        "--pull-request-branch",
        help=(
            "Head branch for --pull-request. Omit to create a unique "
            "gh-actions-update-<id> branch (no force). A given name is "
            "force-pushed with lease. Rejected if it is main, master, or "
            "the repository base branch."
        ),
        metavar="BRANCH",
        rich_help_panel=_PULL,
    ),
]

UserReviewersOption = Annotated[
    str | None,
    typer.Option(
        "--pull-request-reviewers",
        help=(
            "After a new PR is opened, request reviews from these GitHub "
            "usernames (comma-separated). Not applied if the PR already "
            "exists."
        ),
        metavar="USERS",
        rich_help_panel=_PULL,
    ),
]

TeamReviewersOption = Annotated[
    str | None,
    typer.Option(
        "--pull-request-teams",
        help=(
            "After a new PR is opened, request reviews from these team "
            "slugs (comma-separated). Not applied if the PR already exists."
        ),
        metavar="TEAMS",
        rich_help_panel=_PULL,
    ),
]

LabelsOption = Annotated[
    str | None,
    typer.Option(
        "--pull-request-labels",
        help=(
            "After a new PR is opened, add these labels (comma-separated). "
            "Not applied if the PR already exists."
        ),
        metavar="LABELS",
        rich_help_panel=_PULL,
    ),
]

PathsArgument = Annotated[
    list[Path] | None,
    typer.Argument(
        help=(
            "Extra workflow files or directories to scan besides "
            ".github/workflows (always scanned if present). Directories "
            "are searched recursively. Repeatable; same role as "
            "--extra-workflow-locations."
        ),
        show_default=False,
        metavar="PATHS",
    ),
]
