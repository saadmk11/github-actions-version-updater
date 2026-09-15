"""Tests for pull-request REST calls."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from tests.action.conftest import make_config
from tests.conftest import RecordingReporter, silent_reporter

from update_gha.action import pulls

type RequestFn = Callable[..., tuple[int, str]]


def _stub_request(status: int, payload: str = "{}") -> RequestFn:
    def fake(*_args: object, **_kwargs: object) -> tuple[int, str]:
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
    called: list[object] = []

    def unexpected(*_args: object, **_kwargs: object) -> tuple[int, str]:
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
    captured: list[dict[str, object]] = []

    def fake(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float = 0,
    ) -> tuple[int, str]:
        captured.append(json.loads(body or b"{}"))
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
    called: list[object] = []

    def unexpected(*_args: object, **_kwargs: object) -> tuple[int, str]:
        called.append(True)
        return 200, "{}"

    monkeypatch.setattr(pulls, "request", unexpected)
    pulls.add_labels(make_config(), silent_reporter(), pull_request_number=1, labels=())
    assert called == []


def test_add_labels_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, object]] = []

    def fake(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float = 0,
    ) -> tuple[int, str]:
        captured.append(json.loads(body or b"{}"))
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


def test_api_request_requires_token() -> None:
    with pytest.raises(ValueError, match="token"):
        pulls.api_request("GET", "https://example.com", make_config(token=None))


def test_request_uses_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Response:
        status_code = 200
        text = '{"ok": true}'

    monkeypatch.setattr(
        "update_gha.action.pulls.requests.request",
        lambda *_args, **_kwargs: _Response(),
    )
    status, body = pulls.request("GET", "https://example.com", {}, None)
    assert status == 200
    assert "ok" in body
