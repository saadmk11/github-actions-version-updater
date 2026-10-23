"""Shared helpers for action-extra tests."""

from __future__ import annotations

from pathlib import Path

from update_gha.config import Configuration


def make_config(
    **overrides: str | bool | Path | tuple[str, ...] | None,
) -> Configuration:
    data: dict[str, str | bool | Path | tuple[str, ...] | None] = {
        "token": "token-token",
        "repository": "o/r",
        "github_ref": "refs/heads/main",
    }
    data.update(overrides)
    return Configuration.model_validate(data)
