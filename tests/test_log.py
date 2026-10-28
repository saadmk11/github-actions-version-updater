"""Local CLI logging tests."""

import io

import pytest

from update_gha.log import CliReporter, Verbosity, configure_logging, get_reporter


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
