"""GitHub REST client for release and commit lookup."""

import time
from collections.abc import Callable, Mapping
from typing import Protocol, assert_never
from urllib.parse import quote, urlsplit

import requests
from packaging.version import InvalidVersion, Version
from pydantic import TypeAdapter, ValidationError
from requests import RequestException

from update_gha.log import Reporter
from update_gha.models import (
    BranchInfo,
    CommitInfo,
    GitHubCommitPayload,
    GitHubMessagePayload,
    GitHubReleasePayload,
    GitHubRepoPayload,
    GitHubTagPayload,
    ReleaseInfo,
    ReleaseType,
    ResolvedVersion,
    UpdateVersionWith,
)

GITHUB_API_URL = "https://api.github.com"
GITHUB_HTML_URL = "https://github.com/"
HTTP_TIMEOUT_SECONDS = 30
PAGE_SIZE = 100
MAX_RETRIES = 4
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
type SleepFn = Callable[[float], None]


def parse_version(value: str) -> Version | None:
    """Parse a PEP 440 version, or return None for tags/SHAs that are not versions."""
    try:
        return Version(value)
    except InvalidVersion:
        return None


class VersionLookup(Protocol):
    """Version lookup used by the updater."""

    def resolve_new_version(
        self,
        action_repository: str,
        current_version: str,
        update_with: UpdateVersionWith,
        release_types: frozenset[ReleaseType],
    ) -> ResolvedVersion | None: ...


class HttpResponse(Protocol):
    status_code: int
    text: str

    def header(self, name: str) -> str | None: ...


