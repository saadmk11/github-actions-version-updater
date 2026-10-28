"""Optional GitHub Actions reporting and pull-request support."""

from __future__ import annotations

import importlib.util

EXTRA_HINT = (
    "Install the action extra for GitHub Actions and pull-request support: "
    "pip install 'update-gha[action]'  or  uv add 'update-gha[action]'"
)


def has_action_extra() -> bool:
    """Return whether the GitHub Actions and Git dependencies are installed."""
    return (
        importlib.util.find_spec("git") is not None
        and importlib.util.find_spec("github_action_utils") is not None
    )
