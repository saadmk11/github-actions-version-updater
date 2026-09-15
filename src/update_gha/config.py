"""Settings: CLI flags, then ``GHA_UPDATE_*`` env, then ``[tool.update-gha]``."""

import time
from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import AliasChoices, Field, TypeAdapter, ValidationError, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    PyprojectTomlConfigSettingsSource,
    SettingsConfigDict,
)

from update_gha.models import (
    OutputFormat,
    ReleaseType,
    UpdateVersionWith,
)

_STRING_LIST = TypeAdapter(list[str])
_DEFAULT_COMMITTER = "github-actions[bot]"
_DEFAULT_EMAIL = "github-actions[bot]@users.noreply.github.com"
_DEFAULT_MESSAGE = "Update GitHub Action Versions"
_FROZENSET_FIELDS = frozenset(
    {"ignore_actions", "release_types", "extra_workflow_locations"}
)
_TUPLE_FIELDS = frozenset({"user_reviewers", "team_reviewers", "labels"})


def split_csv(value: str) -> tuple[str, ...]:
    """Split a comma-separated string or a JSON string list."""
    if value.startswith("[") and value.endswith("]"):
        try:
            items = _STRING_LIST.validate_json(value)
        except ValidationError as exc:
            raise ValueError(
                "Expected a comma-separated value or JSON string list"
            ) from exc
        return tuple(item.strip() for item in items if item.strip())
    return tuple(part.strip() for part in value.split(",") if part.strip())


class CsvEnvSettingsSource(EnvSettingsSource):
    """Parse comma-separated or JSON-list env values into frozensets or tuples."""

    def prepare_field_value(
        self,
        field_name: str,
        field: FieldInfo,
        value: str | None,
        value_is_complex: bool,
    ) -> str | frozenset[str] | tuple[str, ...] | None:
        if field_name in _FROZENSET_FIELDS:
            return frozenset(split_csv(value)) if value else None
        if field_name in _TUPLE_FIELDS:
            return split_csv(value) if value else None
        return value


