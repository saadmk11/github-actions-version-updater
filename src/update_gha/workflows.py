"""Locate workflow YAML files on disk."""

from collections.abc import Iterable
from pathlib import Path

from update_gha.log import Reporter

DEFAULT_WORKFLOW_DIR = Path(".github/workflows")
WORKFLOW_SUFFIXES = frozenset({".yml", ".yaml"})


def discover_workflow_paths(
    *,
    extra_files: Iterable[Path],
    reporter: Reporter,
    workspace: Path | None = None,
) -> tuple[Path, ...]:
    """Return unique workflow paths in a stable order."""
    root = workspace if workspace is not None else Path.cwd()
    found: set[Path] = set()

    default_dir = root / DEFAULT_WORKFLOW_DIR
    try:
        if default_dir.is_dir():
            found.update(
                path.resolve()
                for path in default_dir.iterdir()
                if path.is_file() and path.suffix in WORKFLOW_SUFFIXES
            )
    except OSError as exc:
        reporter.warning(f"Could not scan '{default_dir}': {exc}")

    for extra in extra_files:
        try:
            resolved = extra if extra.is_absolute() else root / extra
            if resolved.is_file():
                found.add(resolved.resolve())
            else:
                reporter.warning(
                    f"Skipping '{extra}' as it is not a valid file or directory"
                )
        except OSError as exc:
            reporter.warning(f"Skipping '{extra}': {exc}")

    return tuple(sorted(found))


def collect_extra_files(
    locations: Iterable[str],
    reporter: Reporter,
    workspace: Path | None = None,
) -> tuple[Path, ...]:
    """Expand files or directories (recursively) to ``.yml`` / ``.yaml`` paths."""
    root = workspace if workspace is not None else Path.cwd()
    files: list[Path] = []
    for location in locations:
        try:
            resolved = Path(location)
            resolved = resolved if resolved.is_absolute() else root / resolved
            if resolved.is_dir():
                files.extend(
                    child for child in resolved.rglob("*.yml") if child.is_file()
                )
                files.extend(
                    child for child in resolved.rglob("*.yaml") if child.is_file()
                )
            elif resolved.is_file() and resolved.suffix in WORKFLOW_SUFFIXES:
                files.append(resolved)
            else:
                reporter.warning(
                    f"Skipping '{location}' as it is not a valid file or directory"
                )
        except OSError as exc:
            reporter.warning(f"Skipping '{location}': {exc}")
    return tuple(files)
