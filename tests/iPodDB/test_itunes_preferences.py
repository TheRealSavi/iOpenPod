"""Authored golden offsets, preservation and profile tests for binary iTunesPrefs."""

from dataclasses import replace

import pytest

from iPodDB.preferences import (
    ITunesPreferences,
    ITunesPreferencesProfile,
    PreferenceToggle,
    ShuffleVoiceOverPreferences,
    SyncMode,
    SyncSelection,
    parse_itunes_preferences,
    write_itunes_preferences,
)
from iPodDB.shared.errors import iPodDBParseError, iPodDBWriteError


def _source(size: int = 1232) -> bytes:
    data = bytearray((index * 31 + 17) % 256 for index in range(size))
    # A later observed header, followed by synthetic values and opaque bytes.
    data[:8] = b"frpd\x01\x00\x19\x00"
    for offset in (8, 9, 10, 11, 31, 34, 49, 52, 55, 72, 73, 89, 90, 124):
        data[offset] = 1
    data[12:20] = b"libraryA"
    data[96:104] = b"libraryB"
    data[104:108] = b"\x34\x12\x78\x56"
    return bytes(data)


def _with_field(
    settings: ITunesPreferences, name: str, value: object
) -> ITunesPreferences:
    # Parametrized field names (including deliberately invalid runtime values).
    edited = replace(settings)
    object.__setattr__(edited, name, value)
    return edited


@pytest.mark.parametrize("size", (236, 249, 250, 1232, 2048))
def test_complete_prefix_and_extended_file_roundtrip(size: int) -> None:
    source = _source(size)
    document = parse_itunes_preferences(source)
    assert document.settings == ITunesPreferences(
        setup_completed=1,
        open_itunes_on_attach=1,
        music_sync_mode=1,
        music_sync_selection=1,
        library_link_id=b"libraryA",
        disk_use_enabled=1,
        sync_checked_only=1,
        show_artwork=1,
        sync_photos=1,
        include_original_photos=1,
        transcode_to_128kbps_aac=1,
        keep_in_source_list=1,
        podcast_sync_selection=1,
        podcast_sync_mode=1,
        secondary_library_link_id=b"libraryB",
        shuffle_music_capacity_raw=0x1234,
        shuffle_file_capacity_raw=0x5678,
        sound_check_enabled=1,
    )
    assert document.voice_over is None
    assert write_itunes_preferences(document) == source


@pytest.mark.parametrize(
    "name,offset,value",
    (
        ("setup_completed", 8, PreferenceToggle.DISABLED),
        ("open_itunes_on_attach", 9, PreferenceToggle.DISABLED),
        ("music_sync_mode", 10, SyncMode.MANUAL),
        ("music_sync_selection", 11, SyncSelection.SELECTED),
        ("disk_use_enabled", 31, PreferenceToggle.DISABLED),
        ("sync_checked_only", 34, PreferenceToggle.DISABLED),
        ("show_artwork", 49, PreferenceToggle.DISABLED),
        ("sync_photos", 52, PreferenceToggle.DISABLED),
        ("include_original_photos", 55, PreferenceToggle.DISABLED),
        ("transcode_to_128kbps_aac", 72, PreferenceToggle.DISABLED),
        ("keep_in_source_list", 73, PreferenceToggle.DISABLED),
        ("podcast_sync_selection", 89, SyncSelection.SELECTED),
        ("podcast_sync_mode", 90, SyncMode.MANUAL),
        ("sound_check_enabled", 124, PreferenceToggle.DISABLED),
    ),
)
def test_each_setting_edit_changes_only_its_documented_byte(
    name: str,
    offset: int,
    value: int,
) -> None:
    source = _source()
    document = parse_itunes_preferences(source)
    desired = replace(document, settings=_with_field(document.settings, name, value))
    expected = bytearray(source)
    expected[offset] = value
    output = write_itunes_preferences(desired)
    assert output == expected
    assert getattr(parse_itunes_preferences(output).settings, name) == value
    assert write_itunes_preferences(document) == source


@pytest.mark.parametrize(
    "name,offset", (("library_link_id", 12), ("secondary_library_link_id", 96))
)
def test_link_ids_are_exact_bytes_and_not_implicitly_mirrored(
    name: str, offset: int
) -> None:
    source = _source()
    document = parse_itunes_preferences(source)
    edited = replace(
        document, settings=_with_field(document.settings, name, b"newlink!")
    )
    expected = bytearray(source)
    expected[offset : offset + 8] = b"newlink!"
    assert write_itunes_preferences(edited) == expected
    for invalid in (b"short", b"too many bytes", "libraryA", bytearray(b"libraryA")):
        with pytest.raises(iPodDBWriteError):
            write_itunes_preferences(
                replace(
                    document, settings=_with_field(document.settings, name, invalid)
                )
            )