class NearestPyprojectSettingsSource(PyprojectTomlConfigSettingsSource):
    """Read ``[tool.update-gha]`` walking up from cwd."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls, toml_file=_find_pyproject(Path.cwd()))


def _find_pyproject(start: Path) -> Path | None:
    current = start.resolve()
    for directory in (current, *current.parents):
        if (candidate := directory / "pyproject.toml").is_file():
            return candidate
    return None


class Configuration(BaseSettings):
    """Scan settings plus optional pull-request settings."""

    model_config = SettingsConfigDict(
        frozen=True,
        extra="forbid",
        case_sensitive=False,
        env_prefix="GHA_UPDATE_",
        env_ignore_empty=True,
        pyproject_toml_table_header=("tool", "update-gha"),
    )

    token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("token", "GHA_UPDATE_TOKEN", "GITHUB_TOKEN"),
    )
    repository: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "repository", "GHA_UPDATE_REPOSITORY", "GITHUB_REPOSITORY"
        ),
    )
    ignore_actions: frozenset[str] = Field(default_factory=frozenset)
    update_version_with: UpdateVersionWith = UpdateVersionWith.LATEST_RELEASE_TAG
    release_types: frozenset[ReleaseType] = Field(
        default_factory=lambda: frozenset(ReleaseType)
    )
    extra_workflow_locations: frozenset[str] = Field(default_factory=frozenset)
    write: bool = True
    check: bool = False
    dry_run: bool = False
    show_diff: bool = False
    output_format: OutputFormat = OutputFormat.TEXT
    create_pull_request: bool = False
    committer_username: str = _DEFAULT_COMMITTER
    committer_email: str = _DEFAULT_EMAIL
    commit_message: str = _DEFAULT_MESSAGE
    pull_request_title: str = _DEFAULT_MESSAGE
    pull_request_branch: str = ""
    user_reviewers: tuple[str, ...] = Field(
        default=(),
        validation_alias=AliasChoices(
            "user_reviewers", "GHA_UPDATE_PULL_REQUEST_USER_REVIEWERS"
        ),
    )
    team_reviewers: tuple[str, ...] = Field(
        default=(),
        validation_alias=AliasChoices(
            "team_reviewers", "GHA_UPDATE_PULL_REQUEST_TEAM_REVIEWERS"
        ),
    )
    labels: tuple[str, ...] = Field(
        default=(),
        validation_alias=AliasChoices("labels", "GHA_UPDATE_PULL_REQUEST_LABELS"),
    )
    github_ref: str = Field(default="", validation_alias="GITHUB_REF")
    github_ref_name: str = Field(default="", validation_alias="GITHUB_REF_NAME")
    github_base_ref: str = Field(default="", validation_alias="GITHUB_BASE_REF")
    github_output: Path | None = Field(default=None, validation_alias="GITHUB_OUTPUT")

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
            CsvEnvSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
            NearestPyprojectSettingsSource(settings_cls),
        )

    @field_validator("release_types", mode="before")
    @classmethod
    def normalize_release_types(cls, value: object) -> frozenset[str]:
        if isinstance(value, str):
            parsed = split_csv(value)
        elif isinstance(value, (frozenset, set, list, tuple)) and all(
            isinstance(item, str) for item in value
        ):
            parsed = tuple(item.strip() for item in value if item.strip())
        else:
            raise ValueError(
                "release_types must be a comma-separated value or list of strings"
            )
        if frozenset(parsed) == frozenset({"all"}):
            return frozenset(item.value for item in ReleaseType)
        if not parsed:
            raise ValueError("release_types must contain at least one release type")
        return frozenset(parsed)

    @field_validator("ignore_actions", "extra_workflow_locations", mode="before")
    @classmethod
    def normalize_string_set(cls, value: object) -> frozenset[str]:
        if value is None or value == "":
            return frozenset()
        if isinstance(value, str):
            return frozenset(split_csv(value))
        if isinstance(value, (frozenset, set, list, tuple)) and all(
            isinstance(item, str) for item in value
        ):
            return frozenset(item.strip() for item in value if item.strip())
        raise ValueError("Expected a comma-separated value or list of strings")

    @field_validator("user_reviewers", "team_reviewers", "labels", mode="before")
    @classmethod
    def normalize_string_tuple(cls, value: object) -> tuple[str, ...]:
        if value is None or value == "":
            return ()
        if isinstance(value, str):
            return split_csv(value)
        if isinstance(value, (frozenset, set, list, tuple)):
            if all(isinstance(item, str) for item in value):
                return tuple(item.strip() for item in value if item.strip())
            raise ValueError("Expected a list of strings")
        raise ValueError("Expected a comma-separated value or list of strings")

    def should_write(self) -> bool:
        """True unless writing is off (``--check`` / ``--dry-run``)."""
        return self.write and not self.check and not self.dry_run

    @property
    def author(self) -> str:
        return f"{self.committer_username} <{self.committer_email}>"

    @property
    def base_branch(self) -> str:
        """PR base from GitHub refs, or ``main``."""
        if self.github_base_ref:
            return self.github_base_ref
        heads = "refs/heads/"
        if self.github_ref.startswith(heads):
            return self.github_ref.removeprefix(heads)
        if (
            not self.github_ref
            and self.github_ref_name
            and not self.github_ref_name.endswith("/merge")
        ):
            return self.github_ref_name
        return "main"

    def resolve_head(self) -> tuple[str, bool]:
        """Return ``(branch, force_push)`` for the pull-request head."""
        match self.pull_request_branch.strip().lower():
            case "":
                return f"gh-actions-update-{time.time_ns()}", False
            case "main" | "master" as branch:
                raise ValueError(
                    f"Invalid pull_request_branch: `{branch}` cannot be "
                    "used as the pull request branch."
                )
            case _:
                return self.pull_request_branch.strip(), True


def configuration_from_cli(
    *,
    token: str | None = None,
    repository: str | None = None,
    ignore: str | None = None,
    update_version_with: UpdateVersionWith | None = None,
    release_types: str | None = None,
    extra_locations: Iterable[str] | None = None,
    paths: Sequence[Path] = (),
    check: bool = False,
    dry_run: bool = False,
    show_diff: bool = False,
    output_format: OutputFormat | None = None,
    create_pull_request: bool | None = None,
    committer_username: str | None = None,
    committer_email: str | None = None,
    commit_message: str | None = None,
    pull_request_title: str | None = None,
    pull_request_branch: str | None = None,
    user_reviewers: str | None = None,
    team_reviewers: str | None = None,
    labels: str | None = None,
) -> Configuration:
    """Apply only the CLI values that were actually passed."""
    data: dict[str, object] = {
        key: value
        for key, value in {
            "token": token,
            "repository": repository,
            "ignore_actions": ignore,
            "update_version_with": update_version_with,
            "release_types": release_types,
            "output_format": output_format,
            "committer_username": committer_username,
            "committer_email": committer_email,
            "commit_message": commit_message,
            "pull_request_title": pull_request_title,
            "pull_request_branch": pull_request_branch,
            "user_reviewers": user_reviewers,
            "team_reviewers": team_reviewers,
            "labels": labels,
        }.items()
        if value is not None
    }
    if extra_locations is not None:
        data["extra_workflow_locations"] = frozenset(extra_locations)
    if check:
        data["check"] = True
        data["write"] = False
    if dry_run:
        data["dry_run"] = True
        data["write"] = False
    if show_diff:
        data["show_diff"] = True
    if create_pull_request is not None:
        data["create_pull_request"] = create_pull_request

    config = Configuration.model_validate(data)
    if extra_paths := {str(path) for path in paths}:
        config = config.model_copy(
            update={
                "extra_workflow_locations": config.extra_workflow_locations
                | extra_paths
            }
        )
    return config
