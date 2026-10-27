"""CLI and GitHub Actions log reporters."""

import logging
import sys
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager, redirect_stdout
from enum import IntEnum
from typing import Protocol, TextIO, override

import github_action_utils as gha
import typer
from pydantic import SecretStr

LOGGER_NAME = "update_gha"


class Verbosity(IntEnum):
    """CLI verbosity: quiet < default < verbose."""

    QUIET = 0
    DEFAULT = 1
    VERBOSE = 2


class Reporter(Protocol):
    """Progress and summary output used by the updater."""

    def info(self, message: str) -> None:
        """Report progress at the normal verbosity level."""
        ...

    def notice(self, message: str) -> None:
        """Report a user-facing informational notice."""
        ...

    def warning(self, message: str) -> None:
        """Report a recoverable problem."""
        ...

    def error(self, message: str) -> None:
        """Report a failure."""
        ...

    def add_summary(self, markdown: str) -> None:
        """Append Markdown to the job summary, or log it locally at debug level."""
        ...

    def group(self, title: str) -> AbstractContextManager[None]:
        """Group related progress messages and close the group on failure."""
        ...


def running_on_github_actions() -> bool:
    """Return whether GitHub Actions reporting is enabled."""
    return gha.is_github_action()


def echo_report(message: str, *, json_output: bool = False, nl: bool = True) -> None:
    """Print report output without triggering runner commands."""
    if running_on_github_actions():
        # JSON escapes preserve decoded values while hiding legacy command markers.
        message = (
            message.replace("##[", r"\u0023\u0023[")
            if json_output
            else _escape_workflow_text(message)
        )
    typer.echo(message, nl=nl)


def configure_logging(
    verbosity: Verbosity = Verbosity.DEFAULT, *, stream: TextIO | None = None
) -> logging.Logger:
    """Install the process-wide handler and return the package logger."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.propagate = False

    levels = {
        Verbosity.QUIET: logging.WARNING,
        Verbosity.VERBOSE: logging.DEBUG,
        Verbosity.DEFAULT: logging.INFO,
    }
    logger.setLevel(levels[verbosity])

    if running_on_github_actions():
        handler: logging.Handler = GitHubActionsHandler(stream=stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
    else:
        handler = logging.StreamHandler(
            stream=stream if stream is not None else sys.stderr
        )
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    handler.setLevel(logger.level)
    logger.addHandler(handler)
    return logger


def get_reporter(
    logger: logging.Logger | None = None, *, stream: TextIO | None = None
) -> Reporter:
    """Return a reporter for the current runtime and selected output stream."""
    resolved = logger if logger is not None else logging.getLogger(LOGGER_NAME)
    if running_on_github_actions():
        return GitHubActionsReporter(resolved, stream=stream)
    return CliReporter(resolved)


class CliReporter:
    """Plain ``LEVEL: message`` reporter for local CLI use."""

    def __init__(self, logger: logging.Logger) -> None:
        """Bind CLI progress and summary reporting to the supplied logger."""
        self._logger = logger

    def info(self, message: str) -> None:
        """Report progress at the normal verbosity level."""
        self._logger.info(message)

    def notice(self, message: str) -> None:
        """Report a user-facing informational notice."""
        self._logger.info(message)

    def warning(self, message: str) -> None:
        """Report a recoverable problem."""
        self._logger.warning(message)

    def error(self, message: str) -> None:
        """Report a failure."""
        self._logger.error(message)

    def add_summary(self, markdown: str) -> None:
        """Log a Markdown summary at debug level."""
        self._logger.debug("summary:\n%s", markdown)

    @contextmanager
    def group(self, title: str) -> Generator[None]:
        """Log the title before related progress messages."""
        self._logger.info("%s", title)
        yield


def _escape_workflow_text(message: str) -> str:
    """Prevent plain text from triggering modern or legacy runner commands."""
    # ANSI stripping must not join separated command markers.
    return (
        message.replace("\x1b", "%1B").replace("::", "%3A%3A").replace("##[", "%23%23[")
    )


@contextmanager
def _workflow_output(stream: TextIO) -> Generator[None]:
    """Route utility output to a stream and restore the global output settings."""
    # The library writes to stdout. Keep redirection local to each emission and
    # prevent subprocesses from bypassing the chosen stream (JSON uses stderr).
    use_subprocess = gha.COMMANDS_USE_SUBPROCESS
    gha.COMMANDS_USE_SUBPROCESS = False
    try:
        with redirect_stdout(stream):
            yield
    finally:
        gha.COMMANDS_USE_SUBPROCESS = use_subprocess


def mask_secret(secret: SecretStr | None) -> None:
    """Register a credential with the runner while keeping JSON stdout clean."""
    if secret and running_on_github_actions():
        with _workflow_output(sys.stderr):
            gha.add_mask(secret.get_secret_value())


class GitHubActionsHandler(logging.Handler):
    """Send logging records through github-action-utils workflow commands."""

    def __init__(self, stream: TextIO | None = None) -> None:
        """Send workflow commands to the supplied stream or stdout by default."""
        super().__init__()
        self._stream = stream if stream is not None else sys.stdout

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Emit a record through the matching utility command, handling errors."""
        try:
            message = self.format(record)
            with _workflow_output(self._stream):
                match record.levelno:
                    case level if level >= logging.ERROR:
                        gha.error(message)
                    case level if level >= logging.WARNING:
                        gha.warning(message)
                    case level if level >= logging.INFO:
                        gha.notice(message)
                    case _:
                        # --verbose must work without the runner's debug setting.
                        gha.echo(_escape_workflow_text(message))
        except Exception:
            self.handleError(record)


class GitHubActionsReporter:
    """Reporter that uses workflow commands, log groups, and the job summary."""

    def __init__(self, logger: logging.Logger, stream: TextIO | None = None) -> None:
        """Bind workflow reporting to a logger and an optional output stream."""
        self._logger = logger
        self._stream = stream if stream is not None else sys.stdout

    def info(self, message: str) -> None:
        """Report progress at the normal verbosity level."""
        if not self._logger.isEnabledFor(logging.INFO):
            return
        with _workflow_output(self._stream):
            gha.echo(_escape_workflow_text(message))

    def notice(self, message: str) -> None:
        """Report a user-facing informational notice."""
        self._logger.info(message)

    def warning(self, message: str) -> None:
        """Report a recoverable problem."""
        self._logger.warning(message)

    def error(self, message: str) -> None:
        """Report a failure."""
        self._logger.error(message)

    def add_summary(self, markdown: str) -> None:
        """Append raw Markdown when GITHUB_STEP_SUMMARY is configured."""
        if not gha.vars.github.step_summary:
            return
        gha.append_job_summary(markdown.removesuffix("\n"))

    @contextmanager
    def group(self, title: str) -> Generator[None]:
        """Group related progress messages and close the group on failure."""
        enabled = self._logger.isEnabledFor(logging.INFO)
        if enabled:
            with _workflow_output(self._stream):
                gha.start_group(title)
        try:
            yield
        finally:
            if enabled:
                with _workflow_output(self._stream):
                    gha.end_group()
