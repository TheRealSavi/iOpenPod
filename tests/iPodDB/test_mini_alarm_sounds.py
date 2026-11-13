"""Mini native Playlist identity, sound-selection and toggle vectors."""

import struct

import pytest
from tests.iPodDB.alarm_fixtures import mini_alarm_source

from iPodDB.alarms import parse_preferences_alarm, patch_preferences_alarm
from iPodDB.shared.errors import iPodDBWriteError


@pytest.mark.parametrize("format", ("mini1", "mini"))
@pytest.mark.parametrize("index", (0, 1, 2))
def test_native_sound_selection_writes_paired_id_and_mode(
    format: str, index: int
) -> None:
    identity = 0x0102030405060708 + index
    source = mini_alarm_source()
    result = patch_preferences_alarm(
        parse_preferences_alarm(source, format),
        sound_playlist_id=identity,
        sound_playlist_index=index,
    )
    expected = bytearray(source)
    struct.pack_into("<Q", expected, 0xB24, identity)
    struct.pack_into("<H", expected, 0xB18, 0xA5A0 if index == 0 else 0xA5A4)
    assert result == expected
    assert parse_preferences_alarm(result, format).enabled is True


@pytest.mark.parametrize("lookup,expected", ((-1, 0), (0, 0), (2, 4)))
def test_retained_identity_uses_current_native_lookup(
    lookup: int, expected: int
) -> None:
    source = mini_alarm_source(playlist=0x1234567890ABCDEF)
    result = patch_preferences_alarm(
        parse_preferences_alarm(source, "mini"), enabled=True, playlist_index=lookup
    )
    wanted = bytearray(source)
    struct.pack_into("<H", wanted, 0xB18, 0xA5A0 | expected)
    assert result == wanted


def test_disabling_existing_playlist_needs_no_lookup_and_preserves_identity() -> None:
    source = mini_alarm_source(mode=4, playlist=0x1234567890ABCDEF)
    document = parse_preferences_alarm(source, "mini")
    assert document.can_edit_enabled
    result = patch_preferences_alarm(document, enabled=False)
    assert result == mini_alarm_source(playlist=0x1234567890ABCDEF)


def test_explicit_disabled_wins_after_native_sound_selection() -> None:
    source = mini_alarm_source()
    result = patch_preferences_alarm(
        parse_preferences_alarm(source, "mini"),
        sound_playlist_id=0x0102030405060708,
        sound_playlist_index=1,
        enabled=False,
    )
    assert result == mini_alarm_source(playlist=0x0102030405060708)


def test_new_sound_requires_both_identity_and_index() -> None:
    document = parse_preferences_alarm(mini_alarm_source(), "mini")
    with pytest.raises(iPodDBWriteError):
        patch_preferences_alarm(document, sound_playlist_id=10)
    with pytest.raises(iPodDBWriteError):
        patch_preferences_alarm(document, sound_playlist_index=1)
    with pytest.raises(iPodDBWriteError):
        patch_preferences_alarm(
            document, sound_playlist_id=True, sound_playlist_index=1
        )
