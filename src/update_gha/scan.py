"""Scan workflow files, resolve new versions, and optionally write them.

Recoverable failures (one action, one file, one write) are logged and skipped
so the rest of the run can finish. Unexpected errors still propagate.
"""

from __future__ import annotations

import os
import stat
from difflib import unified_diff
from html import escape
from pathlib import Path
from tempfile import mkstemp

from update_gha.config import Configuration
from update_gha.github import (
    GitHubAPIError,
    GitHubClient,
    HttpSession,
    VersionLookup,
)
from update_gha.log import Reporter, get_reporter
from update_gha.models import (
    ActionUpdate,
    FileUpdate,
    ReleaseType,
    ResolvedVersion,
    UpdateReport,
    UpdateVersionWith,
)
from update_gha.rewrite import (
    PinRewrite,
    actions_from_spans,
    apply_version_updates,
    parse_uses_spans,
)
from update_gha.workflows import (
    collect_extra_files,
    discover_workflow_paths,
)


def run_update(
    config: Configuration,
    *,
    reporter: Reporter | None = None,
    client: VersionLookup | None = None,
    session: HttpSession | None = None,
    workspace: Path | None = None,
) -> UpdateReport:
    """Discover workflows, apply version updates, and return a report."""
    active_reporter = reporter if reporter is not None else get_reporter()
    owned_client: GitHubClient | None = None
    if client is not None:
        github: VersionLookup = client
    else:
        owned_client = GitHubClient(config.token, active_reporter, session=session)
        github = owned_client
    root = workspace if workspace is not None else Path.cwd()
    try:
        return _run_update(config, active_reporter, github, root)
    finally:
        if owned_client is not None:
            owned_client.close()


def _run_update(
    config: Configuration,
    active_reporter: Reporter,
    github: VersionLookup,
    root: Path,
) -> UpdateReport:
    extra_files = collect_extra_files(
        config.extra_workflow_locations, active_reporter, workspace=root
    )
    workflow_paths = discover_workflow_paths(
        extra_files=extra_files,
        reporter=active_reporter,
        workspace=root,
    )

    if not workflow_paths:
        active_reporter.warning(
            "No workflow files found. Skipping GitHub Actions version update."
        )
        return UpdateReport(files=())

    if config.ignore_actions:
        ignored = ", ".join(sorted(config.ignore_actions))
        active_reporter.info(f'Actions "{ignored}" will be skipped')

    resolved_cache: dict[tuple[str, str], ResolvedVersion | None] = {}
    file_updates: list[FileUpdate] = []

    for workflow_path in workflow_paths:
        with active_reporter.group(f'Checking "{workflow_path}" for updates'):
            file_update = _update_one_file(
                workflow_path,
                config=config,
                github=github,
                reporter=active_reporter,
                resolved_cache=resolved_cache,
            )
            if file_update is not None:
                file_updates.append(file_update)

    wrote_any = False
    if config.should_write():
        for file_update in file_updates:
            if not file_update.changed:
                continue
            try:
                _write_text_preserving_newlines(file_update.path, file_update.updated)
            except OSError as exc:
                active_reporter.error(f"Could not write '{file_update.path}': {exc}")
            else:
                wrote_any = True

    report = UpdateReport(files=tuple(file_updates), wrote=wrote_any)

    if report.has_updates:
        summary = report.pull_request_body()
        if config.show_diff:
            rendered = "".join(
                render_diff(file_update)
                for file_update in report.files
                if file_update.changed
            )
            summary = (
                f"{summary}\n<details><summary>Git Diff</summary>\n\n"
                f"<pre><code>{escape(rendered)}</code></pre>\n</details>\n"
            )
        active_reporter.add_summary(summary)

    return report


