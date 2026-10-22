"""Tests for pull-request REST calls."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import TypeAdapter
from tests.action.conftest import make_config
from tests.conftest import RecordingReporter, silent_reporter

from update_gha.action import pulls
from update_gha.github import GitHubAPIError

type RequestFn = Callable[
    [str, str, dict[str, str], bytes | None, float], tuple[int, str]
]


def _stub_request(status: int, payload: str = "{}") -> RequestFn:
    def fake(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float = 30,
    ) -> tuple[int, str]:
        return status, payload

    return fake


def test_create_pull_request_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pulls,
        "request",
        _stub_request(
            201, '{"number": 42, "html_url": "https://github.com/o/r/pull/42"}'
        ),
    )
    number = pulls.create_pull_request(
        make_config(),
        silent_reporter(),
        head="branch",
        base="main",
        body="body",
    )
    assert number == 42


def test_create_pull_request_already_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    reporter = RecordingReporter()
    payload = json.dumps(
        {
            "message": "Validation Failed",
            "errors": [
                {
                    "resource": "PullRequest",
                    "code": "custom",
                    "message": "A pull request already exists for o:branch.",
                }
            ],
        }
    )
    monkeypatch.setattr(pulls, "request", _stub_request(422, payload))
    number = pulls.create_pull_request(
        make_config(),
        reporter,
        head="branch",
        base="main",
        body="body",
    )
    assert number is None
    assert any("already exists" in message.lower() for message in reporter.infos)


@pytest.mark.parametrize(
    "status_and_body",
    [
        (422, '{"message": "Head can\'t be blank."}'),
        (400, '{"message": "nope"}'),
    ],
)
def test_create_pull_request_raises_on_error(
    monkeypatch: pytest.MonkeyPatch, status_and_body: tuple[int, str]
) -> None:
    status, body = status_and_body
    reporter = RecordingReporter()
    monkeypatch.setattr(pulls, "request", _stub_request(status, body))
    with pytest.raises(SystemExit) as exited:
        pulls.create_pull_request(
            make_config(),
            reporter,
            head="branch",
            base="main",
            body="body",
        )
    assert exited.value.code == 1
    assert reporter.errors


def test_add_reviewers_skips_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    def unexpected(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float = 30,
    ) -> tuple[int, str]:
        called.append(True)
        return 201, "{}"

    monkeypatch.setattr(pulls, "request", unexpected)
    pulls.add_reviewers(
        make_config(),
        silent_reporter(),
        pull_request_number=1,
        users=(),
        teams=(),
    )
    assert called == []


def test_add_reviewers_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    reporter = RecordingReporter()
    monkeypatch.setattr(pulls, "request", _stub_request(400, '{"message": "nope"}'))
    pulls.add_reviewers(
        make_config(),
        reporter,
        pull_request_number=1,
        users=("a",),
        teams=("b",),
    )
    assert reporter.errors
    assert "nope" in reporter.errors[0]


@pytest.mark.parametrize(
    ("users", "teams", "payload"),
    [
        (("ada",), (), {"reviewers": ["ada"]}),
        ((), ("core",), {"team_reviewers": ["core"]}),
        (("ada",), ("core",), {"reviewers": ["ada"], "team_reviewers": ["core"]}),
    ],
)
def test_add_reviewers_sends_requested_payload(
    monkeypatch: pytest.MonkeyPatch,
    users: tuple[str, ...],
    teams: tuple[str, ...],
    payload: dict[str, list[str]],
) -> None:
    captured: list[dict[str, list[str]]] = []

    def fake(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float = 0,
    ) -> tuple[int, str]:
        captured.append(TypeAdapter(dict[str, list[str]]).validate_json(body or b"{}"))
        return 201, "{}"

    monkeypatch.setattr(pulls, "request", fake)
    pulls.add_reviewers(
        make_config(),
        silent_reporter(),
        pull_request_number=1,
        users=users,
        teams=teams,
    )
    assert captured == [payload]


def test_add_labels_skips_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    def unexpected(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float = 30,
    ) -> tuple[int, str]:
        called.append(True)
        return 200, "{}"

    monkeypatch.setattr(pulls, "request", unexpected)
    pulls.add_labels(make_config(), silent_reporter(), pull_request_number=1, labels=())
    assert called == []


def test_add_labels_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, list[str]]] = []

    def fake(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float = 0,
    ) -> tuple[int, str]:
        captured.append(TypeAdapter(dict[str, list[str]]).validate_json(body or b"{}"))
        return 200, "{}"

    reporter = RecordingReporter()
    monkeypatch.setattr(pulls, "request", fake)
    pulls.add_labels(make_config(), reporter, pull_request_number=1, labels=("bug",))
    assert captured == [{"labels": ["bug"]}]
    assert any("bug" in message for message in reporter.infos)


def test_add_labels_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    reporter = RecordingReporter()
    monkeypatch.setattr(pulls, "request", _stub_request(400, '{"message": "nope"}'))
    pulls.add_labels(make_config(), reporter, pull_request_number=1, labels=("bug",))
    assert reporter.errors
    assert "nope" in reporter.errors[0]


@pytest.mark.parametrize("token", [None, ""])
def test_api_request_requires_token(token: str | None) -> None:
    with pytest.raises(ValueError, match="token"):
        pulls.api_request("GET", "https://example.com", make_config(token=token))


@pytest.mark.parametrize("timeout", [0.5, 30.0])
def test_request_preserves_payload_authentication_and_timeout(
    timeout: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://api.github.com/repos/o/r/pulls"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.content == b'{"title":"Update"}'
        assert request.extensions["timeout"] == {
            "connect": min(timeout, 10),
            "read": timeout,
            "write": timeout,
            "pool": timeout,
        }
        return httpx.Response(201, text='{"number":42}')

    with httpx.Client(transport=httpx.MockTransport(respond)) as api:
        monkeypatch.setattr("update_gha.action.pulls.httpx.request", api.request)
        assert pulls.request(
            "POST",
            "https://api.github.com/repos/o/r/pulls",
            {"Authorization": "Bearer test-token"},
            b'{"title":"Update"}',
            timeout=timeout,
        ) == (201, '{"number":42}')
    assert len(seen) == 1


@pytest.mark.parametrize("status", [301, 307, 308])
def test_pull_request_follows_same_origin_redirect_with_body(
    status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer token-token"
        assert request.headers["Content-Type"] == "application/json"
        assert TypeAdapter(dict[str, str]).validate_json(request.content) == {
            "title": "Update GitHub Action Versions",
            "head": "updates",
            "base": "main",
            "body": "Release notes",
        }
        if request.url.path == "/repos/o/r/pulls":
            return httpx.Response(
                status, headers={"Location": "/repos/o/renamed/pulls"}
            )
        assert request.url.path == "/repos/o/renamed/pulls"
        return httpx.Response(
            201, json={"number": 42, "html_url": "https://github.com/o/renamed/pull/42"}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as api:
        monkeypatch.setattr("update_gha.action.pulls.httpx.request", api.request)
        assert (
            pulls.create_pull_request(
                make_config(),
                silent_reporter(),
                head="updates",
                base="main",
                body="Release notes",
            )
            == 42
        )
    assert len(seen) == 2


@pytest.mark.parametrize(
    "location",
    [
        "https://other.example/pulls",
        "http://api.github.com/pulls",
        "https://user@api.github.com/pulls",
        "",
    ],
)
def test_pull_request_redirect_cannot_forward_token_to_another_origin(
    location: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(307, headers={"Location": location})

    with httpx.Client(transport=httpx.MockTransport(respond)) as api:
        monkeypatch.setattr("update_gha.action.pulls.httpx.request", api.request)
        with pytest.raises(GitHubAPIError, match="unexpected redirect origin"):
            pulls.request(
                "POST",
                "https://api.github.com/repos/o/r/pulls",
                {"Authorization": "Bearer secret"},
                b"{}",
            )
    assert len(seen) == 1


def test_pull_request_redirect_loop_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert len(seen) <= 10
        return httpx.Response(307, headers={"Location": str(request.url)})

    with httpx.Client(transport=httpx.MockTransport(respond)) as api:
        monkeypatch.setattr("update_gha.action.pulls.httpx.request", api.request)
        with pytest.raises(GitHubAPIError, match="too many redirects"):
            pulls.request("POST", "https://api.github.com/repos/o/r/pulls", {}, b"{}")


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.InvalidURL])
def test_transport_failure_has_safe_diagnostic(
    error: type[httpx.ConnectError | httpx.InvalidURL], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes | None,
        timeout: httpx.Timeout,
        follow_redirects: bool,
    ) -> httpx.Response:
        raise error("private-token and internal-proxy-host")

    monkeypatch.setattr("update_gha.action.pulls.httpx.request", fail)
    with pytest.raises(GitHubAPIError) as caught:
        pulls.request("POST", "https://api.github.com/repos/o/r/pulls", {}, b"{}")
    assert str(caught.value) == f"Could not reach GitHub ({error.__name__})."
