"""Filesystem and extra-path discovery."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.conftest import RecordingReporter, silent_reporter
from update_gha.workflows import (
    collect_extra_files,
    discover_workflow_paths,
)


def test_default_workflow_dir(tmp_path: Path) -> None:
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    ci = workflow_dir / "ci.yml"
    extra = workflow_dir / "notes.txt"
    ci.write_text("name: ci\n", encoding="utf-8")
    extra.write_text("nope\n", encoding="utf-8")
    found = discover_workflow_paths(
        extra_files=[],
        reporter=silent_reporter(),
        workspace=tmp_path,
    )
    assert found == (ci.resolve(),)


def test_extra_file_and_directory(tmp_path: Path) -> None:
    extra_dir = tmp_path / "more"
    extra_dir.mkdir()
    nested = extra_dir / "other.yaml"
    nested.write_text("name: other\n", encoding="utf-8")
    single = tmp_path / "one.yml"
    single.write_text("name: one\n", encoding="utf-8")
    extras = collect_extra_files(
        [str(extra_dir), str(single)],
        silent_reporter(),
        workspace=tmp_path,
    )
    found = discover_workflow_paths(
        extra_files=extras,
        reporter=silent_reporter(),
        workspace=tmp_path,
    )
    assert {path.name for path in found} == {"other.yaml", "one.yml"}


def test_missing_paths_are_skipped(tmp_path: Path) -> None:
    reporter = RecordingReporter()
    extras = collect_extra_files(
        ["does-not-exist.yml", str(tmp_path / "also-missing")],
        reporter,
        workspace=tmp_path,
    )
    found = discover_workflow_paths(
        extra_files=[tmp_path / "nope.yml"],
        reporter=reporter,
        workspace=tmp_path,
    )
    assert extras == ()
    assert found == ()
    assert len(reporter.warnings) == 3


def test_unreadable_workflow_dir_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    original_iterdir = Path.iterdir

    def iterdir(self: Path) -> Iterator[Path]:
        if self == workflow_dir:
            raise OSError("denied")
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    reporter = RecordingReporter()
    found = discover_workflow_paths(
        extra_files=[],
        reporter=reporter,
        workspace=tmp_path,
    )
    assert found == ()
    assert any("Could not scan" in message for message in reporter.warnings)


def test_unreadable_extra_file_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extra = tmp_path / "extra.yml"
    extra.write_text("name: extra\n", encoding="utf-8")
    original_is_file = Path.is_file

    def is_file(self: Path) -> bool:
        if self == extra:
            raise OSError("denied")
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", is_file)
    reporter = RecordingReporter()
    found = discover_workflow_paths(
        extra_files=[extra],
        reporter=reporter,
        workspace=tmp_path,
    )
    assert extra.resolve() not in found
    assert any("Skipping" in message for message in reporter.warnings)


def test_unreadable_extra_location_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extra_dir = tmp_path / "more"
    extra_dir.mkdir()
    original_is_dir = Path.is_dir

    def is_dir(self: Path) -> bool:
        if self == extra_dir:
            raise OSError("denied")
        return original_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    reporter = RecordingReporter()
    extras = collect_extra_files([str(extra_dir)], reporter, workspace=tmp_path)
    assert extras == ()
    assert any("Skipping" in message for message in reporter.warnings)
