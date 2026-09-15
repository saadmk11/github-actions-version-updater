"""GitHub REST calls for the update pull request, reviewers, and labels."""

from __future__ import annotations

import json
from collections.abc import Sequence

import requests
from pydantic import BaseModel, ConfigDict

from update_gha.config import Configuration
from update_gha.github import HTTP_TIMEOUT_SECONDS, error_summary, request_headers
from update_gha.log import Reporter

API_ROOT = "https://api.github.com"


class _CreatedPullRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    number: int
    html_url: str


def request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> tuple[int, str]:
    response = requests.request(
        method, url, headers=headers, data=body, timeout=timeout
    )
    return response.status_code, response.text


def api_request(
    method: str,
    url: str,
    config: Configuration,
    payload: dict[str, str | list[str]] | None = None,
) -> tuple[int, str]:
    token = config.token
    if not token:
        raise ValueError("A GitHub token is required to call the pull-request API.")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = request_headers(token)
    headers["Content-Type"] = "application/json"
    return request(method, url, headers, data)


def create_pull_request(
    config: Configuration,
    reporter: Reporter,
    *,
    head: str,
    base: str,
    body: str,
) -> int | None:
    url = f"{API_ROOT}/repos/{config.repository}/pulls"
    status, raw = api_request(
        "POST",
        url,
        config,
        {
            "title": config.pull_request_title,
            "head": head,
            "base": base,
            "body": body,
        },
    )
    match status:
        case 201:
            created = _CreatedPullRequest.model_validate_json(raw)
            reporter.info(f"Pull request opened at {created.html_url}")
            return created.number
        case 422 if "A pull request already exists for" in raw:
            reporter.info("A pull request already exists")
            return None
        case _:
            reporter.error(
                f"Could not create a pull request on {config.repository}: "
                f"{error_summary(status, raw)}"
            )
            raise SystemExit(1)


def add_reviewers(
    config: Configuration,
    reporter: Reporter,
    *,
    pull_request_number: int,
    users: Sequence[str],
    teams: Sequence[str],
) -> None:
    if not users and not teams:
        reporter.info("No reviewers were requested.")
        return
    payload: dict[str, str | list[str]] = {}
    if users:
        payload["reviewers"] = list(users)
    if teams:
        payload["team_reviewers"] = list(teams)
    url = (
        f"{API_ROOT}/repos/{config.repository}/pulls/"
        f"{pull_request_number}/requested_reviewers"
    )
    status, raw = api_request("POST", url, config, payload)
    if status == 201:
        names = ", ".join([*users, *teams])
        reporter.info(f"Requested review from {names}")
        return
    reporter.error(
        f"Could not request reviews on pull request #{pull_request_number} "
        f"on {config.repository}: {error_summary(status, raw)}"
    )


def add_labels(
    config: Configuration,
    reporter: Reporter,
    *,
    pull_request_number: int,
    labels: Sequence[str],
) -> None:
    if not labels:
        reporter.info("No labels to add.")
        return
    url = f"{API_ROOT}/repos/{config.repository}/issues/{pull_request_number}/labels"
    status, raw = api_request("POST", url, config, {"labels": list(labels)})
    if status == 200:
        reporter.info(
            f"Added {list(labels)!r} labels to pull request #{pull_request_number}"
        )
        return
    reporter.error(
        f"Could not add labels to pull request #{pull_request_number} "
        f"on {config.repository}: {error_summary(status, raw)}"
    )
