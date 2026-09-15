"""Shared helpers for action-extra tests."""

from __future__ import annotations

from update_gha.config import Configuration


def make_config(**overrides: object) -> Configuration:
    data: dict[str, object] = {
        "token": "token-token",
        "repository": "o/r",
        "github_ref": "refs/heads/main",
    }
    data.update(overrides)
    return Configuration.model_validate(data)
