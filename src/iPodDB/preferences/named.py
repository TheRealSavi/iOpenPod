"""Lossless, qualified edits to the native Nano ``Device/iPodSettings.xml``.

This is a separate native settings store from the legacy binary Preferences
blob. Only independently traced Brightness, SoundCheck and EQ values are
authorable. The inspection module describes other saved fields without granting
write permission. Nano 4's extensionless store is inspection-only here.
See docs/research/preferences-nano345-2026-11-07.md and
docs/research/preferences-nano67-2026-11-07.md for exact firmware evidence.

We replace scalar text in the captured bytes instead of rebuilding an XML tree.
No missing document, section, or setting is synthesized. Firmware adoption and
retained-RAM overwrites remain application lifecycle concerns.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import cast

from iPodDB.preferences._named_xml import parse_named_xml, unsigned_decimal
from iPodDB.preferences.definitions import (
    NamedPreferencesProfile,
    PreferenceField,
    PreferenceKey,
)
from iPodDB.preferences.models import NamedPreferencesDocument
from iPodDB.shared.errors import iPodDBWriteError


@dataclass(frozen=True, slots=True)
class _Scalar:
    key: PreferenceKey
    start: int
    end: int
    value: int | None


_FIELDS = (
    PreferenceField(PreferenceKey.BRIGHTNESS, minimum=0, maximum=100),
    PreferenceField(PreferenceKey.SOUND_CHECK, (0, 1)),
    # All four latest Nano 5/6/7 images independently map UI index 0 to Off
    # (stored 0), and indices 1..22 to the native preset IDs 100..121.
    # Unknown stored IDs can display Off in firmware, but are never normalized.
    # See preferences-nano567-complete-2026-11-07.md and final-ui receipts.
    PreferenceField(PreferenceKey.EQ_PRESET, (0, *range(100, 122))),
)
_NAMES = {
    PreferenceKey.BRIGHTNESS: ("General", "Brightness"),
    PreferenceKey.SOUND_CHECK: ("Playback", "SoundCheck"),
    PreferenceKey.EQ_PRESET: ("Playback", "EQ"),
}


def _scan(source: bytes) -> tuple[tuple[_Scalar, ...], tuple[str, ...]]:
    """Locate plain UTF-8 scalar spans without resolving external entities.

    Native serializers emit unsigned decimal text. We retain other spellings
    without projecting a possibly different native parser interpretation.
    Unknown scalar text can still be explicitly replaced with a valid value.
    """
    root, framing_issues = parse_named_xml(source)
    if root is None:
        return (), framing_issues
    result: list[_Scalar] = []
    issues: list[str] = []
    for key, (section_name, name) in _NAMES.items():
        sections = [item for item in root.children if item.name == section_name]
        if not sections:
            continue
        if len(sections) != 1 or sections[0].attributes:
            issues.append(f"{section_name}.{name} has an ambiguous section.")
            continue
        nodes = [item for item in sections[0].children if item.name == name]
        if not nodes:
            continue
        if len(nodes) != 1:
            issues.append(f"{section_name}.{name} occurs more than once.")
            continue
        node = nodes[0]
        if (
            node.attributes
            or node.children
            or node.complex
            or node.self_closing
            or node.end < node.start
        ):
            issues.append(f"{section_name}.{name} is not a plain scalar.")
            continue
        raw = source[node.start : node.end]
        # Read original text, not entity-expanded text: authoring preserves the
        # existing distinction between unknown spellings and ordinary decimals.
        value = unsigned_decimal(
            raw.decode("utf-8"), 32, boolean=key is PreferenceKey.SOUND_CHECK
        )
        result.append(_Scalar(key, node.start, node.end, value))
    return tuple(result), tuple(issues)


def parse_named_preferences(
    data: bytes | bytearray | memoryview, *, profile: NamedPreferencesProfile
) -> NamedPreferencesDocument:
    """Retain any captured bytes; unsupported XML remains nonblocking/read-only."""
    if type(profile) is not NamedPreferencesProfile:
        raise ValueError("An explicit named Preferences profile is required.")
    # Untyped callers still need validation before bytes() can coerce the input.
    if not isinstance(cast("object", data), (bytes, bytearray, memoryview)):
        raise TypeError("Named Preferences require captured bytes.")
    source = bytes(data)
    _, issues = _scan(source)
    return NamedPreferencesDocument(source, profile, issues)


def available_named_preferences(
    document: NamedPreferencesDocument,
) -> tuple[PreferenceField, ...]:
    if (
        type(document.profile) is not NamedPreferencesProfile
        or type(document.source_bytes) is not bytes
        or document.profile is NamedPreferencesProfile.NANO_4_1_0_4
    ):
        return ()
    scalars, _ = _scan(document.source_bytes)
    present = {item.key for item in scalars}
    return tuple(item for item in _FIELDS if item.key in present)


def named_preference_value(
    document: NamedPreferencesDocument, key: PreferenceKey
) -> int | None:
    if (
        type(document.profile) is not NamedPreferencesProfile
        or type(document.source_bytes) is not bytes
        or document.profile is NamedPreferencesProfile.NANO_4_1_0_4
    ):
        return None
    scalars, _ = _scan(document.source_bytes)
    scalar = next((item for item in scalars if item.key is key), None)
    if scalar is None:
        return None
    return dict(document.preference_edits).get(key, scalar.value)


def write_named_preferences(document: NamedPreferencesDocument) -> bytes:
    """Validate edits again at publication and replace only selected scalar text."""
    if (
        type(document.profile) is not NamedPreferencesProfile
        or type(document.source_bytes) is not bytes
    ):
        raise iPodDBWriteError(
            "Named Preferences require immutable captured bytes and a qualified profile.",
            code="preferences.invalid_document",
        )
    if not document.preference_edits:
        return document.source_bytes
    scalars, _ = _scan(document.source_bytes)
    spans = {item.key: item for item in scalars}
    domains = {item.key: item for item in available_named_preferences(document)}
    replacements: list[tuple[int, int, bytes]] = []
    seen: set[PreferenceKey] = set()
    for key, value in document.preference_edits:
        domain = domains.get(key) if type(key) is PreferenceKey else None
        if domain is None or key in seen or not domain.accepts(value):
            raise iPodDBWriteError(
                "Unsupported or invalid named Preferences edit.",
                code="preferences.invalid_value",
                field=str(key),
            )
        seen.add(key)
        scalar = spans[key]
        if scalar.value != value:
            raw = document.source_bytes[scalar.start : scalar.end]
            if key is PreferenceKey.SOUND_CHECK:
                # Canonical boolean text is required: retaining a leading
                # space would cause native conversion to consume no digits.
                left, right = 0, len(raw)
            else:
                left = len(raw) - len(raw.lstrip(b" \t\r\n"))
                right = max(left, len(raw.rstrip(b" \t\r\n")))
            replacements.append(
                (scalar.start + left, scalar.start + right, str(value).encode("ascii"))
            )
    output = document.source_bytes
    for start, end, value_bytes in sorted(replacements, reverse=True):
        output = output[:start] + value_bytes + output[end:]
    return output


def update_named_preferences(
    document: NamedPreferencesDocument, changes: Mapping[PreferenceKey, int]
) -> NamedPreferencesDocument:
    """Return a new retained document with explicit, validated scalar edits."""
    write_named_preferences(document)
    for key, value in changes.items():
        if type(key) is not PreferenceKey or type(value) is not int:
            raise iPodDBWriteError(
                "Unsupported or invalid named Preferences edit.",
                code="preferences.invalid_value",
                field=str(key),
            )
    edits = dict(document.preference_edits)
    edits.update(changes)
    updated = replace(document, preference_edits=tuple(edits.items()))
    write_named_preferences(updated)
    return updated
