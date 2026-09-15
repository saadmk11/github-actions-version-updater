"""Typed models for version lookup results and the CLI/action report."""

from enum import StrEnum
from pathlib import Path

from packaging.version import Version
from pydantic import BaseModel, ConfigDict, field_serializer


class UpdateVersionWith(StrEnum):
    """Where the new version token comes from."""

    LATEST_RELEASE_TAG = "release-tag"
    LATEST_RELEASE_COMMIT_SHA = "release-commit-sha"
    DEFAULT_BRANCH_COMMIT_SHA = "default-branch-sha"


class ReleaseType(StrEnum):
    """Semver component that is allowed to increase."""

    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


class OutputFormat(StrEnum):
    """CLI report format."""

    TEXT = "text"
    JSON = "json"


type ActionRef = str
type VersionToken = str


class ReleaseInfo(BaseModel):
    """A published, non-draft, non-prerelease GitHub release."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    tag_name: str
    html_url: str
    published_at: str
    tag_version: Version | None = None

    @field_serializer("tag_version")
    def _serialize_tag_version(self, value: Version | None) -> str | None:
        return None if value is None else str(value)


class CommitInfo(BaseModel):
    """A commit pointed at by a tag or branch."""

    model_config = ConfigDict(frozen=True)

    sha: str
    url: str
    date: str


class BranchInfo(BaseModel):
    """Default-branch metadata used by ``default-branch-sha`` updates."""

    model_config = ConfigDict(frozen=True)

    name: str
    url: str
    commit: CommitInfo


class ResolvedVersion(BaseModel):
    """The version token to write, plus data needed for the PR body."""

    model_config = ConfigDict(frozen=True)

    version: str
    release: ReleaseInfo | None = None
    commit: CommitInfo | None = None
    branch: BranchInfo | None = None


class ActionUpdate(BaseModel):
    """One action that will change (or has changed) in a workflow file."""

    model_config = ConfigDict(frozen=True)

    repository: str
    location: str
    old_version: str
    new_version: str
    resolved: ResolvedVersion
    update_version_with: UpdateVersionWith

    def markdown_line(self) -> str:
        """Markdown bullet for the pull-request body and job summary."""
        start = f"* **[{self.repository}](https://github.com/{self.repository})**"
        resolved = self.resolved
        match self.update_version_with:
            case UpdateVersionWith.LATEST_RELEASE_TAG if resolved.release:
                release = resolved.release
                return (
                    f"{start} published a new release "
                    f"**[{release.tag_name}]({release.html_url})** "
                    f"on {release.published_at}\n"
                )
            case UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA if (
                resolved.release and resolved.commit
            ):
                release = resolved.release
                commit = resolved.commit
                return (
                    f"{start} added a new "
                    f"**[commit]({commit.url})** to "
                    f"**[{release.tag_name}]({release.html_url})** Tag "
                    f"on {commit.date}\n"
                )
            case _ if resolved.branch:
                branch = resolved.branch
                return (
                    f"{start} added a new "
                    f"**[commit]({branch.commit.url})** to "
                    f"**[{branch.name}]({branch.url})** "
                    f"branch on {branch.commit.date}\n"
                )
            case _:
                return (
                    f"{start} updated from `{self.old_version}` "
                    f"to `{self.new_version}`\n"
                )


class FileUpdate(BaseModel):
    """One scanned workflow file and any action updates found in it."""

    model_config = ConfigDict(frozen=True)

    path: Path
    original: str
    updated: str
    actions: tuple[ActionUpdate, ...]

    @property
    def changed(self) -> bool:
        return self.original != self.updated


class UpdateReport(BaseModel):
    """Full result of a scan (and optional write)."""

    model_config = ConfigDict(frozen=True)

    files: tuple[FileUpdate, ...]
    wrote: bool = False

    @property
    def action_updates(self) -> tuple[ActionUpdate, ...]:
        """Action updates, deduplicated across files."""
        seen: dict[tuple[str, str, str], ActionUpdate] = {}
        for file_update in self.files:
            for action in file_update.actions:
                key = (action.location, action.old_version, action.new_version)
                seen.setdefault(key, action)
        return tuple(seen.values())

    @property
    def has_updates(self) -> bool:
        return any(file_update.changed for file_update in self.files)

    def pull_request_body(self) -> str:
        items = "".join(update.markdown_line() for update in self.action_updates)
        return f"### GitHub Actions Version Updates\n{items}"

    def text_summary(self) -> str:
        if not (updates := self.action_updates):
            return "Everything is up-to-date."
        width = max(len(update.location) for update in updates)
        lines = [
            f"{update.location:<{width}}  "
            f"{update.old_version}  ->  {update.new_version}"
            for update in updates
        ]
        file_count = sum(1 for file_update in self.files if file_update.changed)
        lines.extend(("", f"Updated {len(updates)} actions in {file_count} files."))
        return "\n".join(lines)


class GitHubReleasePayload(BaseModel):
    """Subset of ``GET /repos/{repo}/releases`` items we read."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    tag_name: str
    html_url: str
    published_at: str | None = None
    draft: bool = False
    prerelease: bool = False


class GitHubCommitAuthor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    date: str


class GitHubCommitDetail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    author: GitHubCommitAuthor


class GitHubCommitPayload(BaseModel):
    """Subset of ``GET /repos/{repo}/commits`` items we read."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    sha: str
    html_url: str
    commit: GitHubCommitDetail


class GitHubTagCommitPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    sha: str


class GitHubTagPayload(BaseModel):
    """Subset of ``GET /repos/{repo}/tags`` items used for SHA matching."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    commit: GitHubTagCommitPayload


class GitHubRepoPayload(BaseModel):
    """Subset of ``GET /repos/{repo}`` used for the default branch."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    default_branch: str


class GitHubMessagePayload(BaseModel):
    """Subset of a GitHub error body we are willing to log."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    message: str = ""