def test_unknown_flags_survive_unrelated_edits_and_can_be_replaced_explicitly() -> None:
    source = bytearray(_source())
    source[9] = 0xFE
    document = parse_itunes_preferences(source)
    assert document.settings.open_itunes_on_attach == 0xFE
    assert write_itunes_preferences(document) == source
    edited = replace(
        document, settings=replace(document.settings, music_sync_mode=SyncMode.MANUAL)
    )
    expected = bytearray(source)
    expected[10] = 0
    assert write_itunes_preferences(edited) == expected
    expected[9] = 0
    edited = replace(edited, settings=replace(edited.settings, open_itunes_on_attach=0))
    assert write_itunes_preferences(edited) == expected


@pytest.mark.parametrize(
    "value", (-1, 2, 256, True, False, 1.0, None, "1", SyncSelection.ALL)
)
def test_new_invalid_flag_values_and_wrong_types_are_rejected(value: object) -> None:
    document = parse_itunes_preferences(_source())
    settings = replace(document.settings)
    object.__setattr__(settings, "open_itunes_on_attach", value)
    with pytest.raises(iPodDBWriteError):
        write_itunes_preferences(replace(document, settings=settings))


@pytest.mark.parametrize("name", ("music_sync_selection", "podcast_sync_selection"))
def test_selection_zero_is_unknown_even_when_sync_is_manual(name: str) -> None:
    document = parse_itunes_preferences(_source())
    settings = _with_field(
        replace(document.settings, music_sync_mode=0, podcast_sync_mode=0), name, 0
    )
    with pytest.raises(iPodDBWriteError):
        write_itunes_preferences(replace(document, settings=settings))


@pytest.mark.parametrize(
    "name", ("shuffle_music_capacity_raw", "shuffle_file_capacity_raw")
)
def test_unverified_capacity_units_do_not_gain_edit_semantics(name: str) -> None:
    document = parse_itunes_preferences(_source())
    with pytest.raises(iPodDBWriteError) as error:
        write_itunes_preferences(
            replace(document, settings=_with_field(document.settings, name, 0))
        )
    assert error.value.code == "itunes_preferences.observation_only"


def test_voiceover_requires_shuffle_profile_and_available_byte() -> None:
    source = bytearray(_source())
    source[249] = 3  # foo_dop treats any nonzero value as enabled.
    standard = parse_itunes_preferences(source)
    with pytest.raises(iPodDBWriteError):
        write_itunes_preferences(
            replace(standard, voice_over=ShuffleVoiceOverPreferences(0))
        )
    document = parse_itunes_preferences(
        source, profile=ITunesPreferencesProfile.SHUFFLE
    )
    assert document.voice_over is not None and document.voice_over.enabled
    assert write_itunes_preferences(document) == source
    expected = bytearray(source)
    expected[249] = 0
    assert (
        write_itunes_preferences(
            replace(document, voice_over=ShuffleVoiceOverPreferences(0))
        )
        == expected
    )
    for invalid in (-1, 2, 256):
        with pytest.raises(iPodDBWriteError):
            write_itunes_preferences(
                replace(document, voice_over=ShuffleVoiceOverPreferences(invalid))
            )
    short = parse_itunes_preferences(
        _source(236), profile=ITunesPreferencesProfile.SHUFFLE
    )
    assert short.voice_over is None
    with pytest.raises(iPodDBWriteError):
        write_itunes_preferences(
            replace(short, voice_over=ShuffleVoiceOverPreferences(1))
        )
    with pytest.raises(iPodDBWriteError):
        write_itunes_preferences(replace(document, voice_over=None))


@pytest.mark.parametrize(
    "source", (b"", b"frpd", b"frpd" + bytes(231), b"abcd" + bytes(1232))
)
def test_invalid_marker_or_truncated_prefix_is_not_editable(source: bytes) -> None:
    with pytest.raises(iPodDBParseError):
        parse_itunes_preferences(source)
    valid = parse_itunes_preferences(_source())
    with pytest.raises(iPodDBWriteError):
        write_itunes_preferences(replace(valid, source_bytes=source))


def test_bytearray_is_snapshotted_and_unknown_header_bytes_are_not_normalized() -> None:
    source = bytearray(_source())
    source[4:8] = b"\xff\x80\x01\x02"
    original = bytes(source)
    document = parse_itunes_preferences(source)
    source[10] = 0
    assert write_itunes_preferences(document) == original
