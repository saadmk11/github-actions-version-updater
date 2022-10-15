import os
import pprint
import time
from collections.abc import Generator
from typing import Any

import github_action_utils as gha_utils  # type: ignore
import requests
import yaml

from .config import (
    LATEST_RELEASE_COMMIT_SHA,
    LATEST_RELEASE_TAG,
    ActionEnvironment,
    Configuration,
)
from .run_git import (
    configure_git_author,
    create_new_git_branch,
    git_commit_changes,
    git_has_changes,
)
from .utils import (
    add_git_diff_to_job_summary,
    create_pull_request,
    display_whats_new,
    get_request_headers,
)


class GitHubActionsVersionUpdater:
    """Check for GitHub Action updates"""

    github_api_url = "https://api.github.com"
    github_url = "https://github.com/"
    workflow_action_key = "uses"

    def __init__(self, env: ActionEnvironment, user_config: Configuration):
        self.env = env
        self.user_config = user_config

    def run(self) -> None:
        """Entrypoint to the GitHub Action"""
        workflow_paths = self.get_workflow_paths()
        pull_request_body_lines = set()

        if not workflow_paths:
            gha_utils.warning(
                f'No Workflow found in "{self.env.repository}". '
                "Skipping GitHub Actions Version Update"
            )
            raise SystemExit(0)

        ignore_actions = self.user_config.ignore_actions

        if ignore_actions:
            gha_utils.echo(f'Actions "{ignore_actions}" will be skipped')

        for workflow_path in workflow_paths:
            workflow_updated = False

            try:
                with open(workflow_path, "r+") as file, gha_utils.group(
                    f'Checking "{workflow_path}" for updates'
                ):
                    file_data = file.read()
                    updated_workflow_data = file_data

                    data = yaml.load(file_data, Loader=yaml.FullLoader)
                    all_action_set = set(self.get_all_actions(data))
                    # Remove ignored actions
                    all_action_set.difference_update(ignore_actions)

                    for action in all_action_set:
                        try:
                            action_repository, current_version = action.split("@")
                        except ValueError:
                            gha_utils.warning(
                                f'Action "{action}" is in a wrong format, '
                                "We only support community actions currently"
                            )
                            continue

                        new_version, new_version_data = self.get_version(
                            action_repository, current_version
                        )

                        if not new_version:
                            continue

                        updated_action = f"{action_repository}@{new_version}"

                        if action != updated_action:
                            gha_utils.echo(
                                f'Found new version for "{action_repository}"'
                            )
                            pull_request_body_lines.add(
                                self.generate_pull_request_body_line(
                                    action_repository, new_version_data
                                )
                            )
                            gha_utils.echo(
                                f'Updating "{action}" with "{updated_action}"'
                            )
                            updated_workflow_data = updated_workflow_data.replace(
                                action, updated_action
                            )
                            workflow_updated = True
                        else:
                            gha_utils.echo(
                                f'No updates found for "{action_repository}"'
                            )

                    if workflow_updated:
                        file.seek(0)
                        file.write(updated_workflow_data)
                        file.truncate()
            except Exception:
                gha_utils.echo(f'Skipping "{workflow_path}"')

        if git_has_changes():
            # Use timestamp to ensure uniqueness of the new branch
            pull_request_body = "### GitHub Actions Version Updates\n" + "".join(
                pull_request_body_lines
            )
            gha_utils.append_job_summary(pull_request_body)

            if not self.user_config.skip_pull_request:
                new_branch_name = f"gh-actions-update-{int(time.time())}"
                create_new_git_branch(self.env.base_branch, new_branch_name)
                git_commit_changes(
                    self.user_config.commit_message,
                    self.user_config.git_commit_author,
                    new_branch_name,
                )
                create_pull_request(
                    self.user_config.pull_request_title,
                    self.env.repository,
                    self.env.base_branch,
                    new_branch_name,
                    pull_request_body,
                    self.user_config.github_token,
                )
            else:
                add_git_diff_to_job_summary()
                gha_utils.error(
                    "Updates found but skipping pull request. "
                    "Checkout build summary for details."
                )
                raise SystemExit(1)
        else:
            gha_utils.notice("Everything is up-to-date! \U0001F389 \U0001F389")

    def generate_pull_request_body_line(
        self, action_repository: str, version_data: dict[str, str]
    ) -> str:
        """Generate pull request body line for pull request body"""
        start = f"* **[{action_repository}]({self.github_url + action_repository})**"

        if self.user_config.version_from == LATEST_RELEASE_TAG:
            return (
                f"{start} published a new release "
                f"[{version_data['tag_name']}]({version_data['html_url']}) "
                f"on {version_data['published_at']}\n"
            )
        elif self.user_config.version_from == LATEST_RELEASE_COMMIT_SHA:
            return (
                f"{start} added a new "
                f"[commit]({version_data['commit_url']}) to "
                f"[{version_data['tag_name']}]({version_data['html_url']}) "
                f"on {version_data['published_at']}\n"
            )
        else:
            return (
                f"{start} added a new "
                f"([commit]({version_data['commit_url']})) to "
                f"[{version_data['branch_name']}]({version_data['branch_url']}) "
                f"on {version_data['commit_date']}\n"
            )

    def get_latest_release(self, action_repository: str) -> dict[str, str]:
        """Get the latest release using GitHub API"""
        url = f"{self.github_api_url}/repos/{action_repository}/releases/latest"

        response = requests.get(
            url, headers=get_request_headers(self.user_config.github_token)
        )
        data = {}

        if response.status_code == 200:
            response_data = response.json()

            data = {
                "published_at": response_data["published_at"],
                "html_url": response_data["html_url"],
                "tag_name": response_data["tag_name"],
                "body": response_data["body"],
            }
        else:
            # if there is no previous release API will return 404 Not Found
            gha_utils.warning(
                f"Could not find any release for "
                f'"{action_repository}", status code: {response.status_code}'
            )

        return data

    def get_tag_commit(
        self, action_repository: str, tag_name: str
    ) -> dict[str, str] | None:
        """Get the commit SHA for a Tag using GitHub API"""
        url = (
            f"{self.github_api_url}/repos/{action_repository}/git/refs/tags/{tag_name}"
        )

        response = requests.get(
            url, headers=get_request_headers(self.user_config.github_token)
        )

        if response.status_code == 200:
            return response.json()["object"]
        else:
            gha_utils.warning(
                f"Could not find tag {tag_name} for "
                f'"{action_repository}", status code: {response.status_code}'
            )

        return None

    def get_default_branch_name(self, action_repository: str) -> str | None:
        """Get the Action Repository's Default Branch Name using GitHub API"""
        url = f"{self.github_api_url}/repos/{action_repository}"

        response = requests.get(
            url, headers=get_request_headers(self.user_config.github_token)
        )

        if response.status_code == 200:
            return response.json()["default_branch"]
        else:
            gha_utils.warning(
                f"Could not find default branch for "
                f'"{action_repository}", status code: {response.status_code}'
            )

        return None

    def get_branch_data(
        self, action_repository: str, default_branch_name: str
    ) -> dict[str, Any] | None:
        """Get the Action Repository's Default Branch Commit SHA using GitHub API"""
        url = (
            f"{self.github_api_url}/repos/{action_repository}"
            f"/branches/{default_branch_name}"
        )

        response = requests.get(
            url, headers=get_request_headers(self.user_config.github_token)
        )

        if response.status_code == 200:
            return response.json()
        else:
            gha_utils.warning(
                f"Could not find default branch commit SHA for "
                f'"{action_repository}", status code: {response.status_code}'
            )

        return None

    def get_version(
        self, action_repository: str, current_version: str
    ) -> tuple[str | None, dict]:
        """Get the latest version for the action"""
        if self.user_config.version_from == LATEST_RELEASE_TAG:
            version_data = self.get_latest_release(action_repository)

            return version_data.get("tag_name"), version_data

        elif self.user_config.version_from == LATEST_RELEASE_COMMIT_SHA:
            version_data = self.get_latest_release(action_repository)

            if not version_data:
                return None, version_data

            tag_commit = self.get_tag_commit(
                action_repository, version_data["tag_name"]
            )

            if not tag_commit:
                return None, version_data

            tag_commit_sha = tag_commit["sha"]
            version_data.update(
                {
                    "commit_sha": tag_commit_sha,
                    "commit_url": (
                        f"{self.github_url + action_repository}"
                        f"/commit/{tag_commit_sha}"
                    ),
                }
            )

            return tag_commit_sha, version_data
        else:
            version_data = {}
            default_branch_name = self.get_default_branch_name(action_repository)

            if not default_branch_name:
                return None, version_data

            branch_data = self.get_branch_data(action_repository, default_branch_name)

            if not branch_data:
                return None, version_data

            default_branch_commit_sha = branch_data["commit"]["sha"]

            version_data.update(
                {
                    "commit_sha": default_branch_commit_sha,
                    "commit_url": branch_data["commit"]["html_url"],
                    "branch_name": default_branch_name,
                    "branch_url": branch_data["_links"]["html"],
                    "commit_date": branch_data["commit"]["commit"]["author"]["date"],
                }
            )

            return (
                default_branch_commit_sha,
                version_data,
            )

    def get_workflow_paths(self) -> list[str]:
        """Get all workflows of the repository using GitHub API"""
        url = f"{self.github_api_url}/repos/{self.env.repository}/actions/workflows"

        response = requests.get(
            url, headers=get_request_headers(self.user_config.github_token)
        )

        if response.status_code == 200:
            return [workflow["path"] for workflow in response.json()["workflows"]]

        gha_utils.error(
            f"An error occurred while getting workflows for"
            f"{self.env.repository}, status code: {response.status_code}"
        )
        raise SystemExit(1)

    def get_all_actions(self, data: Any) -> Generator[str, None, None]:
        """Recursively get all action names from workflow data"""
        if isinstance(data, dict):
            for key, value in data.items():
                if key == self.workflow_action_key:
                    yield value
                elif isinstance(value, dict) or isinstance(value, list):
                    yield from self.get_all_actions(value)

        elif isinstance(data, list):
            for element in data:
                yield from self.get_all_actions(element)


if __name__ == "__main__":
    with gha_utils.group("Parse Configuration"):
        user_configuration = Configuration.create(os.environ)
        action_environment = ActionEnvironment.from_env(os.environ)

        gha_utils.echo("Using Configuration:")
        gha_utils.echo(pprint.pformat(user_configuration._asdict()))

    # Configure Git Author
    configure_git_author(
        user_configuration.git_committer_username,
        user_configuration.git_committer_email,
    )

    with gha_utils.group("Run GitHub Actions Version Updater"):
        actions_version_updater = GitHubActionsVersionUpdater(
            action_environment,
            user_configuration,
        )
        actions_version_updater.run()

    display_whats_new()
