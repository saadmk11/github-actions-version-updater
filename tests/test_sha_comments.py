"""SHA-pin ``# tag`` comments."""

from __future__ import annotations

from pathlib import Path

import pytest

from update_gha.rewrite import PinRewrite, apply_version_updates, get_all_actions

FIXTURES = Path(__file__).parent / "fixtures"

CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
PYTHON_SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
CACHE_SHA = "b2c3d4e5f60718293a4b5c6d7e8f90123456789a"
NODE_SHA = "c3d4e5f60718293a4b5c6d7e8f90123456789ab"
LOGIN_SHA = "d4e5f60718293a4b5c6d7e8f90123456789abc0"
UPLOAD_SHA = "e5f60718293a4b5c6d7e8f90123456789abcd01"
SCRIPT_SHA = "f60718293a4b5c6d7e8f90123456789abcde012"
LABELER_SHA = "0123456789abcdef0123456789abcdef01234567"
STALE_SHA = "123456789abcdef0123456789abcdef012345678"
NESTED_SHA = "23456789abcdef0123456789abcdef0123456789"
REUSABLE_SHA = "3456789abcdef0123456789abcdef01234567890"
OLD_SHA = "8f4b7f84864484a7ac97850a33f01d618c579def"

SHA_UPDATES: dict[str, PinRewrite] = {
    "actions/checkout@v2": PinRewrite(CHECKOUT_SHA, "v4.2.2"),
    "actions/checkout@v3": PinRewrite(CHECKOUT_SHA, "v4.2.2"),
    "actions/setup-python@v4": PinRewrite(PYTHON_SHA, "v5.0.0"),
    "actions/cache@v3": PinRewrite(CACHE_SHA, "v4.0.2"),
    "actions/setup-node@v3": PinRewrite(NODE_SHA, "v4.1.0"),
    "docker/login-action@v3": PinRewrite(LOGIN_SHA, "v3.3.0"),
    "actions/upload-artifact@v3": PinRewrite(UPLOAD_SHA, "v4.3.1"),
    "actions/github-script@v6": PinRewrite(SCRIPT_SHA, "v7.0.1"),
    "actions/labeler@v4": PinRewrite(LABELER_SHA, "v5.0.0"),
    "actions/stale@v8": PinRewrite(STALE_SHA, "v9.0.0"),
    "owner/nested/action@v1": PinRewrite(NESTED_SHA, "v1.4.0"),
    "org/tool/.github/workflows/ci.yml@v2": PinRewrite(REUSABLE_SHA, "v2.1.0"),
}


def _pin(text: str, tag: str = "v4.2.2") -> str:
    return apply_version_updates(
        text, {"actions/checkout@v3": PinRewrite(CHECKOUT_SHA, tag)}
    )


def test_sha_comment_fixture() -> None:
    input_text = (FIXTURES / "sha_comment_input.yml").read_text(encoding="utf-8")
    expected = (FIXTURES / "sha_comment_expected.yml").read_text(encoding="utf-8")
    actions = get_all_actions(input_text) or frozenset()
    updates = {
        action: SHA_UPDATES[action] for action in actions if action in SHA_UPDATES
    }
    assert apply_version_updates(input_text, updates) == expected


@pytest.mark.parametrize("spaces", [1, 2, 8])
def test_previous_version_comment_is_replaced(spaces: int) -> None:
    source = f"steps:\n  - uses: actions/checkout@{OLD_SHA}{' ' * spaces}# v3.5.0\n"
    updated = apply_version_updates(
        source, {f"actions/checkout@{OLD_SHA}": PinRewrite(CHECKOUT_SHA, "v4.2.2")}
    )
    assert updated == f"steps:\n  - uses: actions/checkout@{CHECKOUT_SHA}  # v4.2.2\n"


def test_quoted_pin_gets_two_space_comment() -> None:
    assert _pin("steps:\n  - uses: 'actions/checkout@v3'\n") == (
        f"steps:\n  - uses: 'actions/checkout@{CHECKOUT_SHA}'  # v4.2.2\n"
    )
    assert _pin('steps:\n  - uses: "actions/checkout@v3"# v3\n') == (
        f'steps:\n  - uses: "actions/checkout@{CHECKOUT_SHA}"  # v4.2.2\n'
    )


def test_custom_comment_is_left_alone() -> None:
    assert _pin("steps:\n  - uses: actions/checkout@v3 # keep me\n") == (
        f"steps:\n  - uses: actions/checkout@{CHECKOUT_SHA} # keep me\n"
    )
    assert _pin("steps:\n  - uses: actions/checkout@v3 #\n") == (
        f"steps:\n  - uses: actions/checkout@{CHECKOUT_SHA} #\n"
    )


def test_existing_tag_comment_is_normalized() -> None:
    text = f"steps:\n  - uses: actions/checkout@{CHECKOUT_SHA} # v4.2.2\n"
    updated = apply_version_updates(
        text, {f"actions/checkout@{CHECKOUT_SHA}": PinRewrite(CHECKOUT_SHA, "v4.2.2")}
    )
    assert updated == f"steps:\n  - uses: actions/checkout@{CHECKOUT_SHA}  # v4.2.2\n"
    already = f"steps:\n  - uses: actions/checkout@{CHECKOUT_SHA}  # v4.2.2\n"
    assert (
        apply_version_updates(
            already,
            {f"actions/checkout@{CHECKOUT_SHA}": PinRewrite(CHECKOUT_SHA, "v4.2.2")},
        )
        == already
    )


@pytest.mark.parametrize(
    "text",
    [
        "steps: [{uses: actions/checkout@v3}]\n",
        "steps:\n  - uses: >-\n      actions/checkout@v3\n",
        'steps:\n  - uses: "actions/checkout@\\\nv3"\n',
    ],
)
def test_flow_and_block_scalars_are_not_annotated(text: str) -> None:
    updated = apply_version_updates(
        text, {"actions/checkout@v3": PinRewrite(CHECKOUT_SHA, "v4.2.2")}
    )
    assert "  # v4.2.2" not in updated


def test_crlf_and_missing_newline() -> None:
    crlf = "steps:\r\n  - uses: actions/checkout@v3\r\n"
    assert f"@{CHECKOUT_SHA}  # v4.2.2\r\n" in _pin(crlf)
    assert _pin("steps:\n  - uses: actions/checkout@v3") == (
        f"steps:\n  - uses: actions/checkout@{CHECKOUT_SHA}  # v4.2.2"
    )


def test_multiline_quoted_value_is_not_annotated() -> None:
    text = 'steps:\n  - uses: "actions/checkout@v3\n"\n'
    updated = apply_version_updates(
        text, {"actions/checkout@v3 ": PinRewrite("v3 ", "v4.2.2")}
    )
    assert updated == text


def test_unsafe_tag_and_plain_string_update() -> None:
    text = "steps:\n  - uses: actions/checkout@v3\n"
    for tag in ("v4\n.2", "v4\r.2", "  "):
        assert (
            apply_version_updates(
                text, {"actions/checkout@v3": PinRewrite(CHECKOUT_SHA, tag)}
            )
            == f"steps:\n  - uses: actions/checkout@{CHECKOUT_SHA}\n"
        )
    assert apply_version_updates(text, {"actions/checkout@v3": "v4"}) == (
        "steps:\n  - uses: actions/checkout@v4\n"
    )
