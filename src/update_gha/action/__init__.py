"""Optional git / pull-request helpers for ``update-gha --pull-request``."""

from __future__ import annotations

import importlib.util

EXTRA_HINT = (
    "GitPython is not installed. Install the action extra: "
    "pip install 'update-gha[action]'  or  uv add 'update-gha[action]'"
)


def has_action_extra() -> bool:
    return importlib.util.find_spec("git") is not None
