import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NamedTuple

import github_action_utils as gha_utils  # type: ignore

LATEST_RELEASE_TAG = "release-tag"
LATEST_RELEASE_COMMIT_SHA = "release-commit-sha"
DEFAULT_BRANCH_COMMIT_SHA = "default-branch-sha"

UPDATE_VERSION_WITH_LIST = [
    LATEST_RELEASE_TAG,
    LATEST_RELEASE_COMMIT_SHA,
    DEFAULT_BRANCH_COMMIT_SHA,
]

MAJOR_RELEASE = "major"
MINOR_RELEASE = "minor"
PATCH_RELEASE = "patch"

ALL_RELEASE_TYPES = [MAJOR_RELEASE, MINOR_RELEASE, PATCH_RELEASE]


class ActionEnvironment(NamedTuple):
    repository: str
    base_branch: str
    event_name: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ActionEnvironment":
        return cls(
            repository=env["GITHUB_REPOSITORY"],
            base_branch=env["GITHUB_REF"],
            event_name=env["GITHUB_EVENT_NAME"],
        )


class Configuration(NamedTuple):
    """Configuration class for GitHub Actions Version Updater"""

    github_token: str | None = None
    skip_pull_request: bool = False
    git_committer_username: str = "github-actions[bot]"
    git_committer_email: str = "github-actions[bot]@users.noreply.github.com"
    pull_request_title: str = "Update GitHub Action Versions"
    commit_message: str = "Update GitHub Action Versions"
    ignore_actions: set[str] = set()
    update_version_with: str = LATEST_RELEASE_TAG
    pull_request_user_reviewers: set[str] = set()
    pull_request_team_reviewers: set[str] = set()
    release_types: list[str] = ALL_RELEASE_TYPES
    extra_workflow_paths: set[str] = set()

    @property
    def git_commit_author(self) -> str:
        """git_commit_author option"""
        return f"{self.git_committer_username} <{self.git_committer_email}>"

    @classmethod
    def create(cls, env: Mapping[str, str | None]) -> "Configuration":
        """
        Create a Configuration object from environment variables
        """
        cleaned_user_config: dict[str, Any] = cls.clean_user_config(
            cls.get_user_config(env)
        )
        return cls(**cleaned_user_config)

    @classmethod
    def get_user_config(cls, env: Mapping[str, str | None]) -> dict[str, str | None]:
        """
        Read user provided input and return user configuration
        """
        user_config: dict[str, str | None] = {
            "github_token": env.get("INPUT_TOKEN"),
            "skip_pull_request": env.get("INPUT_SKIP_PULL_REQUEST"),
            "git_committer_username": env.get("INPUT_COMMITTER_USERNAME"),
            "git_committer_email": env.get("INPUT_COMMITTER_EMAIL"),
            "pull_request_title": env.get("INPUT_PULL_REQUEST_TITLE"),
            "commit_message": env.get("INPUT_COMMIT_MESSAGE"),
            "ignore_actions": env.get("INPUT_IGNORE"),
            "update_version_with": env.get("INPUT_UPDATE_VERSION_WITH"),
            "release_types": env.get("INPUT_RELEASE_TYPES"),
            "pull_request_user_reviewers": env.get("INPUT_PULL_REQUEST_USER_REVIEWERS"),
            "pull_request_team_reviewers": env.get("INPUT_PULL_REQUEST_TEAM_REVIEWERS"),
            "extra_workflow_paths": env.get("INPUT_EXTRA_WORKFLOW_LOCATIONS"),
        }
        return user_config

    @classmethod
    def clean_user_config(cls, user_config: dict[str, str | None]) -> dict[str, Any]:
        cleaned_user_config: dict[str, Any] = {}

        for key, value in user_config.items():
            if key in cls._fields:
                cleaned_value = getattr(cls, f"clean_{key.lower()}", lambda x: x)(value)

                if cleaned_value is not None:
                    cleaned_user_config[key] = cleaned_value

        return cleaned_user_config

    @staticmethod
    def clean_ignore_actions(value: Any) -> set[str] | None:
        if isinstance(value, str) and value.startswith("[") and value.endswith("]"):
            ignore_actions = json.loads(value)

            if isinstance(ignore_actions, list) and all(
                isinstance(item, str) for item in ignore_actions
            ):
                return set(ignore_actions)
            else:
                gha_utils.error(
                    "Invalid input for `ignore` field, "
                    f"expected JSON array of strings but got `{value}`"
                )
                raise SystemExit(1)
        elif value and isinstance(value, str):
            return {s.strip() for s in value.strip().split(",") if s}
        else:
            return None

    @staticmethod
    def clean_pull_request_user_reviewers(value: Any) -> set[str] | None:
        if value and isinstance(value, str):
            return {s.strip() for s in value.strip().split(",") if s}
        return None

    @staticmethod
    def clean_pull_request_team_reviewers(value: Any) -> set[str] | None:
        if value and isinstance(value, str):
            return {s.strip() for s in value.strip().split(",") if s}
        return None

    @staticmethod
    def clean_release_types(value: Any) -> list[str] | None:
        if value and isinstance(value, str):
            values = [s.strip() for s in value.lower().strip().split(",") if s]
            if values == ["all"]:
                return ALL_RELEASE_TYPES
            elif all(i in ALL_RELEASE_TYPES for i in values):
                return values
            else:
                gha_utils.error(
                    "Invalid input for `release_types` field, "
                    f"expected one/all of {ALL_RELEASE_TYPES} but got `{value}`"
                )
                raise SystemExit(1)
        return None

    @staticmethod
    def clean_skip_pull_request(value: Any) -> bool | None:
        if value in [1, "1", True, "true", "True"]:
            return True
        return None

    @staticmethod
    def clean_update_version_with(value: Any) -> str | None:
        if value and value not in UPDATE_VERSION_WITH_LIST:
            gha_utils.error(
                "Invalid input for `update_version_with` field, "
                f"expected one of {UPDATE_VERSION_WITH_LIST} but got `{value}`"
            )
            raise SystemExit(1)
        elif value:
            return value
        else:
            return None

    @staticmethod
    def clean_extra_workflow_paths(value: Any) -> set[str] | None:
        if not value or not isinstance(value, str):
            return None

        workflow_locations = {s.strip() for s in value.strip().split(",") if s}
        workflow_files = set()

        for workflow_location in workflow_locations:
            if os.path.isdir(workflow_location):
                workflow_files.update(
                    {str(path) for path in Path(workflow_location).rglob("*.y*ml")}
                )
            elif os.path.isfile(workflow_location):
                if workflow_location.endswith(".yml") or workflow_location.endswith(
                    ".yaml"
                ):
                    workflow_files.add(workflow_location)
            else:
                gha_utils.warning(
                    f"Skipping '{workflow_location}' "
                    "as it is not a valid file or directory"
                )

        return workflow_files
