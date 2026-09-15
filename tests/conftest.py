"""Shared test doubles."""

from __future__ import annotations

import json
import logging
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest

from update_gha.github import HttpResponse
from update_gha.log import CliReporter


@pytest.fixture(autouse=True)
def _never_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: str | Sequence[object] | Mapping[str, object] = "",
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = payload if isinstance(payload, str) else json.dumps(payload)
        self._headers = {key.lower(): value for key, value in (headers or {}).items()}

    def header(self, name: str) -> str | None:
        return self._headers.get(name.lower())


class FakeSession:
    """Return scripted responses, optionally a queue per URL."""

    def __init__(
        self, mapping: Mapping[str, FakeResponse | list[FakeResponse]]
    ) -> None:
        self._queues: dict[str, list[FakeResponse]] = {
            url: [item] if isinstance(item, FakeResponse) else list(item)
            for url, item in mapping.items()
        }

    def get(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        return self._queues[url].pop(0)


def silent_reporter() -> CliReporter:
    logger = logging.getLogger("tests")
    logger.addHandler(logging.NullHandler())
    return CliReporter(logger)


class RecordingReporter:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.notices: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.summaries: list[str] = []

    def info(self, message: str) -> None:
        self.infos.append(message)

    def notice(self, message: str) -> None:
        self.notices.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def add_summary(self, markdown: str) -> None:
        self.summaries.append(markdown)

    @contextmanager
    def group(self, title: str) -> Generator[None]:
        self.infos.append(title)
        yield


def write_workflow(tmp_path: Path, name: str, content: str) -> Path:
    """Create a workflow file under ``.github/workflows``."""
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    path = workflow_dir / name
    path.write_text(content, encoding="utf-8")
    return path
