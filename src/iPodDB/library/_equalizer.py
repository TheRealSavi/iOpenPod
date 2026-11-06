"""Canonical Track EQ choices exported by the public Library interface.

These are preset IDs, not menu positions or DSP section indices. Recognition
is deliberately limited to canonical values, not a firmware-specific emulation
of permissive malformed input. Unknown text must survive unedited.
"""

from enum import IntEnum


class EqualizerPreset(IntEnum):
    USE_IPOD_SETTING = 0
    ACOUSTIC = 100
    BASS_BOOSTER = 101
    BASS_REDUCER = 102
    CLASSICAL = 103
    DANCE = 104
    DEEP = 105
    ELECTRONIC = 106
    FLAT = 107
    HIP_HOP = 108
    JAZZ = 109
    LATIN = 110
    LOUDNESS = 111
    LOUNGE = 112
    PIANO = 113
    POP = 114
    R_AND_B = 115
    ROCK = 116
    SMALL_SPEAKERS = 117
    SPOKEN_WORD = 118
    TREBLE_BOOSTER = 119
    TREBLE_REDUCER = 120
    VOCAL_BOOSTER = 121


def encode_track_equalizer(preset: EqualizerPreset) -> str:
    """Encode an explicit choice for the existing MHOD7 text writer."""
    return "" if preset is EqualizerPreset.USE_IPOD_SETTING else f"#!#{preset.value}#!#"


_CANONICAL_PRESETS = {
    encode_track_equalizer(preset): preset for preset in EqualizerPreset
}


def decode_track_equalizer(raw: str) -> EqualizerPreset | None:
    """Recognize canonical saved text without normalizing unknown values."""
    return _CANONICAL_PRESETS.get(raw)
