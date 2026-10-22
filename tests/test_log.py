"""Logging adapter tests."""

from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

import github_action_utils as gha
import pytest

from update_gha.log import (
    CliReporter,
    GitHubActionsHandler,
    GitHubActionsReporter,
    Verbosity,
    configure_logging,
    get_reporter,
)


def _record(level: int, message: str) -> logging.LogRecord:
    return logging.LogRecord("update_gha", level, __file__, 1, message, (), None)


def test_cli_logging_uses_level_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    stream = io.StringIO()
    logger = configure_logging(Verbosity.DEFAULT, stream=stream)
    reporter = get_reporter(logger)
    assert isinstance(reporter, CliReporter)
    reporter.info("hello")
    reporter.notice("note")
    reporter.warning("careful")
    reporter.error("boom")
    reporter.add_summary("not-at-info")
    with reporter.group("Work"):
        pass
    output = stream.getvalue()
    assert "INFO: hello\n" in output
    assert "INFO: note\n" in output
    assert "WARNING: careful\n" in output
    assert "ERROR: boom\n" in output
    assert "INFO: Work\n" in output
    assert "not-at-info" not in output


def test_cli_summary_is_emitted_at_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    stream = io.StringIO()
    logger = configure_logging(Verbosity.VERBOSE, stream=stream)
    get_reporter(logger).add_summary("details")
    assert "DEBUG: summary:\ndetails\n" in stream.getvalue()


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (logging.ERROR, "::error ::boom\n"),
        (logging.WARNING, "::warning ::boom\n"),
        (logging.INFO, "::notice ::boom\n"),
        (logging.DEBUG, "boom\n"),
    ],
)
def test_github_handler_prefixes(level: int, expected: str) -> None:
    stream = io.StringIO()
    handler = GitHubActionsHandler(stream=stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.emit(_record(level, "boom"))
    assert stream.getvalue() == expected


@pytest.mark.parametrize("level", [logging.WARNING, logging.DEBUG])
def test_github_handler_escapes_workflow_commands(level: int) -> None:
    stream = io.StringIO()
    handler = GitHubActionsHandler(stream=stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.emit(_record(level, "100%\r\nnext"))
    prefix = "::warning ::" if level == logging.WARNING else ""
    assert stream.getvalue() == prefix + "100%25%0D%0Anext\n"


@pytest.mark.parametrize("use_subprocess", [False, True])
def test_github_handler_does_not_raise_on_stream_error(
    use_subprocess: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gha, "COMMANDS_USE_SUBPROCESS", use_subprocess)

    class Broken:
        def write(self, _data: str) -> None:
            raise OSError("no")

        def flush(self) -> None:
            return None

    handler = GitHubActionsHandler(stream=io.StringIO())
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._stream = Broken()
    handler.emit(_record(logging.INFO, "m"))
    assert gha.COMMANDS_USE_SUBPROCESS is use_subprocess


def test_github_reporter_groups_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    stream = io.StringIO()
    logger = logging.getLogger("test-gha-reporter")
    logger.setLevel(logging.INFO)
    reporter = GitHubActionsReporter(logger, stream=stream)
    with reporter.group("Work"):
        reporter.info("inside")
    reporter.add_summary("### Hello")
    assert stream.getvalue() == "::group ::Work\ninside\n::endgroup::\n"
    assert summary.read_text(encoding="utf-8") == "### Hello\n"


def test_github_reporter_quiet_suppresses_info_and_groups() -> None:
    stream = io.StringIO()
    logger = logging.getLogger("test-gha-reporter-quiet")
    logger.setLevel(logging.WARNING)
    reporter = GitHubActionsReporter(logger, stream=stream)
    with reporter.group("Work"):
        reporter.info("inside")
    assert stream.getvalue() == ""


def test_github_reporter_levels_use_the_logger() -> None:
    stream = io.StringIO()
    logger = logging.getLogger("test-gha-levels")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(stream))
    logger.handlers[0].setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
    GitHubActionsReporter(logger, stream=io.StringIO()).notice("n")
    GitHubActionsReporter(logger, stream=io.StringIO()).warning("w")
    GitHubActionsReporter(logger, stream=io.StringIO()).error("e")
    assert stream.getvalue() == "INFO:n\nWARNING:w\nERROR:e\n"


def test_configure_logging_on_github_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    stream = io.StringIO()
    logger = configure_logging(Verbosity.QUIET, stream=stream)
    reporter = get_reporter()
    assert isinstance(reporter, GitHubActionsReporter)
    assert isinstance(logger.handlers[0], GitHubActionsHandler)
    reporter.warning("careful")
    assert stream.getvalue() == "::warning ::careful\n"
    assert GitHubActionsHandler()._stream is sys.stdout
    assert GitHubActionsReporter(logger)._stream is sys.stdout


def test_add_summary_is_skipped_without_step_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reporter = GitHubActionsReporter(
        logging.getLogger("test-gha-summary"), stream=io.StringIO()
    )
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    reporter.add_summary("x")
    summary = tmp_path / "s.md"
    assert not summary.exists()
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    reporter.add_summary("line")
    assert summary.read_text(encoding="utf-8") == "line\n"


@pytest.mark.parametrize("ending", ["", "\n", "\n\n"])
def test_summary_preserves_raw_markdown_with_utils_v2(
    ending: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    markdown = "### 100% / %25 / %0D / %0A / café\r\nnext" + ending
    reporter = GitHubActionsReporter(logging.getLogger("summary-raw"))
    reporter.add_summary(markdown)
    expected = markdown if markdown.endswith("\n") else markdown + "\n"
    assert summary.read_bytes() == expected.encode("utf-8")


@pytest.mark.parametrize("use_subprocess", [False, True])
def test_utils_v2_escapes_commands_once_and_closes_group_on_error(
    use_subprocess: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gha, "COMMANDS_USE_SUBPROCESS", use_subprocess)
    stream = io.StringIO()
    logger = configure_logging(stream=stream)
    handler = GitHubActionsHandler(stream=stream)
    handler.emit(_record(logging.WARNING, "literal %0A\n::error::text"))
    assert stream.getvalue() == "::warning ::literal %250A%0A::error::text\n"
    stream.seek(0)
    stream.truncate()
    reporter = GitHubActionsReporter(logger, stream=stream)
    with pytest.raises(ValueError), reporter.group("100%\n::error::title"):
        raise ValueError("stop")
    assert stream.getvalue() == ("::group ::100%25%0A::error::title\n::endgroup::\n")
    assert gha.COMMANDS_USE_SUBPROCESS is use_subprocess
