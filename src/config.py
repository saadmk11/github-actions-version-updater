import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any

import github_action_utils as gha_utils  # type: ignore
from pydantic import Field, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


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


class CustomEnvSettingsSource(EnvSettingsSource):
    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        if value and field_name in [
            "ignore_actions",
            "pull_request_user_reviewers",
            "pull_request_team_reviewers",
            "pull_request_labels",
            "release_types",
            "extra_workflow_locations",
        ]:
            if value.startswith("[") and value.endswith("]"):
                return frozenset(json.loads(value))
            return frozenset(s.strip() for s in value.strip().split(",") if s)

        return value


class ActionEnvironment(BaseSettings):
    repository: str
    base_branch: str = Field(alias="GITHUB_REF")
    event_name: str
    workspace: str

    model_config = SettingsConfigDict(
        case_sensitive=False, frozen=True, env_prefix="GITHUB_"
    )


class Configuration(BaseSettings):
    """Configuration class for GitHub Actions Version Updater"""

    token: str = Field(min_length=10)
    pull_request_branch: str = Field(min_length=1)
    skip_pull_request: bool = False
    force_push: bool = False
    committer_username: str = Field(min_length=1, default="github-actions[bot]")
    committer_email: str = Field(
        min_length=5, default="github-actions[bot]@users.noreply.github.com"
    )
    pull_request_title: str = Field(
        min_length=1, default="Update GitHub Action Versions"
    )
    commit_message: str = Field(min_length=1, default="Update GitHub Action Versions")
    update_version_with: UpdateVersionWith = UpdateVersionWith.LATEST_RELEASE_TAG
    release_types: frozenset[ReleaseType] = frozenset(
        [
            ReleaseType.MAJOR,
            ReleaseType.MINOR,
            ReleaseType.PATCH,
        ]
    )
    ignore_actions: frozenset[str] = Field(
        default_factory=frozenset, alias="INPUT_IGNORE"
    )
    pull_request_user_reviewers: frozenset[str] = Field(default_factory=frozenset)
    pull_request_team_reviewers: frozenset[str] = Field(default_factory=frozenset)
    pull_request_labels: frozenset[str] = Field(default_factory=frozenset)
    extra_workflow_locations: frozenset[str] = Field(default_factory=frozenset)
    model_config = SettingsConfigDict(
        case_sensitive=False, frozen=True, env_prefix="INPUT_"
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            CustomEnvSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    @property
    def git_commit_author(self) -> str:
        """git_commit_author option"""
        return f"{self.committer_username} <{self.committer_email}>"

    @model_validator(mode="before")
    @classmethod
    def validate_pull_request_branch(cls, values: Any) -> Any:
        if not values.get("pull_request_branch"):
            values["pull_request_branch"] = f"gh-actions-update-{int(time.time())}"
            values["force_push"] = False
        else:
            values["force_push"] = True
        return values

    @field_validator("release_types", mode="before")
    @classmethod
    def check_release_types(cls, value: frozenset[str]) -> frozenset[str]:
        if value == {"all"}:
            return frozenset(
                [
                    ReleaseType.MAJOR,
                    ReleaseType.MINOR,
                    ReleaseType.PATCH,
                ]
            )

        return value

    @field_validator("extra_workflow_locations")
    @classmethod
    def check_extra_workflow_locations(cls, value: frozenset[str]) -> frozenset[str]:
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

    @field_validator("pull_request_branch")
    @classmethod
    def check_pull_request_branch(cls, value: str) -> str:
        if value.lower() in ["main", "master"]:
            raise ValueError(
                "Invalid input for `pull_request_branch` field, "
                f"branch `{value}` can not be used as the pull request branch."
            )
        return value
