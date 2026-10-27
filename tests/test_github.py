"""GitHub version lookup with a fake Session (no network)."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import cast

import httpx2
import pytest
from pydantic import JsonValue, SecretStr

from tests.conftest import FakeResponse, FakeSession, RecordingReporter, silent_reporter
from update_gha.github import (
    GitHubAPIError,
    GitHubClient,
    HttpResponse,
    _is_full_commit_sha,
    _same_commit,
    _same_origin,
    error_summary,
    next_page_url,
    parse_version,
    request_headers,
)
from update_gha.models import ReleaseType, UpdateVersionWith

RELEASES_URL = "https://api.github.com/repos/actions/checkout/releases?per_page=100"
CHECKOUT_REPO = "https://api.github.com/repos/actions/checkout"
TAGS_URL = f"{CHECKOUT_REPO}/tags?per_page=100"
ALL_RELEASE_TYPES = frozenset(ReleaseType)
RELEASE_FILTERS = (
    frozenset({ReleaseType.MAJOR}),
    frozenset({ReleaseType.MINOR}),
    frozenset({ReleaseType.PATCH}),
    frozenset({ReleaseType.MAJOR, ReleaseType.MINOR}),
    frozenset({ReleaseType.MAJOR, ReleaseType.PATCH}),
    frozenset({ReleaseType.MINOR, ReleaseType.PATCH}),
    ALL_RELEASE_TYPES,
)


def _client(
    session: FakeSession, *, sleeper: Callable[[float], None] | None = None
) -> GitHubClient:
    return GitHubClient(
        SecretStr("token-token"), silent_reporter(), session=session, sleeper=sleeper
    )


def _release(
    tag: str,
    *,
    html_url: str = "https://example.com/tag",
    published_at: str | None = "2024-01-01T00:00:00Z",
    draft: bool = False,
    prerelease: bool = False,
) -> dict[str, JsonValue]:
    return {
        "tag_name": tag,
        "html_url": html_url,
        "published_at": published_at,
        "draft": draft,
        "prerelease": prerelease,
    }


def _commit(
    sha: str,
    *,
    html_url: str = "https://example.com/c",
    date: str = "2024-01-01T00:00:00Z",
) -> dict[str, JsonValue]:
    return {
        "sha": sha,
        "html_url": html_url,
        "commit": {"author": {"date": date}},
    }


def _transition_session() -> FakeSession:
    releases = (
        ("v2.0.0", "d" * 40),
        ("v1.3.2", "8" * 40),
        ("v1.3.0", "c" * 40),
        ("v1.2.4", "b" * 40),
        ("v1.2.3", "a" * 40),
        ("v1.0.1", "f" * 40),
    )
    return FakeSession(
        {
            RELEASES_URL: FakeResponse(200, [_release(tag) for tag, _ in releases]),
            TAGS_URL: FakeResponse(
                200, [{"name": tag, "commit": {"sha": sha}} for tag, sha in releases]
            ),
            CHECKOUT_REPO: FakeResponse(200, {"default_branch": "main"}),
            f"{CHECKOUT_REPO}/commits?sha=main": FakeResponse(200, [_commit("e" * 40)]),
            f"{CHECKOUT_REPO}/commits?sha=maintenance": FakeResponse(
                200, [_commit("a" * 40)]
            ),
            f"{CHECKOUT_REPO}/commits?sha=stable": FakeResponse(
                200, [_commit("a" * 40)]
            ),
            f"{CHECKOUT_REPO}/commits?sha=v1": FakeResponse(200, [_commit("b" * 40)]),
            f"{CHECKOUT_REPO}/commits?sha=v1.2": FakeResponse(200, [_commit("b" * 40)]),
            **{
                f"{CHECKOUT_REPO}/commits?sha={tag}": FakeResponse(200, [_commit(sha)])
                for tag, sha in releases
            },
        }
    )


@pytest.mark.parametrize(
    "current_ref", ["v1.2.3", "a" * 40, "maintenance", "stable", "v1", "v1.2"]
)
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (UpdateVersionWith.LATEST_RELEASE_TAG, "v2.0.0"),
        (UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA, "d" * 40),
        (UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA, "e" * 40),
    ],
)
def test_current_ref_format_does_not_determine_the_update_source(
    current_ref: str, mode: UpdateVersionWith, expected: str
) -> None:
    reporter = RecordingReporter()
    client = GitHubClient(
        SecretStr("token-token"), reporter, session=_transition_session()
    )
    resolved = client.resolve_new_version(
        "actions/checkout", current_ref, mode, ALL_RELEASE_TYPES
    )
    assert resolved is not None and resolved.version == expected
    assert reporter.warnings == []


@pytest.mark.parametrize(
    "current_ref", ["v1.2.3", "a" * 40, "maintenance", "stable", "v1", "v1.2"]
)
@pytest.mark.parametrize(
    "mode",
    [UpdateVersionWith.LATEST_RELEASE_TAG, UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA],
)
@pytest.mark.parametrize(
    ("release_types", "tag", "sha"),
    [
        (frozenset({ReleaseType.MAJOR}), "v2.0.0", "d" * 40),
        (frozenset({ReleaseType.MINOR}), "v1.3.2", "8" * 40),
        (frozenset({ReleaseType.PATCH}), "v1.2.4", "b" * 40),
        (frozenset({ReleaseType.MAJOR, ReleaseType.MINOR}), "v2.0.0", "d" * 40),
        (frozenset({ReleaseType.MAJOR, ReleaseType.PATCH}), "v2.0.0", "d" * 40),
        (frozenset({ReleaseType.MINOR, ReleaseType.PATCH}), "v1.3.2", "8" * 40),
        (ALL_RELEASE_TYPES, "v2.0.0", "d" * 40),
    ],
)
def test_release_filters_are_independent_of_input_and_output_formats(
    current_ref: str,
    mode: UpdateVersionWith,
    release_types: frozenset[ReleaseType],
    tag: str,
    sha: str,
) -> None:
    reporter = RecordingReporter()
    client = GitHubClient(
        SecretStr("token-token"), reporter, session=_transition_session()
    )
    resolved = client.resolve_new_version(
        "actions/checkout", current_ref, mode, release_types
    )
    assert resolved is not None
    assert resolved.version == (
        tag if mode is UpdateVersionWith.LATEST_RELEASE_TAG else sha
    )
    assert resolved.release is not None and resolved.release.tag_name == tag
    assert reporter.warnings == []


@pytest.mark.parametrize("release_types", RELEASE_FILTERS)
def test_current_release_tag_can_be_converted_to_its_sha(
    release_types: frozenset[ReleaseType],
) -> None:
    reporter = RecordingReporter()
    client = GitHubClient(
        SecretStr("token-token"), reporter, session=_transition_session()
    )
    resolved = client.resolve_new_version(
        "actions/checkout",
        "v2.0.0",
        UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
        release_types,
    )
    assert resolved is not None and resolved.version == "d" * 40
    assert reporter.warnings == []


@pytest.mark.parametrize("release_types", RELEASE_FILTERS)
def test_current_release_tag_is_unchanged_in_tag_mode(
    release_types: frozenset[ReleaseType],
) -> None:
    reporter = RecordingReporter()
    client = GitHubClient(
        SecretStr("token-token"), reporter, session=_transition_session()
    )
    assert (
        client.resolve_new_version(
            "actions/checkout",
            "v2.0.0",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            release_types,
        )
        is None
    )
    assert reporter.warnings == []


@pytest.mark.parametrize(
    "mode",
    [UpdateVersionWith.LATEST_RELEASE_TAG, UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA],
)
def test_version_tag_without_a_release_can_use_filters(mode: UpdateVersionWith) -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(200, [_release("v1.2.4"), _release("v2.0.0")]),
            f"{CHECKOUT_REPO}/commits?sha=v1.2.3": FakeResponse(
                200, [_commit("a" * 40)]
            ),
            f"{CHECKOUT_REPO}/commits?sha=v1.2.4": FakeResponse(
                200, [_commit("b" * 40)]
            ),
            TAGS_URL: FakeResponse(
                200, [{"name": "v1.2.3", "commit": {"sha": "a" * 40}}]
            ),
        }
    )
    reporter = RecordingReporter()
    resolved = GitHubClient(None, reporter, session=session).resolve_new_version(
        "actions/checkout", "v1.2.3", mode, frozenset({ReleaseType.PATCH})
    )
    assert resolved is not None
    assert resolved.version == (
        "v1.2.4" if mode is UpdateVersionWith.LATEST_RELEASE_TAG else "b" * 40
    )
    assert reporter.warnings == []


@pytest.mark.parametrize("current_ref", ["v1", "v1.2"])
@pytest.mark.parametrize(
    "mode",
    [UpdateVersionWith.LATEST_RELEASE_TAG, UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA],
)
def test_moving_tag_release_uses_the_version_at_its_commit(
    current_ref: str, mode: UpdateVersionWith
) -> None:
    releases = (
        ("v2.0.0", "d" * 40),
        ("v1.2.4", "b" * 40),
        ("v1.0.1", "f" * 40),
        (current_ref, "b" * 40),
    )
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(200, [_release(tag) for tag, _ in releases]),
            TAGS_URL: FakeResponse(
                200, [{"name": tag, "commit": {"sha": sha}} for tag, sha in releases]
            ),
            **{
                f"{CHECKOUT_REPO}/commits?sha={tag}": FakeResponse(200, [_commit(sha)])
                for tag, sha in releases
            },
        }
    )
    resolved = _client(session).resolve_new_version(
        "actions/checkout", current_ref, mode, frozenset({ReleaseType.PATCH})
    )
    assert resolved is not None
    assert resolved.version == (
        "v1.2.4" if mode is UpdateVersionWith.LATEST_RELEASE_TAG else "b" * 40
    )


@pytest.mark.parametrize("moving_tag", ["v1", "v1.2"])
@pytest.mark.parametrize("ref_kind", ["tag", "branch", "sha"])
@pytest.mark.parametrize(
    "mode",
    [UpdateVersionWith.LATEST_RELEASE_TAG, UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA],
)
def test_moving_release_tags_cannot_supply_a_patch_baseline(
    moving_tag: str, ref_kind: str, mode: UpdateVersionWith
) -> None:
    current_sha = "b" * 40
    current_ref = {"tag": moving_tag, "branch": "maintenance", "sha": current_sha}[
        ref_kind
    ]
    reporter = RecordingReporter()
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200,
                [_release("v1.2.1"), _release("v1.0.1"), _release(moving_tag)],
            ),
            TAGS_URL: FakeResponse(
                200,
                [
                    {"name": moving_tag, "commit": {"sha": current_sha}},
                    {"name": "v1.2.4", "commit": {"sha": current_sha}},
                ],
            ),
            f"{CHECKOUT_REPO}/commits?sha={current_ref}": FakeResponse(
                200, [_commit(current_sha)]
            ),
            f"{CHECKOUT_REPO}/commits?sha=v1.2.1": FakeResponse(
                200, [_commit("c" * 40)]
            ),
            f"{CHECKOUT_REPO}/commits?sha=v1.0.1": FakeResponse(
                200, [_commit("d" * 40)]
            ),
        }
    )
    resolved = GitHubClient(None, reporter, session=session).resolve_new_version(
        "actions/checkout", current_ref, mode, frozenset({ReleaseType.PATCH})
    )
    assert resolved is None
    assert len(reporter.warnings) == 1
    assert "Could not determine a semantic release" in reporter.warnings[0]


@pytest.mark.parametrize(
    "mode",
    [UpdateVersionWith.LATEST_RELEASE_TAG, UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA],
)
def test_restricted_filters_do_not_select_unversioned_releases(
    mode: UpdateVersionWith,
) -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(200, [_release("stable")]),
            f"{CHECKOUT_REPO}/commits?sha=v1.2.3": FakeResponse(
                200, [_commit("a" * 40)]
            ),
            TAGS_URL: FakeResponse(200, []),
        }
    )
    assert (
        _client(session).resolve_new_version(
            "actions/checkout", "v1.2.3", mode, frozenset({ReleaseType.PATCH})
        )
        is None
    )


@pytest.mark.parametrize(
    "mode",
    [UpdateVersionWith.LATEST_RELEASE_TAG, UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA],
)
def test_non_semantic_release_refs_cannot_use_semantic_filters(
    mode: UpdateVersionWith,
) -> None:
    reporter = RecordingReporter()
    client = GitHubClient(
        SecretStr("token-token"),
        reporter,
        session=FakeSession(
            {
                RELEASES_URL: FakeResponse(200, [_release("stable")]),
                f"{CHECKOUT_REPO}/commits?sha=stable": FakeResponse(
                    200, [_commit("a" * 40)]
                ),
                TAGS_URL: FakeResponse(
                    200, [{"name": "stable", "commit": {"sha": "a" * 40}}]
                ),
            }
        ),
    )
    assert (
        client.resolve_new_version(
            "actions/checkout", "stable", mode, frozenset({ReleaseType.PATCH})
        )
        is None
    )
    assert len(reporter.warnings) == 1
    assert "release type filtering cannot be applied safely" in reporter.warnings[0]


@pytest.mark.parametrize(
    "current_ref", ["v1.2.3", "a" * 40, "main", "stable", "v1", "v1.2"]
)
@pytest.mark.parametrize("release_types", RELEASE_FILTERS)
def test_default_branch_source_ignores_release_type_filters(
    current_ref: str, release_types: frozenset[ReleaseType]
) -> None:
    reporter = RecordingReporter()
    client = GitHubClient(
        SecretStr("token-token"),
        reporter,
        session=FakeSession(
            {
                CHECKOUT_REPO: FakeResponse(200, {"default_branch": "main"}),
                f"{CHECKOUT_REPO}/commits?sha=main": FakeResponse(
                    200, [_commit("e" * 40)]
                ),
            }
        ),
    )
    resolved = client.resolve_new_version(
        "actions/checkout",
        current_ref,
        UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA,
        release_types,
    )
    assert resolved is not None and resolved.version == "e" * 40
    assert reporter.warnings == []


def test_latest_release_tag_prefers_newer_semver() -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200,
                [
                    _release("v3.0.0", published_at="2023-01-01T00:00:00Z"),
                    _release("v4.1.0"),
                    _release(
                        "v5.0.0-beta",
                        prerelease=True,
                        published_at="2024-06-01T00:00:00Z",
                    ),
                ],
            )
        }
    )
    resolved = _client(session).resolve_new_version(
        "actions/checkout",
        "v3.0.0",
        UpdateVersionWith.LATEST_RELEASE_TAG,
        ALL_RELEASE_TYPES,
    )
    assert resolved is not None
    assert resolved.version == "v4.1.0"


def test_release_types_major_only() -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200,
                [
                    {
                        "tag_name": "v3.2.0",
                        "html_url": "https://example.com/v3.2.0",
                        "published_at": "2023-06-01T00:00:00Z",
                        "prerelease": False,
                    },
                    {
                        "tag_name": "v3.0.0",
                        "html_url": "https://example.com/v3.0.0",
                        "published_at": "2023-01-01T00:00:00Z",
                        "prerelease": False,
                    },
                ],
            )
        }
    )
    client = GitHubClient(SecretStr("token-token"), silent_reporter(), session=session)
    resolved = client.resolve_new_version(
        "actions/checkout",
        "v3.0.0",
        UpdateVersionWith.LATEST_RELEASE_TAG,
        frozenset({ReleaseType.MAJOR}),
    )
    assert resolved is None


def test_default_release_types_do_not_downgrade() -> None:
    session = FakeSession({RELEASES_URL: FakeResponse(200, [_release("v4.0.0")])})
    resolved = _client(session).resolve_new_version(
        "actions/checkout",
        "v5.0.0",
        UpdateVersionWith.LATEST_RELEASE_TAG,
        ALL_RELEASE_TYPES,
    )
    assert resolved is None


@pytest.mark.parametrize(
    ("draft", "prerelease", "published_at"),
    [
        (True, False, "2024-01-01T00:00:00Z"),
        (False, True, "2024-01-01T00:00:00Z"),
        (False, False, None),
    ],
)
def test_unpublished_and_unstable_releases_are_ignored(
    draft: bool, prerelease: bool, published_at: str | None
) -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200,
                [
                    _release(
                        "v9.0.0",
                        published_at=published_at,
                        draft=draft,
                        prerelease=prerelease,
                    ),
                    _release("v4.0.0"),
                ],
            )
        }
    )
    resolved = _client(session).resolve_new_version(
        "actions/checkout",
        "v3.0.0",
        UpdateVersionWith.LATEST_RELEASE_TAG,
        ALL_RELEASE_TYPES,
    )
    assert resolved is not None
    assert resolved.version == "v4.0.0"


def test_non_semver_current_version_uses_first_release() -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200, [_release("latest", html_url="https://example.com/latest")]
            )
        }
    )
    resolved = _client(session).resolve_new_version(
        "actions/checkout",
        "main",
        UpdateVersionWith.LATEST_RELEASE_TAG,
        ALL_RELEASE_TYPES,
    )
    assert resolved is not None
    assert resolved.version == "latest"


def test_paginates_releases() -> None:
    page2 = "https://api.github.com/repos/actions/checkout/releases?per_page=100&page=2"
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200,
                [
                    {
                        "tag_name": "v3.0.0",
                        "html_url": "https://example.com/v3",
                        "published_at": "2023-01-01T00:00:00Z",
                        "prerelease": False,
                    }
                ],
                headers={"Link": f'<{page2}>; rel="next"'},
            ),
            page2: FakeResponse(
                200,
                [
                    {
                        "tag_name": "v5.0.0",
                        "html_url": "https://example.com/v5",
                        "published_at": "2025-01-01T00:00:00Z",
                        "prerelease": False,
                    }
                ],
            ),
        }
    )
    client = GitHubClient(SecretStr("token-token"), silent_reporter(), session=session)
    resolved = client.resolve_new_version(
        "actions/checkout",
        "v3.0.0",
        UpdateVersionWith.LATEST_RELEASE_TAG,
        frozenset({ReleaseType.MAJOR, ReleaseType.MINOR, ReleaseType.PATCH}),
    )
    assert resolved is not None
    assert resolved.version == "v5.0.0"


def test_rejects_cross_origin_pagination_url() -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200,
                [],
                headers={"Link": '<https://example.com/page/2>; rel="next"'},
            )
        }
    )
    with pytest.raises(GitHubAPIError, match="unexpected origin"):
        _client(session).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )


def test_request_headers_include_token_only_when_set() -> None:
    assert request_headers(None) == {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "update-gha",
    }
    assert request_headers(SecretStr("secret"))["Authorization"] == "Bearer secret"


def test_parse_version_invalid() -> None:
    assert parse_version("nope") is None


def test_commit_sha_helpers() -> None:
    assert _same_commit("abcdef1", "abcdef123456") is True
    assert _same_commit("", "abcdef1") is False
    assert _same_commit("abc", "abcdef1") is False
    assert _same_commit("abcdefg", "abcdef123456") is False
    assert _is_full_commit_sha("a" * 40) is True
    assert _is_full_commit_sha("g" * 40) is False
    assert _is_full_commit_sha("a" * 39) is False


def test_next_page_url_edge_cases() -> None:
    assert next_page_url(None) is None
    assert next_page_url('rel="prev"') is None
    assert next_page_url('no-angles; rel="next"') is None


def test_retries_exhausted_returns_last_response() -> None:
    waits: list[float] = []
    session = FakeSession(
        {
            RELEASES_URL: [
                FakeResponse(429, {"message": "slow"}),
                FakeResponse(429, {"message": "slow"}),
                FakeResponse(429, {"message": "slow"}),
                FakeResponse(429, {"message": "slow"}),
            ]
        }
    )
    with pytest.raises(GitHubAPIError, match="HTTP 429"):
        _client(session, sleeper=waits.append).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )
    assert waits == [1.0, 2.0, 4.0]


@pytest.mark.parametrize(
    ("statuses", "expected_waits"),
    [
        ([429, 429, 200], [1.0, 2.0]),
        ([503, 200], [1.0]),
    ],
)
def test_retries_transient_http_errors(
    statuses: list[int], expected_waits: list[float]
) -> None:
    waits: list[float] = []
    responses = [
        FakeResponse(status, [] if status == 200 else {"message": "retry"})
        for status in statuses
    ]
    session = FakeSession({RELEASES_URL: responses})
    _client(session, sleeper=waits.append).resolve_new_version(
        "actions/checkout",
        "v1",
        UpdateVersionWith.LATEST_RELEASE_TAG,
        ALL_RELEASE_TYPES,
    )
    assert waits == expected_waits


def test_retries_on_429_using_retry_after() -> None:
    sleeps: list[float] = []
    session = FakeSession(
        {
            RELEASES_URL: [
                FakeResponse(429, {"message": "slow"}, headers={"Retry-After": "2"}),
                FakeResponse(200, [_release("v4.0.0", html_url="https://ex/v4")]),
            ]
        }
    )
    resolved = _client(session, sleeper=sleeps.append).resolve_new_version(
        "actions/checkout",
        "v3.0.0",
        UpdateVersionWith.LATEST_RELEASE_TAG,
        ALL_RELEASE_TYPES,
    )
    assert resolved is not None
    assert sleeps == [2.0]


def test_invalid_retry_after_uses_default_delay() -> None:
    waits: list[float] = []
    session = FakeSession(
        {
            RELEASES_URL: [
                FakeResponse(403, {"message": "wait"}, headers={"Retry-After": "x"}),
                FakeResponse(200, []),
            ]
        }
    )
    _client(session, sleeper=waits.append).resolve_new_version(
        "actions/checkout",
        "v1",
        UpdateVersionWith.LATEST_RELEASE_TAG,
        ALL_RELEASE_TYPES,
    )
    assert waits == [1.0]


def test_permanent_403_does_not_retry() -> None:
    waits: list[float] = []
    session = FakeSession(
        {
            RELEASES_URL: [
                FakeResponse(
                    403,
                    {"message": "Resource not accessible by integration"},
                    headers={"X-RateLimit-Remaining": "5"},
                ),
                FakeResponse(200, [_release("v4.0.0")]),
            ]
        }
    )
    with pytest.raises(GitHubAPIError, match="HTTP 403"):
        _client(session, sleeper=waits.append).resolve_new_version(
            "actions/checkout",
            "v3.0.0",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )
    assert waits == []


def test_retries_403_when_rate_limit_remaining_exhausted() -> None:
    waits: list[float] = []
    session = FakeSession(
        {
            RELEASES_URL: [
                FakeResponse(
                    403,
                    {"message": "forbidden"},
                    headers={"X-RateLimit-Remaining": "0"},
                ),
                FakeResponse(200, [_release("v4.0.0", html_url="https://ex/v4")]),
            ]
        }
    )
    resolved = _client(session, sleeper=waits.append).resolve_new_version(
        "actions/checkout",
        "v3.0.0",
        UpdateVersionWith.LATEST_RELEASE_TAG,
        ALL_RELEASE_TYPES,
    )
    assert resolved is not None
    assert waits == [1.0]


def test_retries_403_when_body_mentions_rate_limit() -> None:
    waits: list[float] = []
    session = FakeSession(
        {
            RELEASES_URL: [
                FakeResponse(403, {"message": "API rate limit exceeded"}),
                FakeResponse(200, [_release("v4.0.0", html_url="https://ex/v4")]),
            ]
        }
    )
    resolved = _client(session, sleeper=waits.append).resolve_new_version(
        "actions/checkout",
        "v3.0.0",
        UpdateVersionWith.LATEST_RELEASE_TAG,
        ALL_RELEASE_TYPES,
    )
    assert resolved is not None
    assert waits == [1.0]


def test_owned_session_close_is_idempotent() -> None:
    owned = GitHubClient(
        SecretStr("token-token"), silent_reporter(), sleeper=lambda _d: None
    )
    assert owned._owned_session is not None
    transport = owned._owned_session._inner
    assert transport.is_closed is False
    owned.close()
    assert transport.is_closed is True
    owned.close()
    assert owned._owned_session is None


def test_owned_session_uses_httpx2_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    client_factory = httpx2.Client
    seen: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        assert request.extensions["timeout"] == {
            "connect": 10,
            "read": 30,
            "write": 30,
            "pool": 30,
        }
        return httpx2.Response(200, json=[])

    def factory(*, timeout: httpx2.Timeout, follow_redirects: bool) -> httpx2.Client:
        assert follow_redirects is False
        assert isinstance(timeout, httpx2.Timeout)
        assert timeout.connect == 10 and timeout.read == 30
        return client_factory(
            timeout=timeout,
            follow_redirects=follow_redirects,
            transport=httpx2.MockTransport(respond),
        )

    monkeypatch.setattr("update_gha.github.httpx2.Client", factory)
    client = GitHubClient(SecretStr("token-token"), silent_reporter())
    try:
        assert (
            client.resolve_new_version(
                "actions/checkout",
                "v1",
                UpdateVersionWith.LATEST_RELEASE_TAG,
                ALL_RELEASE_TYPES,
            )
            is None
        )
    finally:
        client.close()
    assert str(seen[0].url) == RELEASES_URL
    assert seen[0].headers["Authorization"] == "Bearer token-token"
    assert seen[0].headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_resolves_release_commit_sha() -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200, [_release("v4.0.0", html_url="https://ex/v4")]
            ),
            f"{CHECKOUT_REPO}/commits?sha=v4.0.0": FakeResponse(200, [_commit("abc")]),
        }
    )
    resolved = _client(session).resolve_new_version(
        "actions/checkout",
        "v3.0.0",
        UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
        ALL_RELEASE_TYPES,
    )
    assert resolved is not None and resolved.version == "abc"


@pytest.mark.parametrize(
    "current_sha",
    [
        "3d3c42e5aac5ba805825da76410c181273ba90b1",
        "1" * 40,
        "A" * 40,
        "b" * 40,
    ],
)
@pytest.mark.parametrize(
    "mode",
    [UpdateVersionWith.LATEST_RELEASE_TAG, UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA],
)
def test_existing_sha_pins_do_not_trigger_semver_warnings(
    current_sha: str, mode: UpdateVersionWith
) -> None:
    target_sha = "b" * 40
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(200, [_release("v7.0.1")]),
            f"{CHECKOUT_REPO}/commits?sha=v7.0.1": FakeResponse(
                200, [_commit(target_sha)]
            ),
        }
    )
    reporter = RecordingReporter()
    client = GitHubClient(SecretStr("token-token"), reporter, session=session)
    resolved = client.resolve_new_version(
        "actions/checkout", current_sha, mode, ALL_RELEASE_TYPES
    )
    assert resolved is not None
    assert resolved.version == (
        "v7.0.1" if mode is UpdateVersionWith.LATEST_RELEASE_TAG else target_sha
    )
    assert reporter.warnings == []


@pytest.mark.parametrize("current_sha", ["a" * 40, "1" * 40])
def test_sha_pins_still_require_a_semantic_baseline_for_release_tag_filters(
    current_sha: str,
) -> None:
    reporter = RecordingReporter()
    client = GitHubClient(
        SecretStr("token-token"),
        reporter,
        session=FakeSession(
            {
                RELEASES_URL: FakeResponse(200, [_release("v7.0.1")]),
                TAGS_URL: FakeResponse(200, []),
            }
        ),
    )
    assert (
        client.resolve_new_version(
            "actions/checkout",
            current_sha,
            UpdateVersionWith.LATEST_RELEASE_TAG,
            frozenset({ReleaseType.PATCH}),
        )
        is None
    )
    assert reporter.warnings == [
        f"Could not determine a semantic release for `{current_sha}` on "
        "`actions/checkout`; release type filtering cannot be applied safely. Skipping."
    ]


def test_resolves_default_branch_commit_sha() -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(200, [_release("v4.0.0")]),
            CHECKOUT_REPO: FakeResponse(200, {"default_branch": "main"}),
            f"{CHECKOUT_REPO}/commits?sha=main": FakeResponse(
                200,
                [_commit("def", html_url="https://ex/d", date="2024-02-01T00:00:00Z")],
            ),
        }
    )
    resolved = _client(session).resolve_new_version(
        "actions/checkout",
        "v3.0.0",
        UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA,
        ALL_RELEASE_TYPES,
    )
    assert resolved is not None and resolved.version == "def"


def test_default_branch_link_and_commit_query_are_encoded() -> None:
    branch = "feature/#stable"
    commit_url = f"{CHECKOUT_REPO}/commits?sha=feature%2F%23stable"
    session = FakeSession(
        {
            CHECKOUT_REPO: FakeResponse(200, {"default_branch": branch}),
            commit_url: FakeResponse(200, [_commit("def")]),
        }
    )
    resolved = _client(session).resolve_new_version(
        "actions/checkout",
        "v1",
        UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA,
        ALL_RELEASE_TYPES,
    )
    assert resolved is not None and resolved.branch is not None
    assert resolved.branch.url.endswith("/tree/feature/%23stable")


def test_missing_releases_returns_none() -> None:
    session = FakeSession({RELEASES_URL: FakeResponse(404, {"message": "missing"})})
    with pytest.raises(GitHubAPIError, match="HTTP 404"):
        _client(session).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )


def test_empty_commit_list_is_an_error() -> None:
    session = FakeSession(
        {
            CHECKOUT_REPO: FakeResponse(200, {"default_branch": "main"}),
            f"{CHECKOUT_REPO}/commits?sha=main": FakeResponse(200, []),
        }
    )
    with pytest.raises(GitHubAPIError, match="empty commit list"):
        _client(session).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA,
            ALL_RELEASE_TYPES,
        )


def test_default_branch_commit_missing() -> None:
    session = FakeSession(
        {
            CHECKOUT_REPO: FakeResponse(200, {"default_branch": "main"}),
            f"{CHECKOUT_REPO}/commits?sha=main": FakeResponse(404, {"message": "no"}),
        }
    )
    with pytest.raises(GitHubAPIError, match="HTTP 404"):
        _client(session).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA,
            ALL_RELEASE_TYPES,
        )


def test_non_semver_releases_with_semver_current() -> None:
    session = FakeSession(
        {RELEASES_URL: FakeResponse(200, [_release("latest", html_url="https://ex")])}
    )
    assert (
        _client(session).resolve_new_version(
            "actions/checkout",
            "v1.0.0",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )
        is not None
    )


def test_release_types_filter_minor_and_rejects() -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200,
                [_release("v2.1.0", html_url="https://ex/v2"), _release("v2.0.0")],
            )
        }
    )
    client = _client(session)
    assert (
        client.resolve_new_version(
            "actions/checkout",
            "v2.0.0",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            frozenset({ReleaseType.PATCH}),
        )
        is None
    )
    assert (
        client.resolve_new_version(
            "actions/checkout",
            "v2.0.0",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            frozenset({ReleaseType.MAJOR}),
        )
        is None
    )
    assert (
        client.resolve_new_version(
            "actions/checkout",
            "v2.0.0",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            frozenset({ReleaseType.MINOR}),
        )
        is not None
    )


def test_release_commit_sha_when_commit_missing() -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200, [_release("v2.1.0", html_url="https://ex/v2")]
            ),
            f"{CHECKOUT_REPO}/commits?sha=v2.1.0": FakeResponse(404, {"message": "no"}),
        }
    )
    with pytest.raises(GitHubAPIError, match="HTTP 404"):
        _client(session).resolve_new_version(
            "actions/checkout",
            "v2.0.0",
            UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
            ALL_RELEASE_TYPES,
        )


def test_default_branch_when_repo_missing() -> None:
    session = FakeSession({CHECKOUT_REPO: FakeResponse(404, {"message": "gone"})})
    with pytest.raises(GitHubAPIError, match="HTTP 404"):
        _client(session).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA,
            ALL_RELEASE_TYPES,
        )


@pytest.mark.parametrize(
    "current_ref", ["v1.2.3", "a" * 40, "main", "stable", "v1", "v1.2"]
)
@pytest.mark.parametrize(
    "mode",
    [UpdateVersionWith.LATEST_RELEASE_TAG, UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA],
)
@pytest.mark.parametrize("release_types", RELEASE_FILTERS)
def test_release_modes_leave_pins_unchanged_without_releases(
    current_ref: str,
    mode: UpdateVersionWith,
    release_types: frozenset[ReleaseType],
) -> None:
    reporter = RecordingReporter()
    session = FakeSession({RELEASES_URL: FakeResponse(200, [])})
    client = GitHubClient(None, reporter, session=session)
    assert (
        client.resolve_new_version("actions/checkout", current_ref, mode, release_types)
        is None
    )
    assert reporter.warnings == []


def test_release_commit_sha_applies_filter_using_matching_tag() -> None:
    current_sha = "1234567890abcdef1234567890abcdef12345678"
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200,
                [
                    _release("v2.0.0", html_url="https://ex/v2"),
                    _release("v1.2.4", html_url="https://ex/v1.2.4"),
                    _release("v1.2.3", html_url="https://ex/v1.2.3"),
                ],
            ),
            TAGS_URL: FakeResponse(
                200,
                [
                    {"name": "v2.0.0", "commit": {"sha": "2" * 40}},
                    {"name": "v1.2.4", "commit": {"sha": "4" * 40}},
                    {"name": "v1.2.3", "commit": {"sha": current_sha}},
                ],
            ),
            f"{CHECKOUT_REPO}/commits?sha=v1.2.4": FakeResponse(
                200, [_commit("4" * 40)]
            ),
        }
    )
    resolved = _client(session).resolve_new_version(
        "actions/checkout",
        current_sha,
        UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
        frozenset({ReleaseType.PATCH}),
    )
    assert resolved is not None
    assert resolved.release is not None
    assert resolved.release.tag_name == "v1.2.4"


def test_release_commit_sha_skips_restricted_filter_without_matching_tag() -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(200, [_release("v2.0.0")]),
            TAGS_URL: FakeResponse(
                200, [{"name": "v2.0.0", "commit": {"sha": "2" * 40}}]
            ),
        }
    )
    client = _client(session)
    assert (
        client.resolve_new_version(
            "actions/checkout",
            "1" * 40,
            UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
            frozenset({ReleaseType.PATCH}),
        )
        is None
    )
    # The negative lookup is cached, so a second call needs no scripted tag response.
    assert (
        client.resolve_new_version(
            "actions/checkout",
            "1" * 40,
            UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
            frozenset({ReleaseType.PATCH}),
        )
        is None
    )


def test_commit_reference_is_url_encoded_and_cached() -> None:
    url = f"{CHECKOUT_REPO}/commits?sha=v1.0.0%2Bcpu"
    client = _client(FakeSession({url: FakeResponse(200, [_commit("abc1234")])}))
    first = client._commit("actions/checkout", "v1.0.0+cpu")
    second = client._commit("actions/checkout", "v1.0.0+cpu")
    assert first.sha == "abc1234"
    assert first == second


def test_invalid_github_payload_raises_clear_error() -> None:
    secret = "response-sensitive-value"
    session = FakeSession({RELEASES_URL: FakeResponse(200, f"not-json: {secret}")})
    with pytest.raises(GitHubAPIError, match="invalid release list") as caught:
        _client(session).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )
    assert secret not in "".join(traceback.format_exception(caught.value))


def test_tag_lookup_errors_are_fatal() -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(200, [_release("v2.0.0")]),
            TAGS_URL: FakeResponse(400, {"message": "bad"}),
        }
    )
    with pytest.raises(GitHubAPIError, match="Could not get tags"):
        _client(session).resolve_new_version(
            "actions/checkout",
            "1" * 40,
            UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
            frozenset({ReleaseType.PATCH}),
        )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (UpdateVersionWith.LATEST_RELEASE_TAG, "v2.0.1"),
        (UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA, "c" * 40),
    ],
)
def test_sha_baseline_uses_highest_matching_release_across_tag_pages(
    mode: UpdateVersionWith, expected: str
) -> None:
    current_sha = "a" * 40
    page2 = f"{TAGS_URL}&page=2"
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200,
                [_release(tag) for tag in ("v1.0.0", "v1.0.1", "v2.0.0", "v2.0.1")],
            ),
            TAGS_URL: FakeResponse(
                200,
                [{"name": "v1.0.0", "commit": {"sha": current_sha}}],
                headers={"Link": f'<{page2}>; rel="next"'},
            ),
            page2: FakeResponse(
                200, [{"name": "v2.0.0", "commit": {"sha": current_sha}}]
            ),
            f"{CHECKOUT_REPO}/commits?sha=v2.0.1": FakeResponse(
                200, [_commit("c" * 40)]
            ),
            f"{CHECKOUT_REPO}/commits?sha=v1.0.1": FakeResponse(
                200, [_commit("b" * 40)]
            ),
        }
    )
    resolved = _client(session).resolve_new_version(
        "actions/checkout", current_sha, mode, frozenset({ReleaseType.PATCH})
    )
    assert resolved is not None
    assert resolved.version == expected


@pytest.mark.parametrize("current_ref", ["main", "stable", "v1", "v1.2", "f" * 40])
@pytest.mark.parametrize(
    "mode",
    [UpdateVersionWith.LATEST_RELEASE_TAG, UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA],
)
@pytest.mark.parametrize("release_types", RELEASE_FILTERS)
def test_refs_without_matching_releases_require_unrestricted_updates(
    current_ref: str,
    mode: UpdateVersionWith,
    release_types: frozenset[ReleaseType],
) -> None:
    reporter = RecordingReporter()
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(200, [_release("v2.0.0")]),
            f"{CHECKOUT_REPO}/commits?sha={current_ref}": FakeResponse(
                200, [_commit("f" * 40)]
            ),
            f"{CHECKOUT_REPO}/commits?sha=v2.0.0": FakeResponse(
                200, [_commit("d" * 40)]
            ),
            TAGS_URL: FakeResponse(
                200, [{"name": "v2.0.0", "commit": {"sha": "d" * 40}}]
            ),
        }
    )
    resolved = GitHubClient(None, reporter, session=session).resolve_new_version(
        "actions/checkout", current_ref, mode, release_types
    )
    if release_types == ALL_RELEASE_TYPES:
        assert resolved is not None
        assert resolved.version == (
            "v2.0.0" if mode is UpdateVersionWith.LATEST_RELEASE_TAG else "d" * 40
        )
        assert resolved.release is not None
        assert resolved.release.tag_name == "v2.0.0"
        assert reporter.warnings == []
    else:
        assert resolved is None
        assert reporter.warnings == [
            f"Could not determine a semantic release for `{current_ref}` "
            "on `actions/checkout`; release type filtering cannot be "
            "applied safely. Skipping."
        ]


def test_non_sha_commit_ref_with_matching_release_can_use_filters() -> None:
    client = _client(_transition_session())
    resolved = client.resolve_new_version(
        "actions/checkout",
        "maintenance",
        UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
        frozenset({ReleaseType.PATCH}),
    )
    assert resolved is not None and resolved.version == "b" * 40


@pytest.mark.parametrize("error", [httpx2.ConnectError, httpx2.InvalidURL])
def test_transport_error_becomes_github_api_error(
    error: type[httpx2.ConnectError | httpx2.InvalidURL],
) -> None:
    class BoomSession:
        def get(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
            raise error("private-token and internal-proxy-host")

    with pytest.raises(GitHubAPIError) as caught:
        GitHubClient(
            SecretStr("token-token"), silent_reporter(), session=BoomSession()
        ).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )
    assert str(caught.value) == f"Could not reach GitHub ({error.__name__})."
    rendered = "".join(traceback.format_exception(caught.value))
    assert "private-token" not in rendered
    assert "internal-proxy-host" not in rendered


def test_invalid_token_encoding_has_a_safe_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "fixture-sensitive-token-é"
    client_factory = httpx2.Client

    def factory(*, timeout: httpx2.Timeout, follow_redirects: bool) -> httpx2.Client:
        return client_factory(
            timeout=timeout,
            follow_redirects=follow_redirects,
            transport=httpx2.MockTransport(
                lambda _request: pytest.fail("Invalid header reached the transport")
            ),
        )

    monkeypatch.setattr("update_gha.github.httpx2.Client", factory)
    client = GitHubClient(SecretStr(secret), RecordingReporter())
    try:
        with pytest.raises(GitHubAPIError) as caught:
            client.resolve_new_version(
                "actions/checkout",
                "v1",
                UpdateVersionWith.LATEST_RELEASE_TAG,
                ALL_RELEASE_TYPES,
            )
    finally:
        client.close()
    assert str(caught.value) == "Could not reach GitHub (UnicodeEncodeError)."
    rendered = "".join(traceback.format_exception(caught.value))
    assert secret not in rendered
    assert "UnicodeEncodeError:" not in rendered


def test_redirect_to_renamed_repository_is_followed() -> None:
    renamed = "https://api.github.com/repos/new/action/releases?per_page=100"
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(301, headers={"Location": renamed}),
            renamed: FakeResponse(200, [_release("v2")]),
        }
    )
    resolved = _client(session).resolve_new_version(
        "actions/checkout",
        "v1",
        UpdateVersionWith.LATEST_RELEASE_TAG,
        ALL_RELEASE_TYPES,
    )
    assert resolved is not None and resolved.version == "v2"


@pytest.mark.parametrize("location", ["https://example.com/steal", ""])
def test_redirects_cannot_leave_api_origin(location: str) -> None:
    session = FakeSession(
        {RELEASES_URL: FakeResponse(302, headers={"Location": location})}
    )
    with pytest.raises(GitHubAPIError, match="unexpected redirect origin"):
        _client(session).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )


def test_redirect_loops_are_bounded() -> None:
    session = FakeSession(
        {
            RELEASES_URL: [
                FakeResponse(307, headers={"Location": RELEASES_URL}) for _ in range(6)
            ]
        }
    )
    with pytest.raises(GitHubAPIError, match="too many redirects"):
        _client(session).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )


def test_malformed_redirect_url_is_reported() -> None:
    session = FakeSession(
        {RELEASES_URL: FakeResponse(302, headers={"Location": "https://[invalid"})}
    )
    with pytest.raises(GitHubAPIError, match="invalid redirect URL"):
        _client(session).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )


@pytest.mark.parametrize(
    ("url", "trusted"),
    [
        ("https://API.GITHUB.COM:443/path", True),
        ("https://api.github.com/path", True),
        ("http://api.github.com/path", False),
        ("https://api.github.com:8443/path", False),
        ("https://api.github.com:0/path", False),
        ("https://user@api.github.com/path", False),
        ("https://:password@api.github.com/path", False),
        ("https://api.github.com:invalid/path", False),
        ("https://[invalid/path", False),
    ],
)
def test_api_origin_validation(url: str, trusted: bool) -> None:
    assert _same_origin(url, "https://api.github.com") is trusted


def test_invalid_update_mode_cannot_silently_skip() -> None:
    # Exercise callers bypassing validation with an unsupported runtime value.
    mode = cast(UpdateVersionWith, "unknown-mode")
    with pytest.raises(AssertionError):
        _client(FakeSession({})).resolve_new_version(
            "o/r", "v1", mode, ALL_RELEASE_TYPES
        )


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, "authentication failed"),
        (403, "permission denied or rate limited"),
        (404, "repository or resource unavailable"),
        (422, "request validation failed"),
        (429, "rate limited"),
        (500, "request failed"),
    ],
)
def test_error_summary_uses_only_status(status: int, reason: str) -> None:
    assert error_summary(status) == f"HTTP {status}: {reason}"


@pytest.mark.parametrize("raw_body", [True, False])
def test_client_keeps_token_wrapped_and_omits_response_body(raw_body: bool) -> None:
    secret = SecretStr("fixture-sensitive-token")
    body = "response-sensitive-value"
    client = GitHubClient(
        secret,
        RecordingReporter(),
        session=FakeSession(
            {RELEASES_URL: FakeResponse(401, body if raw_body else {"message": body})}
        ),
    )
    assert isinstance(client._token, SecretStr)
    assert secret.get_secret_value() not in repr(client._token)
    with pytest.raises(GitHubAPIError) as error:
        client.resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )
    assert body not in str(error.value)
    assert "HTTP 401: authentication failed" in str(error.value)
