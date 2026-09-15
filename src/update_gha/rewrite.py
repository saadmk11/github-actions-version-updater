"""Discover and rewrite ``uses:`` pins without re-serializing YAML."""

from collections.abc import Mapping

from yaml import YAMLError, compose_all
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from update_gha.models import ActionRef, VersionToken

type UsesSpan = tuple[int, int, str, str | None]


def actions_from_spans(spans: tuple[UsesSpan, ...]) -> frozenset[str]:
    """Unique ``uses`` values from already-parsed spans."""
    return frozenset(action for _start, _end, action, _style in spans)


def get_all_actions(text: str) -> frozenset[str] | None:
    """Return unique ``uses`` values, or ``None`` when the YAML is invalid."""
    spans = parse_uses_spans(text)
    if spans is None:
        return None
    return actions_from_spans(spans)


def apply_version_updates(
    original_text: str,
    updates: Mapping[ActionRef, VersionToken],
    *,
    spans: tuple[UsesSpan, ...] | None = None,
) -> str:
    """Return ``original_text`` with listed action versions replaced."""
    if not updates:
        return original_text

    replacements: dict[tuple[int, int], str] = {}
    resolved_spans = spans if spans is not None else parse_uses_spans(original_text)
    if resolved_spans is None:
        return original_text
    for start, end, action, style in resolved_spans:
        if (new_version := updates.get(action)) is None:
            continue
        location, separator, old_version = action.rpartition("@")
        if not separator or not location or new_version == old_version:
            continue
        raw_scalar = original_text[start:end]
        updated_action = f"{location}@{new_version}"
        match style:
            case "'":
                encoded_action = updated_action.replace("'", "''")
            case '"':
                encoded_action = updated_action.replace("\\", "\\\\").replace(
                    '"', '\\"'
                )
            case None if any(character in ",[]{}" for character in updated_action):
                escaped_action = updated_action.replace("'", "''")
                encoded_action = f"'{escaped_action}'"
            case _:
                encoded_action = updated_action
        updated_scalar = raw_scalar.replace(action, encoded_action, 1)
        if updated_scalar == raw_scalar:
            continue
        replacements[(start, end)] = updated_scalar

    result = original_text
    for (start, end), replacement in sorted(replacements.items(), reverse=True):
        result = f"{result[:start]}{replacement}{result[end:]}"
    return result


def parse_uses_spans(text: str) -> tuple[UsesSpan, ...] | None:
    """Return source spans for scalar values assigned to a ``uses`` key."""
    found: dict[tuple[int, int], tuple[str, str | None]] = {}
    seen: set[int] = set()

    def visit(node: Node) -> None:
        identity = id(node)
        if identity in seen:
            return
        seen.add(identity)

        if isinstance(node, MappingNode):
            for key, value in node.value:
                if (
                    isinstance(key, ScalarNode)
                    and key.value == "uses"
                    and key.tag == "tag:yaml.org,2002:str"
                    and isinstance(value, ScalarNode)
                    and value.tag == "tag:yaml.org,2002:str"
                ):
                    found[(value.start_mark.index, value.end_mark.index)] = (
                        value.value,
                        value.style,
                    )
                visit(value)
        elif isinstance(node, SequenceNode):
            for value in node.value:
                visit(value)

    try:
        for document in compose_all(text):
            visit(document)
    except YAMLError:
        return None
    return tuple(
        (start, end, action, style) for (start, end), (action, style) in found.items()
    )
