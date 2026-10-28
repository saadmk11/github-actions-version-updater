"""GitHub Actions reporting through github-action-utils."""

import logging
import sys
from collections.abc import Generator
from contextlib import contextmanager, redirect_stdout
from typing import TextIO, override

import github_action_utils as gha
from pydantic import SecretStr

from update_gha.log import _escape_workflow_text


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
    if secret:
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
