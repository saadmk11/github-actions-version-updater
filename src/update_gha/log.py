"""CLI and GitHub Actions log reporters."""

import logging
import os
import sys
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager, redirect_stdout
from enum import IntEnum
from typing import Protocol, TextIO, override

import github_action_utils as gha

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


@contextmanager
def _workflow_stream(stream: TextIO) -> Generator[None]:
    """Keep utility commands on the selected stream, including JSON's stderr."""
    use_subprocess = gha.COMMANDS_USE_SUBPROCESS
    try:
        # Child processes inherit OS stdout and bypass redirect_stdout.
        gha.COMMANDS_USE_SUBPROCESS = False
        with redirect_stdout(stream):
            yield
    finally:
        gha.COMMANDS_USE_SUBPROCESS = use_subprocess


class GitHubActionsHandler(logging.Handler):
    """Emit ``::notice::`` / ``::warning::`` / ``::error::`` workflow commands."""

    def __init__(self, stream: TextIO | None = None) -> None:
        super().__init__()
        self._stream = stream if stream is not None else sys.stdout

    @override
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            with _workflow_stream(self._stream):
                match record.levelno:
                    case level if level >= logging.ERROR:
                        gha.error(message)
                    case level if level >= logging.WARNING:
                        gha.warning(message)
                    case level if level >= logging.INFO:
                        gha.notice(message)
                    case _:
                        # echo() prints raw text, so escape workflow-command characters.
                        gha.echo(
                            message.replace("%", "%25")
                            .replace("\r", "%0D")
                            .replace("\n", "%0A")
                        )
        except Exception:
            self.handleError(record)


class GitHubActionsReporter:
    """Reporter that uses workflow commands, log groups, and the job summary."""

    def __init__(self, logger: logging.Logger, stream: TextIO | None = None) -> None:
        self._logger = logger
        self._stream = stream if stream is not None else sys.stdout

    def info(self, message: str) -> None:
        """Report progress at the normal verbosity level."""
        if not self._logger.isEnabledFor(logging.INFO):
            return
        with _workflow_stream(self._stream):
            gha.echo(message)

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
        if not os.environ.get("GITHUB_STEP_SUMMARY"):
            return
        gha.append_job_summary(markdown.removesuffix("\n"))

    @contextmanager
    def group(self, title: str) -> Generator[None]:
        """Group related progress messages and close the group on failure."""
        enabled = self._logger.isEnabledFor(logging.INFO)
        if enabled:
            with _workflow_stream(self._stream):
                gha.start_group(title)
        try:
            yield
        finally:
            if enabled:
                with _workflow_stream(self._stream):
                    gha.end_group()
