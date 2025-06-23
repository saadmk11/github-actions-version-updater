from functools import cache

import github_action_utils as gha_utils  # type: ignore
import requests

from .run_git import git_diff


@cache
def get_request_headers(github_token: str | None = None) -> dict[str, str]:
    """Get headers for GitHub API request"""
    headers = {"Accept": "application/vnd.github.v3+json"}

    if github_token:
        headers.update({"authorization": f"Bearer {github_token}"})

    return headers


def create_pull_request(
    pull_request_title: str,
    repository_name: str,
    base_branch_name: str,
    head_branch_name: str,
    body: str,
    github_token: str | None = None,
) -> int | None:
    """Create pull request on GitHub"""
    with gha_utils.group("Create Pull Request"):
        url = f"https://api.github.com/repos/{repository_name}/pulls"
        payload = {
            "title": pull_request_title,
            "head": head_branch_name,
            "base": base_branch_name,
            "body": body,
        }

        response = requests.post(
            url, json=payload, headers=get_request_headers(github_token)
        )

        if response.status_code == 201:
            response_data = response.json()
            gha_utils.notice(
                f"Pull request opened at {response_data['html_url']} \U0001f389"
            )
            return response_data["number"]

        elif (
            response.status_code == 422
            and "A pull request already exists for" in response.text
        ):
            gha_utils.notice("A pull request already exists")
            return None

        gha_utils.error(
            f"Could not create a pull request on "
            f"{repository_name}, GitHub API Response: {response.json()}"
        )
        raise SystemExit(1)


def add_pull_request_reviewers(
    repository_name: str,
    pull_request_number: int,
    pull_request_user_reviewers: frozenset[str],
    pull_request_team_reviewers: frozenset[str],
    github_token: str | None = None,
) -> None:
    """Request reviewers for a pull request on GitHub"""
    with gha_utils.group(f"Request Reviewers for Pull Request #{pull_request_number}"):
        payload = {}

        if pull_request_user_reviewers:
            payload["reviewers"] = list(pull_request_user_reviewers)

        if pull_request_team_reviewers:
            payload["team_reviewers"] = list(pull_request_team_reviewers)

        if not payload:
            gha_utils.echo("No reviewers were requested.")
            return

        url = (
            f"https://api.github.com/repos/{repository_name}/pulls"
            f"/{pull_request_number}/requested_reviewers"
        )

        response = requests.post(
            url, json=payload, headers=get_request_headers(github_token)
        )

        if response.status_code == 201:
            gha_utils.notice(
                "Requested review from "
                f"{pull_request_user_reviewers.union(pull_request_team_reviewers)} "
                "\U0001f389"
            )
            return

        gha_utils.error(
            f"Could not request reviews on pull request #{pull_request_number} "
            f"on {repository_name}, GitHub API Response: {response.json()}"
        )


def add_pull_request_labels(
    repository_name: str,
    pull_request_number: int,
    labels: frozenset[str],
    github_token: str | None = None,
) -> None:
    """Request reviewers for a pull request on GitHub"""
    with gha_utils.group(f"Add Labels to Pull Request #{pull_request_number}"):
        if not labels:
            gha_utils.echo("No labels to add.")
            return

        payload = {"labels": list(labels)}

        url = (
            f"https://api.github.com/repos/{repository_name}/issues"
            f"/{pull_request_number}/labels"
        )

        response = requests.post(
            url, json=payload, headers=get_request_headers(github_token)
        )

        if response.status_code == 200:
            gha_utils.notice(
                f"Added '{labels}' labels to "
                f"pull request #{pull_request_number} \U0001f389"
            )
            return

        gha_utils.error(
            f"Could not add labels to pull request #{pull_request_number} "
            f"on {repository_name}, GitHub API Response: {response.json()}"
        )


def add_git_diff_to_job_summary() -> None:
    """Add git diff to job summary"""
    markdown_diff = (
        "<details>"
        "<summary>Git Diff</summary>"
        f"\n\n```diff\n{git_diff()}```\n\n"
        "</details>"
    )
    gha_utils.append_job_summary(markdown_diff)


def display_whats_new() -> None:
    """Print what's new in GitHub Actions Version Updater Latest Version"""
    url = (
        "https://api.github.com/repos"
        "/saadmk11/github-actions-version-updater"
        "/releases/latest"
    )
    response = requests.get(url)

    if response.status_code == 200:
        response_data = response.json()
        latest_release_tag = response_data["tag_name"]
        latest_release_html_url = response_data["html_url"]
        latest_release_body = response_data["body"]

        group_title = (
            "\U0001f389 What's New In "
            f"GitHub Actions Version Updater {latest_release_tag} \U0001f389"
        )

        with gha_utils.group(group_title):
            gha_utils.echo(latest_release_body)
            gha_utils.echo(
                f"\nGet More Information about '{latest_release_tag}' "
                f"Here: {latest_release_html_url}"
            )
            gha_utils.echo(
                "\nTo use these features please upgrade to "
                f"version '{latest_release_tag}' if you haven't already."
            )
            gha_utils.echo(
                "\nReport Bugs or Add Feature Requests Here: "
                "https://github.com/saadmk11/github-actions-version-updater/issues"
            )
