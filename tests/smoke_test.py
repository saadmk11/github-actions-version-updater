"""Import and rewrite smoke test used by the release workflow on built artifacts."""

from __future__ import annotations

from update_gha import (
    __version__,
    apply_version_updates,
    get_all_actions,
)


def main() -> None:
    if not __version__:
        raise SystemExit("missing package version")
    text = "- uses: actions/checkout@v3\n"
    actions = get_all_actions(text)
    if actions != frozenset({"actions/checkout@v3"}):
        raise SystemExit(f"unexpected actions: {actions}")
    updated = apply_version_updates(text, {"actions/checkout@v3": "v4"})
    if "actions/checkout@v4" not in updated:
        raise SystemExit(f"update failed: {updated!r}")
    print(f"smoke ok {__version__}")


# Release runs this file as a script; pytest also imports it during collection.
if __name__ == "__main__":
    main()
