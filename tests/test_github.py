"""GitHub version lookup with a fake Session (no network)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
import requests

from tests.conftest import FakeResponse, FakeSession, silent_reporter
from update_gha.github import (
    GitHubAPIError,
    GitHubClient,
    HttpResponse,
    _is_full_commit_sha,
    _same_commit,
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


def _client(
    session: FakeSession, *, sleeper: Callable[[float], None] | None = None
) -> GitHubClient:
    return GitHubClient(
        "token-token", silent_reporter(), session=session, sleeper=sleeper
    )


def _release(
    tag: str,
    *,
    html_url: str = "https://example.com/tag",
    published_at: str | None = "2024-01-01T00:00:00Z",
    draft: bool = False,
    prerelease: bool = False,
) -> dict[str, str | bool | None]:
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
) -> dict[str, object]:
    return {
        "sha": sha,
        "html_url": html_url,
        "commit": {"author": {"date": date}},
    }


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
    client = GitHubClient("token-token", silent_reporter(), session=session)
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


def test_draft_releases_are_ignored() -> None:
    session = FakeSession(
        {
            RELEASES_URL: FakeResponse(
                200,
                [
                    _release("v9.0.0", published_at=None, draft=True),
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
    client = GitHubClient("token-token", silent_reporter(), session=session)
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


def test_error_summary_uses_message_not_raw_body() -> None:
    body = '{"message": "API rate limit exceeded", "documentation_url": "https://docs"}'
    assert error_summary(403, body) == "HTTP 403: API rate limit exceeded"
    assert "documentation_url" not in error_summary(403, body)


def test_error_summary_empty_invalid_and_blank_message() -> None:
    assert error_summary(500, "") == "HTTP 500"
    assert error_summary(500, "{").startswith("HTTP 500:")
    assert error_summary(500, "{}") == "HTTP 500"


def test_request_headers_include_token_only_when_set() -> None:
    assert request_headers(None) == {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "update-gha",
    }
    assert request_headers("secret")["Authorization"] == "Bearer secret"


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
    owned = GitHubClient("token-token", silent_reporter(), sleeper=lambda _d: None)
    owned.close()
    owned.close()
    assert owned._owned_session is None


def test_owned_session_get_adapts_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Response:
        status_code = 200
        text = "[]"

        def __init__(self) -> None:
            self.headers = {"X-Test": 1}

    class _Session:
        def get(
            self,
            url: str,
            headers: dict[str, str] | None = None,
            timeout: float | None = None,
        ) -> _Response:
            _ = (url, headers, timeout)
            return _Response()

        def close(self) -> None:
            return None

    monkeypatch.setattr("update_gha.github.requests.Session", _Session)
    client = GitHubClient("token-token", silent_reporter(), sleeper=lambda _d: None)
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
                200, [_release("v2.1.0", html_url="https://ex/v2")]
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


def test_release_commit_sha_when_no_releases() -> None:
    session = FakeSession({RELEASES_URL: FakeResponse(200, [])})
    assert (
        _client(session).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
            ALL_RELEASE_TYPES,
        )
        is None
    )


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
    assert first == second


def test_invalid_github_payload_raises_clear_error() -> None:
    session = FakeSession({RELEASES_URL: FakeResponse(200, "not-json")})
    with pytest.raises(GitHubAPIError, match="invalid release list"):
        _client(session).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )


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


def test_non_semver_current_with_restricted_types_is_skipped() -> None:
    session = FakeSession({RELEASES_URL: FakeResponse(200, [_release("v2.0.0")])})
    assert (
        _client(session).resolve_new_version(
            "actions/checkout",
            "main",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            frozenset({ReleaseType.PATCH}),
        )
        is None
    )


def test_non_sha_commit_ref_with_restricted_types_is_skipped() -> None:
    client = _client(FakeSession({}))
    assert (
        client.resolve_new_version(
            "actions/checkout",
            "main",
            UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA,
            frozenset({ReleaseType.PATCH}),
        )
        is None
    )


def test_transport_error_becomes_github_api_error() -> None:
    class BoomSession:
        def get(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
            raise requests.ConnectionError("offline")

    with pytest.raises(GitHubAPIError, match="Could not reach GitHub"):
        GitHubClient(
            "token-token", silent_reporter(), session=BoomSession()
        ).resolve_new_version(
            "actions/checkout",
            "v1",
            UpdateVersionWith.LATEST_RELEASE_TAG,
            ALL_RELEASE_TYPES,
        )
