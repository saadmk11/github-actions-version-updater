"""CLI and GitHub Actions log reporters."""

import logging
import os
import sys
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from enum import IntEnum
from pathlib import Path
from typing import Protocol, TextIO, override

LOGGER_NAME = "update_gha"


class Verbosity(IntEnum):
    """CLI verbosity: quiet < default < verbose."""

    QUIET = 0
    DEFAULT = 1
    VERBOSE = 2


class Reporter(Protocol):
    """Progress and summary output used by the updater."""

    def info(self, message: str) -> None: ...

    def notice(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...

    def add_summary(self, markdown: str) -> None: ...

    def group(self, title: str) -> AbstractContextManager[None]: ...


def running_on_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


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
    resolved = logger if logger is not None else logging.getLogger(LOGGER_NAME)
    if running_on_github_actions():
        return GitHubActionsReporter(resolved, stream=stream)
    return CliReporter(resolved)


class CliReporter:
    """Plain ``LEVEL: message`` reporter for local CLI use."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def info(self, message: str) -> None:
        self._logger.info(message)

    def notice(self, message: str) -> None:
        self._logger.info(message)

    def warning(self, message: str) -> None:
        self._logger.warning(message)

    def error(self, message: str) -> None:
        self._logger.error(message)

    def add_summary(self, markdown: str) -> None:
        self._logger.debug("summary:\n%s", markdown)

    @contextmanager
    def group(self, title: str) -> Generator[None]:
        self._logger.info("%s", title)
        yield


class GitHubActionsHandler(logging.Handler):
    """Emit ``::notice::`` / ``::warning::`` / ``::error::`` workflow commands."""

    def __init__(self, stream: TextIO | None = None) -> None:
        super().__init__()
        self._stream = stream if stream is not None else sys.stdout

    @override
    def emit(self, record: logging.LogRecord) -> None:
        try:
            escaped = _escape_workflow_message(self.format(record))
            match record.levelno:
                case level if level >= logging.ERROR:
                    command = f"::error::{escaped}"
                case level if level >= logging.WARNING:
                    command = f"::warning::{escaped}"
                case level if level >= logging.INFO:
                    command = f"::notice::{escaped}"
                case _:
                    command = escaped
            self._stream.write(f"{command}\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)


class GitHubActionsReporter:
    """Reporter that uses workflow commands, log groups, and the job summary."""

    def __init__(self, logger: logging.Logger, stream: TextIO | None = None) -> None:
        self._logger = logger
        self._stream = stream if stream is not None else sys.stdout

    def info(self, message: str) -> None:
        if not self._logger.isEnabledFor(logging.INFO):
            return
        self._stream.write(f"{message}\n")
        self._stream.flush()

    def notice(self, message: str) -> None:
        self._logger.info(message)

    def warning(self, message: str) -> None:
        self._logger.warning(message)

    def error(self, message: str) -> None:
        self._logger.error(message)

    def add_summary(self, markdown: str) -> None:
        if not (summary_path := os.environ.get("GITHUB_STEP_SUMMARY")):
            return
        text = markdown if markdown.endswith("\n") else f"{markdown}\n"
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(text)

    @contextmanager
    def group(self, title: str) -> Generator[None]:
        enabled = self._logger.isEnabledFor(logging.INFO)
        if enabled:
            self._stream.write(f"::group::{_escape_workflow_message(title)}\n")
            self._stream.flush()
        try:
            yield
        finally:
            if enabled:
                self._stream.write("::endgroup::\n")
                self._stream.flush()


def _escape_workflow_message(message: str) -> str:
    """Escape values so they survive GitHub workflow-command parsing."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
