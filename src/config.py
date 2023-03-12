import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any

import github_action_utils as gha_utils  # type: ignore
from pydantic import BaseSettings, validator


class UpdateVersionWith(str, Enum):
    LATEST_RELEASE_TAG = "release-tag"
    LATEST_RELEASE_COMMIT_SHA = "release-commit-sha"
    DEFAULT_BRANCH_COMMIT_SHA = "default-branch-sha"


class ReleaseType(str, Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


class ActionEnvironment(BaseSettings):
    repository: str
    base_branch: str
    event_name: str
    workspace: str

    class Config:
        allow_mutation = False
        env_prefix = "GITHUB_"
        fields = {
            "base_branch": {
                "env": "GITHUB_REF",
            },
        }


class Configuration(BaseSettings):
    """Configuration class for GitHub Actions Version Updater"""

    token: str | None = None
    skip_pull_request: bool = False
    committer_username: str = "github-actions[bot]"
    committer_email: str = "github-actions[bot]@users.noreply.github.com"
    pull_request_title: str = "Update GitHub Action Versions"
    pull_request_branch: str | None = None
    commit_message: str = "Update GitHub Action Versions"
    ignore_actions: frozenset[str] = frozenset()
    update_version_with: UpdateVersionWith = UpdateVersionWith.LATEST_RELEASE_TAG
    pull_request_user_reviewers: frozenset[str] = frozenset()
    pull_request_team_reviewers: frozenset[str] = frozenset()
    pull_request_labels: frozenset[str] = frozenset()
    release_types: frozenset[ReleaseType] = frozenset(
        [
            ReleaseType.MAJOR,
            ReleaseType.MINOR,
            ReleaseType.PATCH,
        ]
    )
    extra_workflow_locations: frozenset[str] = frozenset()

    class Config:
        allow_mutation = False
        env_prefix = "INPUT_"
        fields = {
            "ignore_actions": {
                "env": "INPUT_IGNORE",
            },
        }

        @classmethod
        def parse_env_var(cls, field_name: str, raw_val: str):
            if field_name in [
                "ignore_actions",
                "pull_request_user_reviewers",
                "pull_request_team_reviewers",
                "pull_request_labels",
                "release_types",
                "extra_workflow_locations",
            ]:
                if raw_val.startswith("[") and raw_val.endswith("]"):
                    return frozenset(json.loads(raw_val))
                return frozenset(s.strip() for s in raw_val.strip().split(",") if s)
            return raw_val

    def get_pull_request_branch_name(self) -> tuple[bool, str]:
        """
        Get the pull request branch name.
        If the branch name is provided by the user frozenset the force push flag to True
        """
        if self.pull_request_branch is None:
            return (False, f"gh-actions-update-{int(time.time())}")
        return (True, self.pull_request_branch)

    @property
    def git_commit_author(self) -> str:
        """git_commit_author option"""
        return f"{self.committer_username} <{self.committer_email}>"

    @validator("release_types", pre=True)
    def check_release_types(cls, value: frozenset[str]) -> frozenset[str]:
        if value == {"all"}:
            return frozenset(["major", "minor", "patch"])

        return value

    @validator("extra_workflow_locations")
    def check_extra_workflow_locations(value: frozenset[str]) -> frozenset[str]:
        workflow_file_paths = []

        for workflow_location in value:
            if os.path.isdir(workflow_location):
                workflow_file_paths.extend(
                    [str(path) for path in Path(workflow_location).rglob("*.y*ml")]
                )
            elif os.path.isfile(workflow_location):
                if workflow_location.endswith(".yml") or workflow_location.endswith(
                    ".yaml"
                ):
                    workflow_file_paths.append(workflow_location)
            else:
                gha_utils.warning(
                    f"Skipping '{workflow_location}' "
                    "as it is not a valid file or directory"
                )

        return frozenset(workflow_file_paths)

    @validator("pull_request_branch")
    def check_pull_request_branch(value: Any) -> str | None:
        if isinstance(value, str):
            if value.lower() in ["main", "master"]:
                raise ValueError(
                    "Invalid input for `pull_request_branch` field, "
                    "the action does not support `main` or `master` branches"
                )
            return value
        return None
