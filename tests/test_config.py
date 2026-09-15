"""Configuration precedence: CLI > env > pyproject.toml > defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from update_gha.config import (
    Configuration,
    _find_pyproject,
    configuration_from_cli,
    split_csv,
)
from update_gha.models import (
    OutputFormat,
    ReleaseType,
    UpdateVersionWith,
)


def test_defaults() -> None:
    config = Configuration(token=None, repository=None)
    assert config.update_version_with is UpdateVersionWith.LATEST_RELEASE_TAG
    assert config.release_types == {
        ReleaseType.MAJOR,
        ReleaseType.MINOR,
        ReleaseType.PATCH,
    }
    assert config.ignore_actions == frozenset()
    assert config.should_write() is True


def test_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "GHA_UPDATE_IGNORE_ACTIONS", "actions/checkout@v2, actions/cache@v3"
    )
    monkeypatch.setenv("GHA_UPDATE_UPDATE_VERSION_WITH", "release-commit-sha")
    monkeypatch.setenv("GHA_UPDATE_RELEASE_TYPES", "minor, patch")
    config = Configuration()
    assert config.ignore_actions == frozenset(
        {"actions/checkout@v2", "actions/cache@v3"}
    )
    assert config.update_version_with is UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA
    assert config.release_types == {ReleaseType.MINOR, ReleaseType.PATCH}


def test_github_token_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_abcdefghij")
    config = Configuration()
    assert config.token == "ghs_abcdefghij"


def test_cli_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GHA_UPDATE_IGNORE_ACTIONS", "actions/checkout@v2")
    monkeypatch.setenv("GHA_UPDATE_UPDATE_VERSION_WITH", "release-tag")
    config = configuration_from_cli(
        ignore="actions/setup-python@v4",
        update_version_with=UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA,
        release_types="major",
        check=True,
    )
    assert config.ignore_actions == frozenset({"actions/setup-python@v4"})
    assert config.update_version_with is UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA
    assert config.release_types == {ReleaseType.MAJOR}
    assert config.should_write() is False


def test_omitted_cli_values_keep_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GHA_UPDATE_IGNORE_ACTIONS", "actions/checkout@v2")
    monkeypatch.setenv("GHA_UPDATE_UPDATE_VERSION_WITH", "release-commit-sha")
    monkeypatch.setenv("GHA_UPDATE_RELEASE_TYPES", "major")
    monkeypatch.setenv("GHA_UPDATE_EXTRA_WORKFLOW_LOCATIONS", "extra.yml")
    config = configuration_from_cli()
    assert config.ignore_actions == frozenset({"actions/checkout@v2"})
    assert config.update_version_with is UpdateVersionWith.LATEST_RELEASE_COMMIT_SHA
    assert config.release_types == {ReleaseType.MAJOR}
    assert config.extra_workflow_locations == frozenset({"extra.yml"})


def test_explicit_empty_extra_locations_override_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GHA_UPDATE_EXTRA_WORKFLOW_LOCATIONS", "extra.yml")
    config = configuration_from_cli(extra_locations=())
    assert config.extra_workflow_locations == frozenset()


def test_pyproject_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.update-gha]
ignore_actions = ["actions/checkout@v2"]
update_version_with = "default-branch-sha"
release_types = ["patch"]
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    config = Configuration()
    assert config.ignore_actions == frozenset({"actions/checkout@v2"})
    assert config.update_version_with is UpdateVersionWith.DEFAULT_BRANCH_COMMIT_SHA
    assert config.release_types == {ReleaseType.PATCH}


def test_release_types_all() -> None:
    config = Configuration.model_validate({"release_types": "all"})
    assert config.release_types == {
        ReleaseType.MAJOR,
        ReleaseType.MINOR,
        ReleaseType.PATCH,
    }


def test_split_csv_json_array() -> None:
    assert split_csv('["a", "b"]') == ("a", "b")


def test_split_csv_invalid_json_list() -> None:
    with pytest.raises(ValueError, match="JSON string list"):
        split_csv("[not-json]")
    with pytest.raises(ValueError, match="JSON string list"):
        split_csv("[1, 2]")


def test_release_types_cannot_be_empty() -> None:
    with pytest.raises(ValueError, match="at least one"):
        Configuration.model_validate({"release_types": ""})


def test_collection_settings_reject_invalid_types_and_trim_lists() -> None:
    assert (
        Configuration.model_validate({"ignore_actions": None}).ignore_actions == set()
    )
    with pytest.raises(ValueError, match="release_types"):
        Configuration.model_validate({"release_types": 1})
    with pytest.raises(ValueError, match="list of strings"):
        Configuration.model_validate({"ignore_actions": [1]})
    with pytest.raises(ValueError, match="list of strings"):
        Configuration.model_validate({"labels": [1]})
    config = Configuration.model_validate(
        {
            "release_types": [" minor ", ""],
            "ignore_actions": [" actions/checkout@v4 ", ""],
            "labels": {" dependencies ", ""},
        }
    )
    assert config.release_types == {ReleaseType.MINOR}
    assert config.ignore_actions == {"actions/checkout@v4"}
    assert config.labels == ("dependencies",)


def test_unknown_configuration_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="extra_forbidden"):
        Configuration.model_validate({"release_type": "major"})


def test_configuration_from_cli_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert configuration_from_cli(token="t", repository="o/r").token == "t"
    cfg = configuration_from_cli(
        extra_locations=("one.yml",),
        paths=[tmp_path / "two.yml"],
        check=True,
        dry_run=True,
        show_diff=True,
        output_format=OutputFormat.JSON,
    )
    assert cfg.check is True
    assert cfg.dry_run is True
    assert cfg.should_write() is False
    assert cfg.show_diff is True
    assert cfg.output_format is OutputFormat.JSON
    assert cfg.extra_workflow_locations == frozenset(
        {"one.yml", str(tmp_path / "two.yml")}
    )


def test_pull_request_fields_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GHA_UPDATE_CREATE_PULL_REQUEST", "true")
    monkeypatch.setenv("GHA_UPDATE_COMMITTER_USERNAME", "bot")
    monkeypatch.setenv("GHA_UPDATE_PULL_REQUEST_USER_REVIEWERS", "ada, linus")
    config = Configuration()
    assert config.create_pull_request is True
    assert config.committer_username == "bot"
    assert config.user_reviewers == ("ada", "linus")


@pytest.mark.parametrize(
    ("env_value", "flag", "expected"),
    [
        ("false", True, True),
        ("true", False, False),
    ],
)
def test_cli_pull_request_flag_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str,
    flag: bool,
    expected: bool,
) -> None:
    monkeypatch.setenv("GHA_UPDATE_CREATE_PULL_REQUEST", env_value)
    assert (
        configuration_from_cli(create_pull_request=flag).create_pull_request is expected
    )


def test_omitted_format_keeps_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GHA_UPDATE_OUTPUT_FORMAT", "json")
    config = configuration_from_cli()
    assert config.output_format is OutputFormat.JSON


def test_configuration_from_cli_pull_request_fields() -> None:
    config = configuration_from_cli(
        create_pull_request=True,
        committer_username="bot",
        committer_email="bot@x",
        commit_message="msg",
        pull_request_title="title",
        pull_request_branch="updates",
        user_reviewers="ada",
        team_reviewers="core",
        labels="deps",
    )
    assert config.committer_username == "bot"
    assert config.committer_email == "bot@x"
    assert config.commit_message == "msg"
    assert config.pull_request_title == "title"
    assert config.pull_request_branch == "updates"
    assert config.user_reviewers == ("ada",)
    assert config.team_reviewers == ("core",)
    assert config.labels == ("deps",)


def test_author_property() -> None:
    config = Configuration.model_validate(
        {"committer_username": "bot", "committer_email": "bot@x"}
    )
    assert config.author == "bot <bot@x>"


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"github_ref": "refs/heads/develop"}, "develop"),
        ({"github_base_ref": "target"}, "target"),
        (
            {
                "github_ref": "refs/pull/1/merge",
                "github_ref_name": "1/merge",
                "github_base_ref": "feature",
            },
            "feature",
        ),
        ({"github_ref": "refs/pull/1/merge", "github_ref_name": ""}, "main"),
        ({"github_ref": "refs/tags/v1.0.0"}, "main"),
        ({"github_ref": "", "github_ref_name": "pr/merge"}, "main"),
    ],
)
def test_base_branch(fields: dict[str, str], expected: str) -> None:
    assert Configuration.model_validate(fields).base_branch == expected


def test_resolve_head() -> None:
    name, force = Configuration.model_validate({}).resolve_head()
    assert name.startswith("gh-actions-update-")
    assert force is False
    name, force = Configuration.model_validate(
        {"pull_request_branch": "actions-update"}
    ).resolve_head()
    assert name == "actions-update" and force is True
    with pytest.raises(ValueError, match="main"):
        Configuration.model_validate({"pull_request_branch": "main"}).resolve_head()


def test_reviewer_tuple_from_list_or_junk() -> None:
    assert Configuration.model_validate(
        {"user_reviewers": ["a", "b"]}
    ).user_reviewers == ("a", "b")
    with pytest.raises(ValueError, match="comma-separated"):
        Configuration.model_validate({"user_reviewers": 1})
    with pytest.raises(ValueError, match="list of strings"):
        Configuration.model_validate({"user_reviewers": [1]})


def test_find_pyproject_walks_parents(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'x'\n", encoding="utf-8"
    )
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert _find_pyproject(nested) == tmp_path / "pyproject.toml"


def test_find_pyproject_returns_none_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.is_file

    def is_file(self: Path) -> bool:
        return False if self.name == "pyproject.toml" else original(self)

    monkeypatch.setattr(Path, "is_file", is_file)
    assert _find_pyproject(tmp_path) is None
