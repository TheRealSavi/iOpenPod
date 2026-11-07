"""Translated preset labels shared by the editor and Track table."""

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication

from iPodDB.library import EqualizerPreset, decode_track_equalizer

_LABELS = {
    EqualizerPreset.USE_IPOD_SETTING: QT_TRANSLATE_NOOP(
        "Equalizer", "Use iPod setting"
    ),
    EqualizerPreset.ACOUSTIC: QT_TRANSLATE_NOOP("Equalizer", "Acoustic"),
    EqualizerPreset.BASS_BOOSTER: QT_TRANSLATE_NOOP("Equalizer", "Bass Booster"),
    EqualizerPreset.BASS_REDUCER: QT_TRANSLATE_NOOP("Equalizer", "Bass Reducer"),
    EqualizerPreset.CLASSICAL: QT_TRANSLATE_NOOP("Equalizer", "Classical"),
    EqualizerPreset.DANCE: QT_TRANSLATE_NOOP("Equalizer", "Dance"),
    EqualizerPreset.DEEP: QT_TRANSLATE_NOOP("Equalizer", "Deep"),
    EqualizerPreset.ELECTRONIC: QT_TRANSLATE_NOOP("Equalizer", "Electronic"),
    EqualizerPreset.FLAT: QT_TRANSLATE_NOOP("Equalizer", "Flat"),
    EqualizerPreset.HIP_HOP: QT_TRANSLATE_NOOP("Equalizer", "Hip Hop"),
    EqualizerPreset.JAZZ: QT_TRANSLATE_NOOP("Equalizer", "Jazz"),
    EqualizerPreset.LATIN: QT_TRANSLATE_NOOP("Equalizer", "Latin"),
    EqualizerPreset.LOUDNESS: QT_TRANSLATE_NOOP("Equalizer", "Loudness"),
    EqualizerPreset.LOUNGE: QT_TRANSLATE_NOOP("Equalizer", "Lounge"),
    EqualizerPreset.PIANO: QT_TRANSLATE_NOOP("Equalizer", "Piano"),
    EqualizerPreset.POP: QT_TRANSLATE_NOOP("Equalizer", "Pop"),
    EqualizerPreset.R_AND_B: QT_TRANSLATE_NOOP("Equalizer", "R & B"),
    EqualizerPreset.ROCK: QT_TRANSLATE_NOOP("Equalizer", "Rock"),
    EqualizerPreset.SMALL_SPEAKERS: QT_TRANSLATE_NOOP("Equalizer", "Small Speakers"),
    EqualizerPreset.SPOKEN_WORD: QT_TRANSLATE_NOOP("Equalizer", "Spoken Word"),
    EqualizerPreset.TREBLE_BOOSTER: QT_TRANSLATE_NOOP("Equalizer", "Treble Booster"),
    EqualizerPreset.TREBLE_REDUCER: QT_TRANSLATE_NOOP("Equalizer", "Treble Reducer"),
    EqualizerPreset.VOCAL_BOOSTER: QT_TRANSLATE_NOOP("Equalizer", "Vocal Booster"),
}


def equalizer_label(preset: EqualizerPreset | None) -> str:
    """Keep protocol numbers and unknown raw values out of ordinary display."""
    if preset is None:
        return QCoreApplication.translate("Equalizer", "Unknown preset (preserved)")
    return QCoreApplication.translate("Equalizer", str(_LABELS[preset]))


def track_equalizer_label(raw: str) -> str:
    return equalizer_label(decode_track_equalizer(raw))
