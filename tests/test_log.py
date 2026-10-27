"""Logging adapter tests."""

from __future__ import annotations

import io
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import github_action_utils as gha
import pytest
from pydantic import SecretStr

from update_gha.log import (
    CliReporter,
    GitHubActionsHandler,
    GitHubActionsReporter,
    Verbosity,
    configure_logging,
    get_reporter,
    mask_secret,
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
    ("level", "command", "expected"),
    [
        (logging.ERROR, "error", "::error ::boom\n"),
        (logging.WARNING, "warning", "::warning ::boom\n"),
        (logging.INFO, "notice", "::notice ::boom\n"),
        (logging.DEBUG, "echo", "boom\n"),
    ],
)
def test_github_handler_uses_utils_commands(
    level: int, command: str, expected: str
) -> None:
    stream = io.StringIO()
    handler = GitHubActionsHandler(stream=stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    with patch.object(gha, command, wraps=getattr(gha, command)) as emit:
        handler.emit(_record(level, "boom"))
    emit.assert_called_once_with("boom")
    assert stream.getvalue() == expected


@pytest.mark.parametrize("level", [logging.WARNING, logging.DEBUG])
def test_github_handler_escapes_workflow_commands(level: int) -> None:
    stream = io.StringIO()
    handler = GitHubActionsHandler(stream=stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.emit(_record(level, "100%\r\nnext"))
    expected = (
        "::warning ::100%25%0D%0Anext\n"
        if level == logging.WARNING
        else "100%\r\nnext\n"
    )
    assert stream.getvalue() == expected


@pytest.mark.parametrize("use_subprocess", [False, True])
def test_github_handler_does_not_raise_on_stream_error(
    monkeypatch: pytest.MonkeyPatch, use_subprocess: bool
) -> None:
    class Broken:
        def write(self, _data: str) -> None:
            raise OSError("no")

        def flush(self) -> None:
            return None

    stdout = sys.stdout
    monkeypatch.setattr(gha, "COMMANDS_USE_SUBPROCESS", use_subprocess)
    handler = GitHubActionsHandler(stream=io.StringIO())
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._stream = Broken()
    errors: list[logging.LogRecord] = []
    monkeypatch.setattr(handler, "handleError", errors.append)
    record = _record(logging.INFO, "m")
    handler.emit(record)
    assert errors == [record]
    assert sys.stdout is stdout
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
    with (
        patch.object(gha, "start_group", wraps=gha.start_group) as start,
        patch.object(gha, "end_group", wraps=gha.end_group) as end,
        patch.object(gha, "echo", wraps=gha.echo) as echo,
        patch.object(gha, "append_job_summary", wraps=gha.append_job_summary) as append,
    ):
        with reporter.group("Work"):
            reporter.info("inside")
        reporter.add_summary("### Hello")
    start.assert_called_once_with("Work")
    end.assert_called_once_with()
    echo.assert_called_once_with("inside")
    append.assert_called_once_with("### Hello")
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


def test_workflow_commands_escape_once_and_close_group_on_error() -> None:
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


@pytest.mark.parametrize("use_subprocess", [False, True])
def test_workflow_logging_restores_global_output(
    monkeypatch: pytest.MonkeyPatch, use_subprocess: bool
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(gha, "COMMANDS_USE_SUBPROCESS", use_subprocess)

    class ObservingStream(io.StringIO):
        def write(self, text: str) -> int:
            assert sys.stdout is self
            assert gha.COMMANDS_USE_SUBPROCESS is False
            return super().write(text)

    stream = ObservingStream()
    logger = configure_logging(stream=stream)
    reporter = GitHubActionsReporter(logger, stream=stream)
    with patch("subprocess.run") as command, reporter.group("Updates"):
        assert sys.stdout is stdout
        reporter.warning("100%\nnext")
        assert sys.stdout is stdout
        reporter.info("Done")
        assert sys.stdout is stdout
        print("Unrelated output")
    expected = "::group ::Updates\n::warning ::100%25%0Anext\nDone\n::endgroup::\n"
    command.assert_not_called()
    assert stream.getvalue() == expected
    assert sys.stdout is stdout
    assert gha.COMMANDS_USE_SUBPROCESS is use_subprocess
    assert stdout.getvalue() == "Unrelated output\n"


def test_workflow_logging_writes_utf8_to_encoded_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    buffer = io.BytesIO()
    with io.TextIOWrapper(buffer, encoding="ascii") as stream:
        handler = GitHubActionsHandler(stream=stream)
        handler.emit(_record(logging.WARNING, "café"))
        assert buffer.getvalue() == "::warning ::café\n".encode()


@pytest.mark.parametrize(
    "message",
    [
        "::add-mask::hidden",
        " \t::stop-commands::hidden",
        "ordinary output\n::error::injected",
        "ordinary output\r::error::injected",
        "ordinary output ##[add-mask]hidden",
        "ordinary output\n##[error]injected",
    ],
)
def test_plain_workflow_output_cannot_inject_commands(
    message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    stream = io.StringIO()
    logger = configure_logging(Verbosity.VERBOSE, stream=stream)
    get_reporter(logger, stream=stream).info(message)
    emitted = stream.getvalue()
    assert emitted.endswith("\n")
    assert "::" not in emitted
    assert "##[" not in emitted


def test_verbose_output_cannot_inject_commands() -> None:
    stream = io.StringIO()
    handler = GitHubActionsHandler(stream=stream)
    handler.emit(_record(logging.DEBUG, "100%\r\n::error::text\n##[error]text"))
    assert stream.getvalue() == ("100%\r\n%3A%3Aerror%3A%3Atext\n%23%23[error]text\n")


def test_progress_preserves_multiline_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    stream = io.StringIO()
    logger = configure_logging(stream=stream)
    message = "Updated café\n100% complete\n"
    get_reporter(logger, stream=stream).info(message)
    assert stream.getvalue() == message + "\n"


@pytest.mark.parametrize("github_actions", [False, True])
@pytest.mark.parametrize("value", [None, "", "first%\r\n::error::injected"])
def test_runner_masks_use_utils_and_keep_stdout_clean(
    github_actions: bool,
    value: str | None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if github_actions:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
    secret = SecretStr(value) if value is not None else None
    with patch.object(gha, "add_mask", wraps=gha.add_mask) as add_mask:
        mask_secret(secret)
    captured = capsys.readouterr()
    assert captured.out == ""
    if github_actions and value:
        add_mask.assert_called_once_with(value)
        assert captured.err == "::add-mask ::first%25%0D%0A::error::injected\n"
    else:
        add_mask.assert_not_called()
        assert captured.err == ""
