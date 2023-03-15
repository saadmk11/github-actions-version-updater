import json
import os
import time
from enum import Enum
from pathlib import Path

import github_action_utils as gha_utils  # type: ignore
from pydantic import BaseSettings, Field, root_validator, validator


class UpdateVersionWith(str, Enum):
    LATEST_RELEASE_TAG = "release-tag"
    LATEST_RELEASE_COMMIT_SHA = "release-commit-sha"
    DEFAULT_BRANCH_COMMIT_SHA = "default-branch-sha"

    def __repr__(self):
        return self.value


class ReleaseType(str, Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"

    def __repr__(self):
        return self.value


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

    token: str
    pull_request_branch: str
    skip_pull_request: bool = False
    force_push: bool = False
    committer_username: str = "github-actions[bot]"
    committer_email: str = "github-actions[bot]@users.noreply.github.com"
    pull_request_title: str = "Update GitHub Action Versions"
    commit_message: str = "Update GitHub Action Versions"
    update_version_with: UpdateVersionWith = UpdateVersionWith.LATEST_RELEASE_TAG
    release_types: frozenset[ReleaseType] = frozenset(
        [
            ReleaseType.MAJOR,
            ReleaseType.MINOR,
            ReleaseType.PATCH,
        ]
    )
    ignore_actions: frozenset[str] = Field(default_factory=frozenset)
    pull_request_user_reviewers: frozenset[str] = Field(default_factory=frozenset)
    pull_request_team_reviewers: frozenset[str] = Field(default_factory=frozenset)
    pull_request_labels: frozenset[str] = Field(default_factory=frozenset)
    extra_workflow_locations: frozenset[str] = Field(default_factory=frozenset)

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

    @property
    def git_commit_author(self) -> str:
        """git_commit_author option"""
        return f"{self.committer_username} <{self.committer_email}>"

    @root_validator(pre=True)
    def validate_pull_request_branch(cls, values):
        if not values.get("pull_request_branch"):
            values["pull_request_branch"] = f"gh-actions-update-{int(time.time())}"
            values["force_push"] = False
        else:
            values["force_push"] = True
        return values

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
    def check_pull_request_branch(value: str) -> str:
        if value.lower() in ["main", "master"]:
            raise ValueError(
                "Invalid input for `pull_request_branch` field, "
                f"branch `{value}` can not be used as the pull request branch."
            )
        return value
