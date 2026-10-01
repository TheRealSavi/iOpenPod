"""Pure, lossless reader/writer for iPod_Control/iTunes/iTunesPrefs."""

from dataclasses import dataclass

from iPodDB.preferences._source import capture_source
from iPodDB.preferences.itunes_definitions import (
    ITUNES_FIELD_VALUES,
    ITUNES_OBSERVATION_FIELDS,
    ITUNES_PREFS_MIN_SIZE,
    ITunesPreferences,
    ITunesPreferencesProfile,
    PreferenceToggle,
    ShuffleVoiceOverPreferences,
)
from iPodDB.shared.binary_struct import (
    binary_fields,
    binary_struct_extent,
    parse_binary_struct,
    write_binary_struct_into,
)
from iPodDB.shared.errors import iPodDBParseError, iPodDBWriteError


@dataclass(frozen=True, slots=True)
class ITunesPreferencesDocument:
    source_bytes: bytes
    settings: ITunesPreferences
    profile: ITunesPreferencesProfile = ITunesPreferencesProfile.STANDARD
    voice_over: ShuffleVoiceOverPreferences | None = None


def parse_itunes_preferences(
    data: bytes | bytearray,
    *,
    profile: ITunesPreferencesProfile = ITunesPreferencesProfile.STANDARD,
) -> ITunesPreferencesDocument:
    """Read the documented frpd prefix, retaining every unknown and later byte.

    The historical file has 236 bytes; later files are longer. No version, model,
    header-length or checksum meaning is inferred from the unknown header bytes.
    A Shuffle assertion enables the optional VoiceOver field when it is present.
    """

    if type(profile) is not ITunesPreferencesProfile:
        raise TypeError("profile must be an ITunesPreferencesProfile.")
    source = capture_source(data)
    if len(source) < ITUNES_PREFS_MIN_SIZE:
        raise iPodDBParseError("iTunesPrefs is shorter than the documented prefix.")
    if source[:4] != b"frpd":
        raise iPodDBParseError("iTunesPrefs must start with frpd.")
    voice_over = None
    if profile is ITunesPreferencesProfile.SHUFFLE and len(
        source
    ) >= binary_struct_extent(ShuffleVoiceOverPreferences):
        voice_over = parse_binary_struct(source, 0, ShuffleVoiceOverPreferences)
    return ITunesPreferencesDocument(
        source, parse_binary_struct(source, 0, ITunesPreferences), profile, voice_over
    )


def write_itunes_preferences(document: ITunesPreferencesDocument) -> bytes:
    """Overlay validated edits; do not initialize, resize or repair the file.

    Unknown retained values survive unrelated edits. Linked-library identities
    are never manufactured or synchronized implicitly. Filesystem persistence,
    protective sync policy and companion plist reconciliation belong to callers.
    """

    if type(document.source_bytes) is not bytes:
        raise iPodDBWriteError(
            "iTunesPrefs requires immutable source bytes.",
            code="itunes_preferences.invalid_source",
        )
    try:
        original = parse_itunes_preferences(
            document.source_bytes, profile=document.profile
        )
    except (iPodDBParseError, TypeError) as error:
        raise iPodDBWriteError(
            str(error), code="itunes_preferences.invalid_source"
        ) from error
    if type(document.settings) is not ITunesPreferences:
        raise iPodDBWriteError(
            "iTunesPrefs requires typed settings.",
            code="itunes_preferences.invalid_settings",
        )
    for field in binary_fields(document.settings):
        name = field.attribute_name
        value = getattr(document.settings, name)
        old_value = getattr(original.settings, name)
        enum_type = ITUNES_FIELD_VALUES.get(name)
        valid_type = (
            type(value) is bytes
            if field.schema.encoding == "raw"
            else type(value) is int
            or (enum_type is not None and type(value) is enum_type)
        )
        if not valid_type:
            raise iPodDBWriteError(
                "iTunesPrefs fields require native integers, matching enums or bytes.",
                code="itunes_preferences.invalid_value",
                field=name,
                offset=field.schema.offset,
            )
        if value == old_value:
            continue
        if name in ITUNES_OBSERVATION_FIELDS:
            raise iPodDBWriteError(
                "The units of this Shuffle capacity field are unverified; retain it.",
                code="itunes_preferences.observation_only",
                field=name,
                offset=field.schema.offset,
            )
        if enum_type is not None and value not in tuple(enum_type):
            raise iPodDBWriteError(
                "The edited iTunesPrefs setting is unrecognized.",
                code="itunes_preferences.invalid_value",
                field=name,
                offset=field.schema.offset,
            )
    output = bytearray(document.source_bytes)
    write_binary_struct_into(output, document.settings)
    if original.voice_over is None:
        if document.voice_over is not None:
            raise iPodDBWriteError(
                "VoiceOver needs a Shuffle profile and an existing field.",
                code="itunes_preferences.profile_mismatch",
            )
    else:
        if type(document.voice_over) is not ShuffleVoiceOverPreferences:
            raise iPodDBWriteError(
                "Retain the Shuffle VoiceOver settings.",
                code="itunes_preferences.profile_mismatch",
            )
        value = document.voice_over.voice_over_enabled
        if type(value) not in (int, PreferenceToggle) or (
            value != original.voice_over.voice_over_enabled and value not in (0, 1)
        ):
            raise iPodDBWriteError(
                "VoiceOver edits require 0 (disabled) or 1 (enabled).",
                code="itunes_preferences.invalid_value",
                field="voice_over_enabled",
            )
        write_binary_struct_into(output, document.voice_over)
    return bytes(output)
