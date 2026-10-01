"""Pure lossless Preferences reader/writer; persistence belongs to Storage."""

from iPodDB.preferences._source import capture_source
from iPodDB.preferences.definitions import (
    PreferencesLayout,
    PreferencesProfile,
    definition_for_size,
    extension_for_profile,
)
from iPodDB.preferences.models import CityTimezone, PreferencesDocument
from iPodDB.shared.binary_struct import (
    binary_fields,
    parse_binary_struct,
    write_binary_struct_into,
)
from iPodDB.shared.errors import iPodDBParseError, iPodDBWriteError


def parse_preferences(
    data: bytes | bytearray,
    *,
    layout: PreferencesLayout | None = None,
    profile: PreferencesProfile = PreferencesProfile.STANDARD,
) -> PreferencesDocument:
    """Read fields from an exact known extent, otherwise retain opaque bytes.

    A supplied known layout asserts a match; it cannot force offsets onto a
    different size. UNKNOWN explicitly suppresses interpretation, including on
    an unverified model whose file happens to have a recognized size. No model
    identity, checksum, or signature is inferred from file length.
    """

    if layout is not None and type(layout) is not PreferencesLayout:
        raise TypeError("layout must be a PreferencesLayout.")
    if type(profile) is not PreferencesProfile:
        raise TypeError("profile must be a PreferencesProfile.")
    source = capture_source(data)
    if not source:
        raise iPodDBParseError("Preferences is empty.")
    definition = definition_for_size(len(source))
    if profile is not PreferencesProfile.STANDARD and (
        layout is PreferencesLayout.UNKNOWN or definition is None
    ):
        raise iPodDBParseError("An opaque Preferences layout cannot assert a profile.")
    if layout is PreferencesLayout.UNKNOWN:
        return PreferencesDocument(source, PreferencesLayout.UNKNOWN, None)
    if layout is not None and (definition is None or definition.layout is not layout):
        raise iPodDBParseError(
            f"Preferences layout {layout.value} does not match {len(source)} bytes."
        )
    if definition is None:
        return PreferencesDocument(source, PreferencesLayout.UNKNOWN, None)
    try:
        extension = extension_for_profile(profile, len(source))
    except ValueError as error:
        raise iPodDBParseError(str(error)) from error
    return PreferencesDocument(
        source,
        definition.layout,
        parse_binary_struct(source, 0, definition.settings_type),
        profile,
        parse_binary_struct(source, 0, extension) if extension is not None else None,
    )


def write_preferences(document: PreferencesDocument) -> bytes:
    """Overlay edited known fields without changing any other source bytes.

    Unknown layouts and unknown/invalid retained values round-trip unchanged.
    Newly introduced invalid field values are rejected independently. This is
    an inverse codec, not a factory for new firmware settings or a device write.
    """

    if type(document.source_bytes) is not bytes or not document.source_bytes:
        raise iPodDBWriteError(
            "Preferences requires nonempty, immutable source bytes.",
            code="preferences.invalid_source",
        )
    if type(document.layout) is not PreferencesLayout:
        raise iPodDBWriteError(
            "Preferences requires a typed layout.", code="preferences.layout_mismatch"
        )
    if type(document.profile) is not PreferencesProfile:
        raise iPodDBWriteError(
            "Preferences requires a typed profile.", code="preferences.profile_mismatch"
        )
    if document.layout is PreferencesLayout.UNKNOWN:
        if (
            document.settings is not None
            or document.extended_settings is not None
            or document.profile is not PreferencesProfile.STANDARD
        ):
            raise iPodDBWriteError(
                "An unknown Preferences layout has no editable fields.",
                code="preferences.unknown_layout",
            )
        return document.source_bytes
    definition = definition_for_size(len(document.source_bytes))
    if (
        definition is None
        or document.layout is not definition.layout
        or document.settings is None
        or type(document.settings) is not definition.settings_type
    ):
        raise iPodDBWriteError(
            "Preferences settings must match the retained source layout and size.",
            code="preferences.layout_mismatch",
        )
    original = parse_binary_struct(document.source_bytes, 0, definition.settings_type)
    for field in binary_fields(document.settings):
        if type(getattr(document.settings, field.attribute_name)) is not int:
            raise iPodDBWriteError(
                "Preferences fields require integers, not booleans or floats.",
                code="preferences.invalid_value",
                field=field.attribute_name,
                offset=field.schema.offset,
            )
    timezone_changed = any(
        getattr(document.settings, field.attribute_name)
        != getattr(original, field.attribute_name)
        for field in binary_fields(original)
        if field.attribute_name != "language_code"
    )
    zone = document.timezone
    if timezone_changed and (
        zone is None or (isinstance(zone, CityTimezone) and zone.timezone_name is None)
    ):
        raise iPodDBWriteError(
            "The edited Preferences timezone is invalid or unrecognized.",
            code="preferences.invalid_timezone",
        )
    output = bytearray(document.source_bytes)
    write_binary_struct_into(output, document.settings)
    try:
        extension = extension_for_profile(document.profile, len(output))
    except ValueError as error:
        raise iPodDBWriteError(
            str(error), code="preferences.profile_mismatch"
        ) from error
    if extension is None:
        if document.extended_settings is not None:
            raise iPodDBWriteError(
                "Standard Preferences has no extended settings.",
                code="preferences.profile_mismatch",
            )
    else:
        if (
            document.extended_settings is None
            or type(document.extended_settings) is not extension
        ):
            raise iPodDBWriteError(
                "Extended Preferences settings must match the asserted profile.",
                code="preferences.profile_mismatch",
            )
        original_extension = parse_binary_struct(document.source_bytes, 0, extension)
        for field in binary_fields(document.extended_settings):
            value = getattr(document.extended_settings, field.attribute_name)
            valid = False
            if type(value) is int:
                valid = (
                    value in (0, 60)
                    if document.profile is PreferencesProfile.NANO_3
                    else 0 <= value <= 64
                )
            if type(value) is not int or (
                value != getattr(original_extension, field.attribute_name) and not valid
            ):
                raise iPodDBWriteError(
                    "Invalid extended Preferences setting.",
                    code="preferences.invalid_value",
                    field=field.attribute_name,
                    offset=field.schema.offset,
                )
        write_binary_struct_into(output, document.extended_settings)
    return bytes(output)
