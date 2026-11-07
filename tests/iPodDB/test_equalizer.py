"""Canonical choices are explicit; existing noncanonical EQ remains unknown."""

import pytest

from iPodDB.library import (
    EqualizerPreset,
    decode_track_equalizer,
    encode_track_equalizer,
)


@pytest.mark.parametrize("preset_id", range(100, 122))
def test_builtin_track_marker_contract(preset_id: int) -> None:
    preset = EqualizerPreset(preset_id)
    marker = f"#!#{preset_id}#!#"
    assert encode_track_equalizer(preset) == marker
    assert decode_track_equalizer(marker) is preset


def test_inheritance_is_separate_from_flat() -> None:
    assert encode_track_equalizer(EqualizerPreset.USE_IPOD_SETTING) == ""
    assert decode_track_equalizer("") is EqualizerPreset.USE_IPOD_SETTING
    assert encode_track_equalizer(EqualizerPreset.FLAT) == "#!#107#!#"


@pytest.mark.parametrize(
    "raw",
    [
        "Rock",
        "116",
        "Custom preset",
        "#!#999#!#",
        "#!#356#!#",
        "#!#116extra#!#",
        " #!#116#!#",
        "#!#000#!#",
    ],
)
def test_noncanonical_values_are_not_silently_reinterpreted(raw: str) -> None:
    assert decode_track_equalizer(raw) is None