class HttpSession(Protocol):
    def get(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse: ...


_RELEASE_LIST = TypeAdapter(list[GitHubReleasePayload])
_COMMIT_LIST = TypeAdapter(list[GitHubCommitPayload])
_TAG_LIST = TypeAdapter(list[GitHubTagPayload])
_REPOSITORY = TypeAdapter(GitHubRepoPayload)


class GitHubAPIError(RuntimeError):
    """GitHub request failed or returned an invalid response."""


def request_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "update-gha",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class _ResponseAdapter:
    def __init__(self, status_code: int, text: str, headers: Mapping[str, str]) -> None:
        self.status_code = status_code
        self.text = text
        self._headers = {key.lower(): value for key, value in headers.items()}

    def header(self, name: str) -> str | None:
        return self._headers.get(name.lower())


class _RequestsSession:
    """Adapt ``requests.Session`` to ``HttpSession``."""

    def __init__(self) -> None:
        self._inner = requests.Session()

    def get(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        response = self._inner.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
        raw_headers = {
            str(key).lower(): str(value) for key, value in response.headers.items()
        }
        return _ResponseAdapter(response.status_code, response.text, raw_headers)

    def close(self) -> None:
        self._inner.close()


class GitHubClient:
    """Look up release tags, commit SHAs, and default-branch tips."""

    def __init__(
        self,
        token: str | None,
        reporter: Reporter,
        session: HttpSession | None = None,
        api_url: str = GITHUB_API_URL,
        sleeper: SleepFn | None = None,
    ) -> None:
        self._token = token
        self._reporter = reporter
        self._sleeper: SleepFn = sleeper if sleeper is not None else time.sleep
        self._owned_session: _RequestsSession | None
        if session is None:
            self._owned_session = _RequestsSession()
            self._session: HttpSession = self._owned_session
        else:
            self._owned_session = None
            self._session = session
        self._api_url = api_url.rstrip("/")
        self._release_cache: dict[str, tuple[ReleaseInfo, ...]] = {}
        self._commit_cache: dict[tuple[str, str], CommitInfo] = {}
        self._release_sha_cache: dict[tuple[str, str], ReleaseInfo | None] = {}

    def close(self) -> None:
        if self._owned_session is not None:
            self._owned_session.close()
            self._owned_session = None

    def resolve_new_version(
        self,
        action_repository: str,
        current_version: str,
        update_with: UpdateVersionWith,
        release_types: frozenset[ReleaseType],
    ) -> ResolvedVersion | None:
        match update_with:
            case UpdateVersionWith.LATEST_RELEASE_TAG:
                if not (
                    release := self._latest_release(
                        action_repository, current_version, release_types
                    )
                ):
                    return None
                return ResolvedVersion(version=release.tag_name, release=release)
            case UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA:
                lookup_version = current_version
                restricted = release_types != frozenset(ReleaseType)
                if restricted and _is_full_commit_sha(current_version):
                    current_release = self._release_for_commit(
                        action_repository, current_version
                    )
                    if current_release is None:
                        self._reporter.warning(
                            f"Could not match commit `{current_version}` to a semantic "
                            f"release of `{action_repository}`; release type filtering "
                            "cannot be applied safely. Skipping."
                        )
                        return None
                    lookup_version = current_release.tag_name
                elif restricted and parse_version(current_version) is None:
                    self._reporter.warning(
                        f"Current version (`{current_version}`) of "
                        f"`{action_repository}` is not semantic; release type "
                        "filtering cannot be applied safely. Skipping."
                    )
                    return None
                if not (
                    release := self._latest_release(
                        action_repository, lookup_version, release_types
                    )
                ):
                    return None
                commit = self._commit(action_repository, release.tag_name)
                return ResolvedVersion(
                    version=commit.sha, release=release, commit=commit
                )
            case UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA:
                branch_name = self._default_branch(action_repository)
                commit = self._commit(action_repository, branch_name)
                return ResolvedVersion(
                    version=commit.sha,
                    commit=commit,
                    branch=BranchInfo(
                        name=branch_name,
                        url=(
                            f"{GITHUB_HTML_URL}{action_repository}/tree/"
                            f"{quote(branch_name, safe='/')}"
                        ),
                        commit=commit,
                    ),
                )
        assert_never(update_with)

    def _request(self, url: str) -> HttpResponse:
        try:
            return self._session.get(url, headers=request_headers(self._token))
        except RequestException as exc:
            raise GitHubAPIError(f"Could not reach GitHub: {exc}") from exc

    def _get(self, url: str) -> HttpResponse:
        delay = 1.0
        response = self._request(url)
        for attempt in range(1, MAX_RETRIES):
            if not _should_retry(response):
                return response
            wait = _retry_after_seconds(response) or delay
            self._reporter.warning(
                f"GitHub API returned HTTP {response.status_code}; "
                f"retrying in {wait:.1f}s (attempt {attempt}/{MAX_RETRIES})"
            )
            self._sleeper(wait)
            delay *= 2
            response = self._request(url)
        return response

    def _paginate(self, first_url: str) -> tuple[HttpResponse, ...]:
        pages: list[HttpResponse] = []
        url: str | None = first_url
        seen: set[str] = set()
        while url is not None and url not in seen:
            seen.add(url)
            response = self._get(url)
            pages.append(response)
            if response.status_code != 200:
                break
            url = next_page_url(response.header("link"))
            if url is not None and not _same_origin(url, self._api_url):
                raise GitHubAPIError(
                    "GitHub returned a pagination URL on an unexpected origin"
                )
        return tuple(pages)

    def _releases(self, action_repository: str) -> tuple[ReleaseInfo, ...]:
        if (cached := self._release_cache.get(action_repository)) is not None:
            return cached
        url = f"{self._api_url}/repos/{action_repository}/releases?per_page={PAGE_SIZE}"
        releases: list[ReleaseInfo] = []
        for response in self._paginate(url):
            if response.status_code != 200:
                raise GitHubAPIError(
                    f"Could not get releases for {action_repository}: "
                    f"{error_summary(response.status_code, response.text)}"
                )
            for payload in _validate_response(
                _RELEASE_LIST, response.text, context="release list"
            ):
                if payload.draft or payload.prerelease or payload.published_at is None:
                    continue
                releases.append(
                    ReleaseInfo(
                        tag_name=payload.tag_name,
                        html_url=payload.html_url,
                        published_at=payload.published_at,
                        tag_version=parse_version(payload.tag_name),
                    )
                )

        versioned = [rel for rel in releases if rel.tag_version is not None]
        unversioned = [rel for rel in releases if rel.tag_version is None]
        versioned.sort(key=lambda rel: rel.tag_version or Version("0"), reverse=True)
        ordered = tuple(versioned + unversioned)
        self._release_cache[action_repository] = ordered
        return ordered

    def _latest_release(
        self,
        action_repository: str,
        current_version: str,
        release_types: frozenset[ReleaseType],
    ) -> ReleaseInfo | None:
        if not (releases := self._releases(action_repository)):
            return None

        if (parsed_current := parse_version(current_version)) is None:
            self._reporter.warning(
                f"Current version (`{current_version}`) of `{action_repository}` "
                "does not follow Semantic Versioning specification. This can yield "
                "unexpected results, please be careful while using the updates "
                "suggested by this action."
            )
            if release_types != frozenset(ReleaseType):
                self._reporter.warning(
                    "Release type filtering requires a semantic current version. "
                    "Skipping."
                )
                return None
            return releases[0]

        matches_filter = _release_filter(release_types)
        for release in releases:
            if release.tag_version is None:
                continue
            if matches_filter(release.tag_version, parsed_current):
                return release

        if all(release.tag_version is None for release in releases):
            self._reporter.warning(
                f"GitHub releases of `{action_repository}` do not follow "
                "Semantic Versioning specification. This can yield unexpected "
                "results, please be careful while using the updates suggested "
                "by this action."
            )
            return releases[0]
        return None

    def _commit(self, action_repository: str, tag_or_branch: str) -> CommitInfo:
        cache_key = (action_repository, tag_or_branch)
        if cached := self._commit_cache.get(cache_key):
            return cached
        encoded_ref = quote(tag_or_branch, safe="")
        url = f"{self._api_url}/repos/{action_repository}/commits?sha={encoded_ref}"
        response = self._get(url)
        if response.status_code != 200:
            raise GitHubAPIError(
                f"Could not get commit data for {tag_or_branch} on "
                f"{action_repository}: "
                f"{error_summary(response.status_code, response.text)}"
            )
        if not (
            commits := _validate_response(
                _COMMIT_LIST, response.text, context="commit list"
            )
        ):
            raise GitHubAPIError(
                f"Could not get commit data for {tag_or_branch} on "
                f"{action_repository}: empty commit list"
            )
        payload = commits[0]
        commit = CommitInfo(
            sha=payload.sha,
            url=payload.html_url,
            date=payload.commit.author.date,
        )
        self._commit_cache[cache_key] = commit
        return commit

    def _release_for_commit(
        self, action_repository: str, current_sha: str
    ) -> ReleaseInfo | None:
        cache_key = (action_repository, current_sha)
        if cache_key in self._release_sha_cache:
            return self._release_sha_cache[cache_key]

        releases_by_tag = {
            release.tag_name: release
            for release in self._releases(action_repository)
            if release.tag_version is not None
        }
        url = f"{self._api_url}/repos/{action_repository}/tags?per_page={PAGE_SIZE}"
        matches: list[ReleaseInfo] = []
        for response in self._paginate(url):
            if response.status_code != 200:
                raise GitHubAPIError(
                    f"Could not get tags for {action_repository}: "
                    f"{error_summary(response.status_code, response.text)}"
                )
            tags = _validate_response(_TAG_LIST, response.text, context="tag list")
            matches.extend(
                release
                for tag in tags
                if _same_commit(tag.commit.sha, current_sha)
                if (release := releases_by_tag.get(tag.name)) is not None
            )

        found = max(
            matches,
            key=lambda release: release.tag_version or Version("0"),
            default=None,
        )
        self._release_sha_cache[cache_key] = found
        return found

    def _default_branch(self, action_repository: str) -> str:
        url = f"{self._api_url}/repos/{action_repository}"
        response = self._get(url)
        if response.status_code != 200:
            raise GitHubAPIError(
                f"Could not get the default branch for {action_repository}: "
                f"{error_summary(response.status_code, response.text)}"
            )
        payload = _validate_response(_REPOSITORY, response.text, context="repository")
        return payload.default_branch


def next_page_url(link_header: str | None) -> str | None:
    """Return the ``rel=next`` URL from a GitHub ``Link`` header."""
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        start = section.find("<")
        end = section.find(">", start + 1)
        if start != -1 and end != -1:
            return section[start + 1 : end]
    return None


def _validate_response[T](adapter: TypeAdapter[T], raw: str, *, context: str) -> T:
    try:
        return adapter.validate_json(raw)
    except ValidationError as exc:
        raise GitHubAPIError(f"GitHub returned an invalid {context} response") from exc


def _same_commit(candidate: str, current: str) -> bool:
    """True if both are hex SHAs and one is a prefix of the other (min 7 chars)."""
    if not candidate or not current:
        return False
    shorter, longer = sorted((candidate.lower(), current.lower()), key=len)
    return (
        len(shorter) >= 7
        and all(character in _HEX_DIGITS for character in shorter)
        and all(character in _HEX_DIGITS for character in longer)
        and longer.startswith(shorter)
    )


def _is_full_commit_sha(value: str) -> bool:
    return len(value) == 40 and all(character in _HEX_DIGITS for character in value)


def _should_retry(response: HttpResponse) -> bool:
    if response.status_code == 429 or response.status_code >= 500:
        return True
    if response.status_code != 403:
        return False
    if response.header("retry-after") is not None:
        return True
    if response.header("x-ratelimit-remaining") == "0":
        return True
    return "rate limit" in response.text.lower()


def _same_origin(url: str, expected: str) -> bool:
    actual_parts = urlsplit(url)
    expected_parts = urlsplit(expected)
    return (
        actual_parts.scheme == expected_parts.scheme
        and actual_parts.netloc == expected_parts.netloc
    )


def _retry_after_seconds(response: HttpResponse) -> float | None:
    raw = response.header("retry-after")
    if raw is None:
        return None
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return None


def error_summary(status: int, body: str) -> str:
    """HTTP status plus GitHub's ``message``, or a short body snippet."""
    if not (stripped := body.strip()):
        return f"HTTP {status}"
    try:
        payload = GitHubMessagePayload.model_validate_json(stripped)
    except ValueError:
        snippet = stripped.replace("\n", " ")[:160]
        return f"HTTP {status}: {snippet}"
    if payload.message:
        return f"HTTP {status}: {payload.message}"
    return f"HTTP {status}"


def _release_filter(
    release_types: frozenset[ReleaseType],
) -> Callable[[Version, Version], bool]:
    all_types = frozenset(ReleaseType)
    if release_types == all_types:
        return lambda release, current: release > current

    def matches(release_tag: Version, current_version: Version) -> bool:
        checks: list[bool] = []
        if ReleaseType.MAJOR in release_types:
            checks.append(release_tag.major > current_version.major)
        if ReleaseType.MINOR in release_types:
            checks.append(
                release_tag.major == current_version.major
                and release_tag.minor > current_version.minor
            )
        if ReleaseType.PATCH in release_types:
            checks.append(
                release_tag.major == current_version.major
                and release_tag.minor == current_version.minor
                and release_tag.micro > current_version.micro
            )
        return any(checks)

    return matches
