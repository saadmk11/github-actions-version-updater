"""YAML rewrite: fixture pairs and quoting / span edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from update_gha.rewrite import (
    apply_version_updates,
    get_all_actions,
    parse_uses_spans,
)

FIXTURES = Path(__file__).parent / "fixtures"

FAKE_VERSIONS: dict[str, str] = {
    "actions/checkout@v2": "v4",
    "actions/checkout@v3": "v4",
    "actions/setup-python@v4": "v5",
    "actions/setup-node@v3": "v4",
    "actions/cache@v3": "v4",
    "actions/checkout@v4": "v4",
    "actions/setup-python@v5": "v5",
}


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _apply(input_text: str) -> str:
    actions = get_all_actions(input_text) or frozenset()
    updates: dict[str, str] = {}
    for action in actions:
        if "@" not in action:
            continue
        new_ver = FAKE_VERSIONS.get(action)
        if new_ver is not None:
            updates[action] = new_ver
    return apply_version_updates(input_text, updates)


def _assert_fixture(fixture_base: str) -> None:
    input_text = _read(f"{fixture_base}_input.yml")
    expected = _read(f"{fixture_base}_expected.yml")
    assert _apply(input_text) == expected


@pytest.mark.parametrize(
    "fixture_base",
    [
        "quoted",
        "comments",
        "same_action_two_versions",
        "anchors",
        "multi_document",
        "non_ascii",
        "idempotent",
    ],
)
def test_rewrite_fixtures(fixture_base: str) -> None:
    _assert_fixture(fixture_base)


def test_idempotent_double_run() -> None:
    input_text = _read("quoted_input.yml")
    first_pass = _apply(input_text)
    assert first_pass == _apply(first_pass)


def test_discovers_actions() -> None:
    assert get_all_actions(_read("quoted_input.yml")) == frozenset(
        {
            "actions/checkout@v3",
            "actions/setup-python@v4",
            "actions/cache@v3",
        }
    )


def test_multi_document_discovery() -> None:
    assert get_all_actions(_read("multi_document_input.yml")) == frozenset(
        {
            "actions/checkout@v3",
            "actions/setup-python@v4",
        }
    )


def test_same_action_two_versions_discovery() -> None:
    assert get_all_actions(_read("same_action_two_versions_input.yml")) == frozenset(
        {
            "actions/checkout@v2",
            "actions/checkout@v3",
        }
    )


def test_invalid_yaml_returns_none() -> None:
    assert get_all_actions("not: [valid: yaml: {{{}}") is None


def test_scalar_document_has_no_actions() -> None:
    assert get_all_actions("42\n") == frozenset()
    assert get_all_actions("- hello\n- 1\n") == frozenset()


def test_non_string_uses_value_is_ignored() -> None:
    assert get_all_actions("- uses: 123\n- uses: true\n") == frozenset()


def test_folded_uses_is_rewritten() -> None:
    text = "jobs:\n  a:\n    steps:\n      - uses: >-\n          actions/checkout@v3\n"
    assert get_all_actions(text) == frozenset({"actions/checkout@v3"})
    updated = apply_version_updates(text, {"actions/checkout@v3": "v4"})
    assert "actions/checkout@v4" in updated
    assert "actions/checkout@v3" not in updated


def test_token_fallback_does_not_rewrite_longer_version() -> None:
    text = (
        "jobs:\n  a:\n    steps:\n      - uses: >-\n          actions/checkout@v3.1\n"
    )
    updated = apply_version_updates(text, {"actions/checkout@v3": "v4"})
    assert "actions/checkout@v3.1" in updated
    assert "actions/checkout@v4" not in updated


def test_token_fallback_only_rewrites_the_uses_scalar() -> None:
    text = (
        "jobs:\n"
        "  update:\n"
        "    steps:\n"
        "      - uses: >-\n"
        "          org/action@v1\n"
        "      - uses: org/action@v1/maintenance\n"
        "      - run: curl https://github.com/org/action@v1/README.md\n"
        "      - run: |\n"
        "          org/action@v1\n"
    )
    updated = apply_version_updates(text, {"org/action@v1": "v2"})
    assert "          org/action@v2\n" in updated
    assert "uses: org/action@v1/maintenance" in updated
    assert "https://github.com/org/action@v1/README.md" in updated
    assert "          org/action@v1\n" in updated


def test_unquoted_date_does_not_crash() -> None:
    text = (
        "on: 2024-01-01\njobs:\n  a:\n    steps:\n      - uses: actions/checkout@v3\n"
    )
    assert get_all_actions(text) == frozenset({"actions/checkout@v3"})


def test_apply_uses_precomputed_spans() -> None:
    text = "- uses: actions/checkout@v3\n"
    spans = parse_uses_spans(text)
    assert spans is not None
    updated = apply_version_updates(text, {"actions/checkout@v3": "v4"}, spans=spans)
    assert "actions/checkout@v4" in updated
    assert apply_version_updates(text, {"actions/checkout@v3": "v4"}, spans=()) == text


def test_empty_updates_returns_original() -> None:
    text = _read("quoted_input.yml")
    assert apply_version_updates(text, {}) == text


def test_invalid_yaml_is_not_rewritten() -> None:
    text = "jobs: [\nuses: actions/checkout@v3\n"
    assert apply_version_updates(text, {"actions/checkout@v3": "v4"}) == text


def test_no_matching_action() -> None:
    text = _read("quoted_input.yml")
    assert apply_version_updates(text, {"nonexistent/action@v1": "v2"}) == text


def test_preserves_line_endings() -> None:
    text = (
        "name: Test\r\non: push\r\njobs:\r\n  build:\r\n"
        "    runs-on: ubuntu-latest\r\n    steps:\r\n"
        "      - uses: actions/checkout@v3\r\n"
    )
    result = apply_version_updates(text, {"actions/checkout@v3": "v4"})
    assert "actions/checkout@v4\r\n" in result
    assert result.count("\r\n") == text.count("\r\n")


def test_missing_colon_key_is_ignored() -> None:
    assert apply_version_updates("x", {"nocolon": "v2"}) == "x"


def test_same_version_is_idempotent() -> None:
    text = "- uses: actions/checkout@v3\n"
    assert apply_version_updates(text, {"actions/checkout@v3": "v3"}) == text


def test_escapes_new_version_for_quoted_scalars() -> None:
    single = "- uses: 'owner/action@v1'\n"
    double = '- uses: "owner/action@v1"\n'
    updated_single = apply_version_updates(single, {"owner/action@v1": "v2'stable"})
    updated_double = apply_version_updates(double, {"owner/action@v1": 'v2"stable'})
    assert yaml.safe_load(updated_single)[0]["uses"] == "owner/action@v2'stable"
    assert yaml.safe_load(updated_double)[0]["uses"] == 'owner/action@v2"stable'


def test_quotes_plain_scalar_when_tag_has_flow_delimiters() -> None:
    text = "steps: [{uses: owner/action@v1}]\n"
    updated = apply_version_updates(text, {"owner/action@v1": "v2]"})
    assert yaml.safe_load(updated)["steps"][0]["uses"] == "owner/action@v2]"


def test_block_scalar_keeps_flow_delimiter_literal() -> None:
    text = "steps:\n  - uses: >-\n      owner/action@v1\n"
    updated = apply_version_updates(text, {"owner/action@v1": "v2]"})
    assert yaml.safe_load(updated)["steps"][0]["uses"] == "owner/action@v2]"


def test_one_unrewritable_token_does_not_block_others() -> None:
    text = (
        "jobs:\n  a:\n    steps:\n"
        "      - uses: actions/setup-python@v3\n"
        '      - uses: "actions/checkout@\\\nv3"\n'
    )
    updated = apply_version_updates(
        text,
        {"actions/setup-python@v3": "v4", "actions/checkout@v3": "v4"},
    )
    assert "actions/setup-python@v4" in updated
    assert "actions/checkout@v4" not in updated
