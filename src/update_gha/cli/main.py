"""Typer command for ``update-gha``."""

from __future__ import annotations

import sys
from typing import Annotated

import typer
from pydantic import ValidationError
from pydantic_settings import SettingsError

from update_gha._version import __version__
from update_gha.action import EXTRA_HINT, has_action_extra
from update_gha.cli.options import (
    CheckOption,
    CommitMessageOption,
    CommitterEmailOption,
    CommitterUsernameOption,
    DiffOption,
    DryRunOption,
    ExtraLocationsOption,
    FailOnUpdateOption,
    FormatOption,
    IgnoreOption,
    LabelsOption,
    PathsArgument,
    PullRequestBranchOption,
    PullRequestOption,
    PullRequestTitleOption,
    QuietOption,
    ReleaseTypesOption,
    RepositoryOption,
    TeamReviewersOption,
    TokenOption,
    UpdateWithOption,
    UserReviewersOption,
    VerboseOption,
)
from update_gha.config import configuration_from_cli, split_csv
from update_gha.log import (
    Verbosity,
    configure_logging,
    get_reporter,
)
from update_gha.models import OutputFormat
from update_gha.scan import render_diff, run_update


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(0)


app = typer.Typer(
    name="update-gha",
    help=(
        "Bump outdated GitHub Action pins to the latest release or commit. "
        "Scans .github/workflows by default. A GitHub token is optional for "
        "public actions and required for --pull-request or private repos."
    ),
    add_completion=False,
    no_args_is_help=False,
)


@app.command()
def main(
    paths: PathsArgument = None,
    token: TokenOption = None,
    ignore: IgnoreOption = None,
    update_version_with: UpdateWithOption = None,
    release_types: ReleaseTypesOption = None,
    extra_workflow_locations: ExtraLocationsOption = None,
    check: CheckOption = False,
    dry_run: DryRunOption = False,
    show_diff: DiffOption = False,
    fail_on_update: FailOnUpdateOption = False,
    output_format: FormatOption = None,
    verbose: VerboseOption = False,
    quiet: QuietOption = False,
    create_pull_request: PullRequestOption = None,
    repository: RepositoryOption = None,
    committer_username: CommitterUsernameOption = None,
    committer_email: CommitterEmailOption = None,
    commit_message: CommitMessageOption = None,
    pull_request_title: PullRequestTitleOption = None,
    pull_request_branch: PullRequestBranchOption = None,
    user_reviewers: UserReviewersOption = None,
    team_reviewers: TeamReviewersOption = None,
    labels: LabelsOption = None,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print the package version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Bump outdated GitHub Action pins to the latest release or commit.

    Scans .github/workflows by default. GitHub API calls are unauthenticated
    unless --token is set. A token is required for --pull-request and for
    private action repositories.
    """
    if verbose and quiet:
        raise typer.BadParameter("Use either --verbose or --quiet, not both.")

    match (verbose, quiet):
        case (True, False):
            verbosity = Verbosity.VERBOSE
        case (False, True):
            verbosity = Verbosity.QUIET
        case _:
            verbosity = Verbosity.DEFAULT
    try:
        extra_locations = (
            split_csv(extra_workflow_locations)
            if extra_workflow_locations is not None
            else None
        )
        config = configuration_from_cli(
            token=token,
            repository=repository,
            ignore=ignore,
            update_version_with=update_version_with,
            release_types=release_types,
            extra_locations=extra_locations,
            paths=paths if paths is not None else [],
            check=check,
            dry_run=dry_run,
            show_diff=show_diff,
            output_format=output_format,
            create_pull_request=create_pull_request,
            committer_username=committer_username,
            committer_email=committer_email,
            commit_message=commit_message,
            pull_request_title=pull_request_title,
            pull_request_branch=pull_request_branch,
            user_reviewers=user_reviewers,
            team_reviewers=team_reviewers,
            labels=labels,
        )
    except (SettingsError, ValidationError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if fail_on_update and config.create_pull_request:
        raise typer.BadParameter(
            "--fail-on-update cannot be combined with --pull-request."
        )
    if fail_on_update and not config.should_write():
        raise typer.BadParameter(
            "--fail-on-update requires file writing to be enabled."
        )

    log_stream = sys.stderr if config.output_format is OutputFormat.JSON else None
    logger = configure_logging(verbosity, stream=log_stream)
    reporter = get_reporter(logger, stream=log_stream)

    pull_request_context = None
    if config.create_pull_request and config.should_write():
        if not has_action_extra():
            reporter.error(EXTRA_HINT)
            raise typer.Exit(2)
        if not config.token or not config.repository:
            reporter.error(
                "A GitHub token and repository are required for --pull-request."
            )
            raise typer.Exit(1)
        from update_gha.action.run import prepare

        pull_request_context = prepare(config, reporter)
        if pull_request_context is None:
            raise typer.Exit(1)

    try:
        report = run_update(config, reporter=reporter)
    except OSError as exc:
        reporter.error(str(exc))
        raise typer.Exit(1) from exc

    if config.output_format is OutputFormat.JSON:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(report.text_summary())
        if config.show_diff:
            for file_update in report.files:
                if file_update.changed:
                    typer.echo(render_diff(file_update), nl=False)

    if config.check and report.has_updates:
        raise typer.Exit(1)
    if fail_on_update and report.wrote:
        reporter.error("Updates were applied; failing as requested.")
        raise typer.Exit(1)

    if config.create_pull_request:
        if not config.should_write():
            reporter.warning("Skipping pull request because files were not written.")
            raise typer.Exit(0)
        if not report.has_updates:
            raise typer.Exit(0)
        if not report.wrote:
            reporter.warning(
                "Skipping pull request because no updated files could be written."
            )
            raise typer.Exit(0)
        from update_gha.action.run import run

        try:
            result = run(
                config,
                reporter,
                body=report.pull_request_body(),
                paths=tuple(item.path for item in report.files if item.changed),
                context=pull_request_context,
            )
        except (OSError, ValidationError, ValueError) as exc:
            reporter.error(str(exc))
            raise typer.Exit(1) from exc
        raise typer.Exit(result)

    raise typer.Exit(0)
