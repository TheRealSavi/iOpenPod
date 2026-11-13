"""Pure interpretation of Classic/Nano tone files captured by Storage.

Names come from file contents, not filenames. Native defaults rename Beep.tone
to a localized resource string; callers must account for that separately.
See docs/research/alarm-sounds-clickwheel-2026-11-13.md for original-instruction
parser probes, catalog ordering, limits and the default-tone distinction.
"""

from dataclasses import dataclass

from iPodDB.alarms._inputs import capture_bytes
from iPodDB.preferences._named_xml import parse_named_xml
from iPodDB.preferences.codec import parse_preferences
from iPodDB.preferences.definitions import (
    NamedPreferencesProfile,
    PreferencesProfile,
    matches_preferences_profile,
)

MAX_ALARM_TONE_BYTES = 1024 * 1024

_CLASSIC_PROFILES = frozenset(
    (
        PreferencesProfile.CLASSIC_6_1_1_2,
        PreferencesProfile.CLASSIC_120GB_2_0_1,
        PreferencesProfile.CLASSIC_UPDATER_35_2_0_4,
        PreferencesProfile.CLASSIC_UPDATER_38_2_0_5,
        PreferencesProfile.NANO_3_1_1_3,
    )
)
_CLASSIC_DEFAULT_NAMES = {
    0: "Beep",
    1: "Bip",
    3: "Signalton",
    4: "Bip",
    5: "Piippaus",
    8: "Bip",
    9: "Beep",
    10: "ビープ音",
    11: "경고음",
    13: "Piep",
    14: "Pip",
    15: "Bip",
    16: "Pip",
    17: "嘟嘟声",
    18: "嗶聲",
    19: "Pípnutí",
    20: "Μπιπ",
    21: "Csipogó",
    22: "sygnał",
    23: "Сигнал",
    24: "Bip",
}
_NANO4_DEFAULT_NAMES = {
    0: "Beep",
    **{k + 1: v for k, v in _CLASSIC_DEFAULT_NAMES.items()},
}
_NANO5_DEFAULT_NAMES = {
    "en-US": "Beep",
    "ar-SA": "صفير",
    "cs-CZ": "Pípnutí",
    "da-DK": "Bip",
    "de-DE": "Signalton",
    "el-GR": "Μπιπ",
    "en-GB": "Beep",
    "es-ES": "Bip",
    "fi-FI": "Piippaus",
    "fr-FR": "Bip",
    "he-IL": "צפצוף",
    "hr-HR": "Zvučni signal",
    "hu-HU": "Csipogó",
    "it-IT": "Beep",
    "ja-JP": "ビープ音",
    "ko-KR": "경고음",
    "nl-NL": "Piep",
    "no-NO": "Pip",
    "pl-PL": "sygnał",
    "pt-BR": "Bipe",
    "pt-PT": "Bip",
    "ro-RO": "Bip",
    "ru-RU": "Сигнал",
    "sk-SK": "Pípnutie",
    "sv-SE": "Pip",
    "th-TH": "บี๊บ",
    "tr-TR": "Bip",
    "zh-CN": "嘟嘟声",
    "zh-HK": "嗶聲",
    "zh-TW": "嗶聲",
}


def default_alarm_tone_name(
    profile: PreferencesProfile | NamedPreferencesProfile,
    language: int | str | None,
) -> str | None:
    """Exact packaged default name, qualified by firmware and saved language.

    Classic/Nano 3-4 take the binary Preferences language code. Nano 5 takes
    the exact General.Language spelling from iPodSettings.xml. No Host locale
    fallback or invented default applies to missing/unrecognized observations.
    """
    if type(profile) is PreferencesProfile and type(language) is int:
        if profile in _CLASSIC_PROFILES:
            return _CLASSIC_DEFAULT_NAMES.get(language)
        if profile is PreferencesProfile.NANO_4_1_0_4:
            return _NANO4_DEFAULT_NAMES.get(language)
    if profile is NamedPreferencesProfile.NANO_5_1_0_2 and isinstance(language, str):
        return _NANO5_DEFAULT_NAMES.get(language)
    return None


