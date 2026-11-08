"""Qualified saved-setting edits over retained firmware Preferences.

The byte map and authored domains live in native_definitions; this module
applies compound Shuffle/photo transitions and masked Clicker edits. These are
saved settings, not observations of live playback or proof that a USB detach
reloads Preferences. The retained-RAM writer can later overwrite a Host edit.
Unknown values survive unrelated edits.

Qualification sources are the preferences-*-complete-2026-11-07 research notes,
preferences-classic-structures-2026-11-07, preferences-nano34-effects-2026-11-07
and preferences-video-deep-followup-2026-11-07. Their native UI/serializer
receipts distinguish offered choices from wider raw setter acceptance. Shared
offsets alone never qualify another model. Clock fields, volume/locks, forced
flags, slideshow music identities and captions/subtitles remain outside this
authoring API; the latter need coupled live-observer semantics.
"""

from collections.abc import Mapping
from dataclasses import replace

from iPodDB.preferences.definitions import (
    PreferenceField,
    PreferenceKey,
    definition_for_size,
)
from iPodDB.preferences.models import PreferencesDocument
from iPodDB.preferences.native_definitions import (
    PreferenceEncoding,
    preference_encodings,
)
from iPodDB.shared.errors import iPodDBWriteError


def _encodings(document: PreferencesDocument) -> tuple[PreferenceEncoding, ...]:
    definition = definition_for_size(len(document.source_bytes), document.profile)
    if (
        definition is None
        or document.layout is not definition.layout
        or type(document.settings) is not definition.settings_type
        or definition.format_version is None
        or not definition.matches(document.source_bytes)
        # Do not offer edits to bytes the native loader would discard.
        or (
            definition.reset_word_offset is not None
            and document.reset_requested is not False
        )
    ):
        return ()
    return preference_encodings(document.profile)


def available_preferences(document: PreferencesDocument) -> tuple[PreferenceField, ...]:
    """Return authorable domains only for an explicitly qualified exact frame.

    Unknown retained values do not change capability; preference_value exposes
    them so the application can display them without choosing a replacement.
    """
    return tuple(item.field for item in _encodings(document))


def _read(source: bytes | bytearray, encoding: PreferenceEncoding) -> int | None:
    value = int.from_bytes(
        source[encoding.offset : encoding.offset + encoding.width],
        "little",
        signed=encoding.signed,
    )
    if encoding.pair is not None:
        secondary = source[encoding.pair.secondary_offset]
        return next(
            (
                choice.value
                for choice in encoding.pair.choices
                if value == choice.primary
                and (
                    secondary == choice.secondary
                    or value in encoding.pair.ignored_secondary_modes
                )
            ),
            None,
        )
    return value if encoding.mask is None else value & encoding.mask


def preference_value(document: PreferencesDocument, key: PreferenceKey) -> int | None:
    """Read an unnormalized saved value, including pending explicit edits.

    None means unavailable or unrepresentable compound bytes. Scalar
    unknown values remain integers; they are never silently replaced by defaults.
    Clicker intentionally projects only its editable low bits.
    """
    encoding = next(
        (item for item in _encodings(document) if item.field.key is key), None
    )
    if encoding is None:
        return None
    for changed_key, value in document.preference_edits:
        if changed_key is key:
            return value
    return _read(document.source_bytes, encoding)


def apply_preference_edits(output: bytearray, document: PreferencesDocument) -> None:
    """Internal writer boundary: validate every edit before touching its bytes."""
    encodings = {item.field.key: item for item in _encodings(document)}
    seen: set[PreferenceKey] = set()
    for key, value in document.preference_edits:
        encoding = encodings.get(key) if type(key) is PreferenceKey else None
        if encoding is None or key in seen or not encoding.field.accepts(value):
            raise iPodDBWriteError(
                "Unsupported or invalid Preferences edit.",
                code="preferences.invalid_value",
                field=str(key),
            )
        seen.add(key)
        if encoding.pair is not None:
            # Preserve known irrelevant bytes on a no-op (Shuffle already Off,
            # or Random's stale transition ID); author both bytes on a change.
            if _read(output, encoding) != value:
                choice = next(
                    item for item in encoding.pair.choices if item.value == value
                )
                output[encoding.offset] = choice.primary
                output[encoding.pair.secondary_offset] = choice.secondary
        else:
            if encoding.mask is not None:
                old = int.from_bytes(
                    output[encoding.offset : encoding.offset + encoding.width], "little"
                )
                value = old & ~encoding.mask | value
            output[encoding.offset : encoding.offset + encoding.width] = value.to_bytes(
                encoding.width, "little", signed=encoding.signed
            )


def update_preferences(
    document: PreferencesDocument, changes: Mapping[PreferenceKey, int]
) -> PreferencesDocument:
    """Return a validated edit while retaining the original comparison bytes.

    Only explicit choices are authored. This neither creates a Preferences file
    nor writes a device, resets unknown fields, or changes clock/language state.
    """
    from iPodDB.preferences.codec import write_preferences

    pending = dict(document.preference_edits)
    encodings = {item.field.key: item for item in _encodings(document)}
    for key, value in changes.items():
        encoding = encodings.get(key) if type(key) is PreferenceKey else None
        if encoding is None or not encoding.field.accepts(value):
            raise iPodDBWriteError(
                "Unsupported or invalid Preferences edit.",
                code="preferences.invalid_value",
                field=str(key),
            )
        if value == _read(document.source_bytes, encoding):
            pending.pop(key, None)
        else:
            pending[key] = value
    updated = replace(document, preference_edits=tuple(pending.items()))
    write_preferences(updated)
    return updated
