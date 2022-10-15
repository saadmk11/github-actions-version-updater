from functools import lru_cache

import github_action_utils as gha_utils  # type: ignore
import requests

from .run_git import git_diff


@lru_cache
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
) -> None:
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
            html_url = response.json()["html_url"]
            gha_utils.notice(f"Pull request opened at {html_url} \U0001F389")
        else:
            gha_utils.error(
                f"Could not create a pull request on "
                f"{repository_name}, status code: {response.status_code}"
            )
            raise SystemExit(1)


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
            "\U0001F389 What's New In "
            f"GitHub Actions Version Updater {latest_release_tag} \U0001F389"
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
