"""Discover and rewrite ``uses:`` pins without re-serializing YAML."""

from collections.abc import Mapping
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version
from yaml import YAMLError, compose_all
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from update_gha.models import ActionRef, VersionToken

type UsesSpan = tuple[int, int, str, str | None]

_BLOCK_SCALAR_STYLES = frozenset({"|", ">"})


def actions_from_spans(spans: tuple[UsesSpan, ...]) -> frozenset[str]:
    """Unique ``uses`` values from already-parsed spans."""
    return frozenset(action for _start, _end, action, _style in spans)


def get_all_actions(text: str) -> frozenset[str] | None:
    """Return unique ``uses`` values, or ``None`` when the YAML is invalid."""
    spans = parse_uses_spans(text)
    if spans is None:
        return None
    return actions_from_spans(spans)


@dataclass(frozen=True, slots=True)
class PinRewrite:
    """What to write for one ``uses:`` pin.

    ``version`` is the new pin token (tag or SHA). ``comment``, when set,
    is the inline YAML comment written after the pin — the release tag
    when pinning a commit SHA. ``None`` leaves any existing comment as
    it is.
    """

    version: VersionToken
    comment: str | None = None


type PinRewriteSpec = VersionToken | PinRewrite


def apply_version_updates(
    original_text: str,
    updates: Mapping[ActionRef, PinRewriteSpec],
    *,
    spans: tuple[UsesSpan, ...] | None = None,
) -> str:
    """Return ``original_text`` with listed action versions replaced.

    A :class:`PinRewrite` ``comment`` becomes a same-line ``  # tag`` on
    single-line plain/quoted pins. Version-like comments are replaced;
    custom comments, block scalars, and flow values are left alone.
    """
    if not updates:
        return original_text

    replacements: dict[tuple[int, int], str] = {}
    resolved_spans = spans if spans is not None else parse_uses_spans(original_text)
    if resolved_spans is None:
        return original_text
    for start, end, action, style in resolved_spans:
        if (spec := updates.get(action)) is None:
            continue
        rewrite = _as_pin_rewrite(spec)
        location, separator, old_version = action.rpartition("@")
        if not separator or not location:
            continue
        version_changed = rewrite.version != old_version
        if not version_changed and rewrite.comment is None:
            continue
        raw_scalar = original_text[start:end]
        if version_changed:
            updated_action = f"{location}@{rewrite.version}"
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
        else:
            updated_scalar = raw_scalar

        replacement = updated_scalar
        replace_end = end
        if rewrite.comment is not None:
            annotated = _apply_release_tag_comment(
                original_text,
                scalar_start=start,
                scalar_end=end,
                style=style,
                tag=rewrite.comment,
            )
            if annotated is not None:
                suffix, suffix_len = annotated
                replacement = updated_scalar + suffix
                replace_end = end + suffix_len

        if original_text[start:replace_end] == replacement:
            continue
        replacements[(start, replace_end)] = replacement

    result = original_text
    for (start, end), replacement in sorted(replacements.items(), reverse=True):
        result = f"{result[:start]}{replacement}{result[end:]}"
    return result


def _as_pin_rewrite(spec: PinRewriteSpec) -> PinRewrite:
    if isinstance(spec, PinRewrite):
        return spec
    return PinRewrite(version=spec)


def _apply_release_tag_comment(
    text: str,
    *,
    scalar_start: int,
    scalar_end: int,
    style: str | None,
    tag: str,
) -> tuple[str, int] | None:
    """Return ``(new_suffix, old_suffix_len)`` after the scalar, or ``None``.

    ``None`` means the pin cannot be annotated in place: the tag is
    unsafe, the scalar is a block or multi-line value, or more YAML
    tokens follow on the same line (flow style).
    """
    tag = tag.strip()
    if (
        not tag
        or "\n" in tag
        or "\r" in tag
        or style in _BLOCK_SCALAR_STYLES
        or any(character in text[scalar_start:scalar_end] for character in "\r\n")
    ):
        return None

    line, _nl, _rest = text[scalar_end:].partition("\n")
    suffix = line[:-1] if line.endswith("\r") else line
    comment_at = suffix.find("#")
    before_hash = suffix if comment_at < 0 else suffix[:comment_at]
    if before_hash.strip():
        return None

    desired = f"  # {tag}"
    if comment_at < 0:
        return desired, len(suffix)
    body = suffix[comment_at + 1 :].strip()
    if body == tag or _is_version_comment(body):
        return desired, len(suffix)
    return None


def _is_version_comment(body: str) -> bool:
    if not body:
        return False
    try:
        Version(body)
    except InvalidVersion:
        return False
    return True


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
