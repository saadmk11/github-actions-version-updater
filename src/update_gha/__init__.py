"""GitHub Actions Version Updater."""

from __future__ import annotations

from update_gha._version import __version__
from update_gha.rewrite import (
    apply_version_updates,
    get_all_actions,
)
from update_gha.scan import run_update

__all__ = [
    "__version__",
    "apply_version_updates",
    "get_all_actions",
    "run_update",
]