def _update_one_file(
    workflow_path: Path,
    *,
    config: Configuration,
    github: VersionLookup,
    reporter: Reporter,
    resolved_cache: dict[tuple[str, str], ResolvedVersion | None],
) -> FileUpdate | None:
    try:
        original = _read_text_preserving_newlines(workflow_path)
    except OSError as exc:
        reporter.error(f"Could not read '{workflow_path}': {exc}")
        return None

    spans = parse_uses_spans(original)
    if spans is None:
        reporter.error(f"Invalid YAML in '{workflow_path}'. Skipping.")
        return None
    actions = set(actions_from_spans(spans)) - config.ignore_actions

    updates: dict[str, PinRewrite] = {}
    action_updates: list[ActionUpdate] = []

    for action in sorted(actions):
        parsed = _split_action(action)
        if parsed is None:
            reporter.notice(
                f'Action "{action}" is in an unsupported format. '
                "Only owner/repo@version pins are updated "
                "(not local or container actions)."
            )
            continue
        action_location, current_version = parsed
        action_repository = "/".join(action_location.split("/")[:2])
        resolved = _resolve_cached(
            github,
            reporter,
            resolved_cache,
            action_repository=action_repository,
            current_version=current_version,
            action=action,
            update_with=config.update_version_with,
            release_types=config.release_types,
        )
        if resolved is None:
            continue

        updated_action = f"{action_location}@{resolved.version}"
        comment = _release_tag_comment(config.update_version_with, resolved)
        version_changed = action != updated_action
        if not version_changed and comment is None:
            reporter.info(f'No updates found for "{action_repository}"')
            continue

        if version_changed:
            reporter.info(f'Found new version for "{action_repository}"')
            reporter.info(f'Updating "{action}" with "{updated_action}"...')
        updates[action] = PinRewrite(
            version=resolved.version,
            comment=comment,
        )
        action_updates.append(
            ActionUpdate(
                repository=action_repository,
                location=action_location,
                old_version=current_version,
                new_version=resolved.version,
                resolved=resolved,
                update_version_with=config.update_version_with,
            )
        )

    if not updates:
        return FileUpdate(
            path=workflow_path,
            original=original,
            updated=original,
            actions=(),
        )

    updated_text = apply_version_updates(original, updates, spans=spans)
    found_after = parse_uses_spans(updated_text)
    if found_after is None:
        reporter.error(
            f'Updating version tokens produced invalid YAML in "{workflow_path}". '
            "Skipping this file."
        )
        return None

    applied = _applied_updates(
        actions_from_spans(found_after), action_updates, reporter, workflow_path
    )
    changed = updated_text != original and bool(applied)
    return FileUpdate(
        path=workflow_path,
        original=original,
        updated=updated_text if changed else original,
        actions=applied if changed else (),
    )


def _resolve_cached(
    github: VersionLookup,
    reporter: Reporter,
    resolved_cache: dict[tuple[str, str], ResolvedVersion | None],
    *,
    action_repository: str,
    current_version: str,
    action: str,
    update_with: UpdateVersionWith,
    release_types: frozenset[ReleaseType],
) -> ResolvedVersion | None:
    cache_key = (action_repository, current_version)
    if cache_key in resolved_cache:
        return resolved_cache[cache_key]

    reporter.info(f'Checking "{action_repository}" for updates...')
    try:
        resolved = github.resolve_new_version(
            action_repository,
            current_version,
            update_with,
            release_types,
        )
    except GitHubAPIError as exc:
        reporter.error(f'Could not check "{action_repository}" for updates: {exc}')
        resolved = None
    else:
        if resolved is None:
            reporter.warning(
                f"Could not find any new version for {action}. Skipping..."
            )
    resolved_cache[cache_key] = resolved
    return resolved


def _applied_updates(
    found_after: frozenset[str],
    action_updates: list[ActionUpdate],
    reporter: Reporter,
    workflow_path: Path,
) -> tuple[ActionUpdate, ...]:
    applied: list[ActionUpdate] = []
    for item in action_updates:
        new_ref = f"{item.location}@{item.new_version}"
        if new_ref in found_after:
            applied.append(item)
            continue
        reporter.error(
            f'Could not rewrite "{item.location}@{item.old_version}" in '
            f'"{workflow_path}". Skipping.'
        )
    return tuple(applied)


def _release_tag_comment(
    update_with: UpdateVersionWith, resolved: ResolvedVersion
) -> str | None:
    """Tag to write as a ``# tag`` comment on SHA pins, if any.

    Only ``release-commit-sha`` has a corresponding release tag. The
    tag is skipped when it would not be a safe single-line comment.
    """
    if update_with is not UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA:
        return None
    if resolved.release is None:
        return None
    tag = resolved.release.tag_name.strip()
    if not tag or "\n" in tag or "\r" in tag:
        return None
    return tag


def _split_action(action: str) -> tuple[str, str] | None:
    match action:
        case s if s.startswith(("./", "docker://")):
            return None
        case s if "@" not in s:
            return None
        case s:
            location, version = s.rsplit("@", 1)
            parts = location.split("/")
            if len(parts) < 2 or not parts[0] or not parts[1] or not version:
                return None
            return location, version


def _read_text_preserving_newlines(path: Path) -> str:
    """Read as text without translating ``\\r\\n`` into ``\\n``."""
    return path.read_bytes().decode("utf-8", errors="surrogateescape")


def _write_text_preserving_newlines(path: Path, text: str) -> None:
    """Write ``text`` as-is, keeping ``\\r\\n`` and the original file mode."""
    data = text.encode("utf-8", errors="surrogateescape")
    original_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    descriptor, tmp_name = mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        if original_mode is not None:
            tmp.chmod(original_mode)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def render_diff(file_update: FileUpdate) -> str:
    """Unified diff for one file."""
    original_lines = file_update.original.splitlines(keepends=True)
    updated_lines = file_update.updated.splitlines(keepends=True)
    from_file = str(file_update.path)
    return "".join(
        unified_diff(
            original_lines,
            updated_lines,
            fromfile=from_file,
            tofile=from_file,
        )
    )