def saved_alarm_tone_name(
    data: bytes | bytearray,
    profile: PreferencesProfile | NamedPreferencesProfile,
) -> str | None:
    """Read the default tone name from a qualified captured language store.

    Supply Device/Preferences for Classic/Nano 3-4 or Device/iPodSettings.xml
    for Nano 5. This observes the saved language, not a live firmware refresh.
    Missing, ambiguous, reset-requested or unrecognized state returns None.
    """
    source = capture_bytes(data, label="Alarm language source")
    if type(profile) is PreferencesProfile:
        if not matches_preferences_profile(source, profile):
            return None
        document = parse_preferences(source, profile=profile)
        if document.reset_requested:
            return None
        settings = document.settings
        return (
            default_alarm_tone_name(profile, settings.language_code)
            if settings is not None
            else None
        )
    if profile is not NamedPreferencesProfile.NANO_5_1_0_2:
        return None
    root, issues = parse_named_xml(source)
    if root is None or issues:
        return None
    sections = [node for node in root.children if node.name == "General"]
    if len(sections) != 1 or sections[0].attributes:
        return None
    nodes = [node for node in sections[0].children if node.name == "Language"]
    if len(nodes) != 1:
        return None
    node = nodes[0]
    if node.attributes or node.children or node.complex or node.self_closing:
        return None
    try:
        language = source[node.start : node.end].decode("utf-8")
    except UnicodeDecodeError:
        return None
    return default_alarm_tone_name(profile, language)


@dataclass(frozen=True, slots=True)
class AlarmToneNote:
    frequency: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class AlarmToneDocument:
    source_bytes: bytes
    name: str | None = None
    notes: tuple[AlarmToneNote, ...] = ()
    valid: bool = False
    issues: tuple[str, ...] = ()

    @property
    def selectable(self) -> bool:
        """A native-valid named entry, before collection/identity qualification."""
        return self.valid and bool(self.name) and not self.issues


def _decimal_prefix(text: str, signed: bool) -> int:
    # The native routine accepts ASCII digits at the beginning, with uint32
    # arithmetic. Nano 4/5 consume signs; storage truncates to u16.
    sign = -1 if signed and text.startswith("-") else 1
    if signed:
        text = text.lstrip("+-")
    value = 0
    for character in text:
        if not "0" <= character <= "9":
            break
        value = (value * 10 + ord(character) - 48) & 0xFFFF
    return (sign * value) & 0xFFFF


def parse_alarm_tone(
    data: bytes | bytearray,
    *,
    profile: PreferencesProfile | NamedPreferencesProfile | None = None,
) -> AlarmToneDocument:
    """Retain bytes and reproduce the bounded native text parser.

    CR/LF blank lines are skipped. NUL terminates a line, not the whole file.
    The line reader permits 254 bytes only when followed by EOF/NUL; a longer
    line or a 254-byte line followed by CR/LF stops that read. The header's
    read status is ignored by firmware. At most 1000 notes are consumed.
    Nano 4/5 consume leading signs; Classic/Nano 3 map them to zero. Without
    an exact profile, such operands are observation-only. UTF-8 errors remain
    uninterpreted instead of emulating unsafe decoding.
    """
    source = capture_bytes(data, label="Alarm tone input")
    signed = (
        profile is PreferencesProfile.NANO_4_1_0_4
        or profile is NamedPreferencesProfile.NANO_5_1_0_2
    )
    qualified = signed or (
        type(profile) is PreferencesProfile and profile in _CLASSIC_PROFILES
    )
    if len(source) > MAX_ALARM_TONE_BYTES:
        return AlarmToneDocument(
            source, issues=("Alarm tone exceeds the interpretation limit.",)
        )
    cursor = 0

    def line() -> tuple[bool, bytes]:
        nonlocal cursor
        value = bytearray()
        while cursor < len(source):
            byte = source[cursor]
            cursor += 1
            if byte == 0:
                break
            if len(value) >= 254:
                return False, b""
            if byte in (10, 13):
                if value:
                    break
            else:
                value.append(byte)
        return True, bytes(value)

    _, raw_name = line()
    try:
        name = raw_name.decode("utf-8")
        notes: list[AlarmToneNote] = []
        while True:
            read, raw = line()
            text = raw.decode("utf-8")
            if not read or not text or len(notes) >= 1000:
                break
            first, separator, second = text.partition(" ")
            if not separator:
                return AlarmToneDocument(
                    source,
                    name,
                    tuple(notes),
                    issues=("Alarm tone note has no native space separator.",),
                )
            if not qualified and (
                first.startswith(("+", "-")) or second.startswith(("+", "-"))
            ):
                return AlarmToneDocument(
                    source,
                    name,
                    tuple(notes),
                    issues=("Signed tone notes require an exact firmware profile.",),
                )
            notes.append(
                AlarmToneNote(
                    _decimal_prefix(first, signed), _decimal_prefix(second, signed)
                )
            )
    except UnicodeDecodeError:
        return AlarmToneDocument(
            source, issues=("Alarm tone text is not valid UTF-8.",)
        )
    return AlarmToneDocument(source, name, tuple(notes), valid=True)
