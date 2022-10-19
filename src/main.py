import os
import pprint
import time
from collections.abc import Generator
from functools import cache
from typing import Any

import github_action_utils as gha_utils  # type: ignore
import requests
import yaml
from pkg_resources import parse_version

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
    add_pull_request_reviewers,
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
        workflow_paths = self._get_workflow_paths()
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

            with open(workflow_path, "r+") as file, gha_utils.group(
                f'Checking "{workflow_path}" for updates'
            ):
                file_data = file.read()
                updated_workflow_data = file_data

                try:
                    workflow_data = yaml.load(file_data, Loader=yaml.FullLoader)
                except yaml.YAMLError as exc:
                    gha_utils.error(
                        f"Error while parsing YAML from '{workflow_path}' file. "
                        f"Reason: {exc}"
                    )
                    continue

                all_actions = set(self._get_all_actions(workflow_data))
                # Remove ignored actions
                all_actions.difference_update(ignore_actions)

                for action in all_actions:
                    try:
                        action_repository, current_version = action.split("@")
                    except ValueError:
                        gha_utils.warning(
                            f'Action "{action}" is in a wrong format, '
                            "We only support community actions currently"
                        )
                        continue

                    new_version, new_version_data = self._get_new_version(
                        action_repository
                    )

                    if not new_version:
                        gha_utils.warning(
                            f"Could not find any new version for {action}. Skipping..."
                        )
                        continue

                    updated_action = f"{action_repository}@{new_version}"

                    if action != updated_action:
                        gha_utils.echo(f'Found new version for "{action_repository}"')
                        pull_request_body_lines.add(
                            self._generate_pull_request_body_line(
                                action_repository, new_version_data
                            )
                        )
                        gha_utils.echo(
                            f'Updating "{action}" with "{updated_action}"...'
                        )
                        updated_workflow_data = updated_workflow_data.replace(
                            action, updated_action
                        )
                        workflow_updated = True
                    else:
                        gha_utils.echo(f'No updates found for "{action_repository}"')

                if workflow_updated:
                    file.seek(0)
                    file.write(updated_workflow_data)
                    file.truncate()

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
                pull_request_number = create_pull_request(
                    self.user_config.pull_request_title,
                    self.env.repository,
                    self.env.base_branch,
                    new_branch_name,
                    pull_request_body,
                    self.user_config.github_token,
                )
                add_pull_request_reviewers(
                    self.env.repository,
                    pull_request_number,
                    self.user_config.pull_request_user_reviewers,
                    self.user_config.pull_request_team_reviewers,
                    self.user_config.github_token,
                )
            else:
                add_git_diff_to_job_summary()
                gha_utils.error(
                    "Updates found but skipping pull request. "
                    "Checkout build summary for update details."
                )
                raise SystemExit(1)
        else:
            gha_utils.notice("Everything is up-to-date! \U0001F389 \U0001F389")

    def _generate_pull_request_body_line(
        self, action_repository: str, version_data: dict[str, str]
    ) -> str:
        """Generate pull request body line for pull request body"""
        start = f"* **[{action_repository}]({self.github_url}{action_repository})**"

        if self.user_config.update_version_with == LATEST_RELEASE_TAG:
            return (
                f"{start} published a new release "
                f"**[{version_data['tag_name']}]({version_data['html_url']})** "
                f"on {version_data['published_at']}\n"
            )
        elif self.user_config.update_version_with == LATEST_RELEASE_COMMIT_SHA:
            return (
                f"{start} added a new "
                f"**[commit]({version_data['commit_url']})** to "
                f"**[{version_data['tag_name']}]({version_data['html_url']})** Tag "
                f"on {version_data['commit_date']}\n"
            )
        else:
            return (
                f"{start} added a new "
                f"**[commit]({version_data['commit_url']})** to "
                f"**[{version_data['branch_name']}]({version_data['branch_url']})** "
                f"branch on {version_data['commit_date']}\n"
            )

    def _get_latest_version_release(self, action_repository: str) -> dict[str, str]:
        """Get the latest release using GitHub API"""
        url = f"{self.github_api_url}/repos/{action_repository}/releases?per_page=50"

        response = requests.get(
            url, headers=get_request_headers(self.user_config.github_token)
        )

        if response.status_code == 200:
            response_data = response.json()

            if response_data:
                # Sort through the releases (default 30 latest release) returned
                # by GitHub API and find the latest version release
                sorted_data = sorted(
                    response_data, key=lambda r: parse_version(r["tag_name"])
                )[-1]
                return {
                    "published_at": sorted_data["published_at"],
                    "html_url": sorted_data["html_url"],
                    "tag_name": sorted_data["tag_name"],
                }

        gha_utils.warning(
            f"Could not find any release for "
            f'"{action_repository}", status code: {response.status_code}'
        )
        return {}

    def _get_commit_data(
        self, action_repository: str, tag_or_branch_name: str
    ) -> dict[str, str]:
        """Get the commit Data for Tag or Branch using GitHub API"""
        url = (
            f"{self.github_api_url}/repos"
            f"/{action_repository}/commits?sha={tag_or_branch_name}"
        )

        response = requests.get(
            url, headers=get_request_headers(self.user_config.github_token)
        )

        if response.status_code == 200:
            response_data = response.json()[0]

            return {
                "commit_sha": response_data["sha"],
                "commit_url": response_data["html_url"],
                "commit_date": response_data["commit"]["author"]["date"],
            }

        gha_utils.warning(
            f"Could not find commit data for tag/branch {tag_or_branch_name} on "
            f'"{action_repository}", status code: {response.status_code}'
        )
        return {}

    def _get_default_branch_name(self, action_repository: str) -> str | None:
        """Get the Action Repository's Default Branch Name using GitHub API"""
        url = f"{self.github_api_url}/repos/{action_repository}"

        response = requests.get(
            url, headers=get_request_headers(self.user_config.github_token)
        )

        if response.status_code == 200:
            return response.json()["default_branch"]

        gha_utils.warning(
            f"Could not find default branch for "
            f'"{action_repository}", status code: {response.status_code}'
        )
        return None

    # flake8: noqa: B019
    @cache
    def _get_new_version(
        self, action_repository: str
    ) -> tuple[str | None, dict[str, str]]:
        """Get the new version for the action"""
        gha_utils.echo(f'Checking "{action_repository}" for updates...')

        if self.user_config.update_version_with == LATEST_RELEASE_TAG:
            latest_release_data = self._get_latest_version_release(action_repository)
            return latest_release_data.get("tag_name"), latest_release_data

        elif self.user_config.update_version_with == LATEST_RELEASE_COMMIT_SHA:
            latest_release_data = self._get_latest_version_release(action_repository)

            if not latest_release_data:
                return None, {}

            tag_commit_data = self._get_commit_data(
                action_repository, latest_release_data["tag_name"]
            )

            if not tag_commit_data:
                return None, {}

            return tag_commit_data["commit_sha"], {
                **latest_release_data,
                **tag_commit_data,
            }

        else:
            default_branch_name = self._get_default_branch_name(action_repository)

            if not default_branch_name:
                return None, {}

            branch_commit_data = self._get_commit_data(
                action_repository, default_branch_name
            )

            if not branch_commit_data:
                return None, {}

            return branch_commit_data["commit_sha"], {
                "branch_name": default_branch_name,
                "branch_url": (
                    f"{self.github_url}{action_repository}"
                    f"/tree/{default_branch_name}"
                ),
                **branch_commit_data,
            }

    def _get_workflow_paths(self) -> list[str]:
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

    def _get_all_actions(self, data: Any) -> Generator[str, None, None]:
        """Recursively get all action names from workflow data"""
        if isinstance(data, dict):
            for key, value in data.items():
                if key == self.workflow_action_key:
                    yield value
                elif isinstance(value, dict) or isinstance(value, list):
                    yield from self._get_all_actions(value)

        elif isinstance(data, list):
            for element in data:
                yield from self._get_all_actions(element)


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
