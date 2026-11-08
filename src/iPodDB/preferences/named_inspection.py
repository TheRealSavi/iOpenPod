"""Bounded, non-authorizing observations of native Nano saved preferences.

Registration is evidence of a field's type and constructor bounds, not a full
list of UI values or permission to edit it. Keep unknown text visible. In
particular, firmware's unknown-string/invalid-EQ fallbacks are not normalization
rules for iOpenPod. Inspection never serializes or changes the input bytes.

The ordinary named store is extensionless on Nano 4 and .xml on Nano 5/6/7.
Nano 6 alone has a second timer store, still rooted at ``iPodSettings``. Callers
must select an exact firmware profile and the actual captured store. A filename
or matching XML keys cannot establish a device identity.

Evidence and limitations: preferences-nano567-complete-2026-11-07.md,
preferences-nano567-consumers-2026-11-07.md, and
preferences-nano34-consumers-2026-11-07.md in docs/research.
"""

import math
import re
import struct
from collections import Counter

from whenever import PlainDateTime

from iPodDB.preferences._named_catalog import (
    FIELDS_BY_PROFILE,
    FIRMWARE_CITIES,
    NANO6_TIMER_FIELDS,
    NamedFieldSpec,
)
from iPodDB.preferences._named_xml import NamedNode, parse_named_xml, unsigned_decimal
from iPodDB.preferences.definitions import NamedPreferencesProfile
from iPodDB.preferences.inspection_models import (
    PreferenceInspection,
    PreferenceObservation,
)

_MAX_ROWS = 512
_MAX_TEXT = 512
_MAX_ISSUES = 64
_TIMER = re.compile(r"[0-9]{14}\Z")
_AUTHORABLE_KEYS = {
    "General.Brightness": "brightness",
    "Playback.SoundCheck": "sound_check",
    "Playback.EQ": "eq_preset",
}
_LABELS = {
    "DateTime.TimeZone": "Time zone city",
    "DateTime.TwentyFourHourClock": "24-hour clock",
    "DateTime.UserSet24HourSetting": "Explicit clock format choice",
    "DateTime.WorldClock1TimeZone": "World clock 1 city",
    "DateTime.WorldClock2TimeZone": "World clock 2 city",
    "General.Brightness": "Brightness",
    "Playback.EQ": "Equalizer",
    "Playback.SoundCheck": "Sound Check",
    "Timer.DateTime": "Timer deadline (local calendar)",
    "Timer.SleepiPod": "Sleep iPod when timer ends",
    "Trainer.PedometerActivty": "Pedometer activity",
}
_CATEGORIES = {
    "DateTime": "Date and time",
    "General": "Device",
    "NowPlaying": "Now Playing",
    "Settings": "Device",
    "Temp": "Temporary settings",
    "Trainer": "Fitness",
}
_DETAILS = {
    "General.Clicker": (
        "Canonical on/off strings are case sensitive. Recording consumers can "
        "temporarily suppress clicks; exact audio routing remains unqualified."
    ),
    "Playback.AudiobookSpeed": (
        "Canonical slow/normal/fast strings are case sensitive; exact playback "
        "rate factors have not been qualified."
    ),
    "Playback.Repeat": "Case-sensitive saved playback mode; no unknown-string fallback is applied.",
    "Playback.Shuffle": "Case-sensitive saved playback mode; no unknown-string fallback is applied.",
    "Playback.EQ": (
        "Stored preset ID: 0 is Off; 100..121 are presets. Firmware may display "
        "Off for other IDs; the original unknown ID is retained here."
    ),
    "General.Brightness": "Registered screen-brightness scale 0..100; not measured luminance.",
    "Playback.SoundCheck": "Saved Sound Check enable flag; live adoption is not established by this file.",
    "Playback.VolumeLimit": (
        "Native volume scalar, not percent or dB. Runtime maximum depends on "
        "hardware/region/mode; known clamps use floor(maximum/10)..maximum. "
        "The saved value does not establish the live limit."
    ),
    "DateTime.TwentyFourHourClock": (
        "Saved display format, independent of clock basis or UTC offset. "
        "Language changes can select a locale default on later firmware."
    ),
    "DateTime.UserSet24HourSetting": (
        "Saved explicit-choice flag. On Nano 7/refresh, true preserves the "
        "24-hour choice during a language change; false permits the locale "
        "default to replace it. No Host normalization is performed."
    ),
    "General.Language": (
        "Saved locale string. Listed choices are firmware UI entries, not proof "
        "that every speech payload is installed. Language changes can also "
        "select a compatible speech locale using the radio region."
    ),
    "Accessibility.SpeechLocale": (
        "Saved speech locale. UI membership does not establish installed voice "
        "assets; language and radio region can affect the selected locale."
    ),
    "General.UIRotation": (
        "Registered orientation index 0..3. Physical angles are unresolved. "
        "The low-level byte-12 notification bridge is not a Preferences file offset."
    ),
    "General.RadioRegion": (
        "Native region selector. World Wide (TEST) requires a firmware test "
        "capability; hardware eligibility and live radio adoption are separate."
    ),
    "Radio.LivePause": "Saved Nano 5 radio live-pause flag; buffering details remain unresolved.",
    "General.RadioLivePause": "Saved radio live-pause flag; buffering details remain unresolved.",
    "Timer.SleepiPod": (
        "When true the consumer uses an internal sound sentinel -1. That is "
        "not permission to save -1 in Timer.SoundIndex."
    ),
    "Timer.SoundIndex": "Registered timer sound index 0..24; the complete index-to-sound mapping remains unresolved.",
    "Photos.TimePerSlide": (
        "Stored duration selector, not seconds. Later firmware can force five "
        "seconds when transition 7 (Ken Burns) is selected."
    ),
    "Photos.Transitions": "Saved transition ID; UI choices are narrower than some registered ranges.",
    "Trainer.MeasurementSystem": "Display/input measurement system; Weight remains kilograms and Height remains centimetres internally.",
    "Settings.SoftwareVersion": "Saved software-version metadata; this string does not identify or qualify the connected firmware.",
}


def _preview(text: str) -> str:
    if len(text) <= _MAX_TEXT:
        return text
    return text[:_MAX_TEXT] + "… [display truncated]"


def _city(value: int, profile: NamedPreferencesProfile) -> tuple[str, str, bool]:
    if value == 0:
        return (
            "No city lookup result (0)",
            "Zero has no city record in the native lookup.",
            True,
        )
    city = FIRMWARE_CITIES.get(value)
    if city is None:
        return (
            str(value),
            "Unknown firmware city ID; no timezone conversion is attempted.",
            False,
        )
    label = city.label
    if profile is NamedPreferencesProfile.NANO_5_1_0_2:
        minutes, zone = city.nano5_base_minutes, ""
    elif profile is NamedPreferencesProfile.NANO_6_1_2:
        minutes, zone = city.nano6_base_minutes, city.nano6_zone
    else:
        minutes, zone = city.nano7_base_minutes, city.nano7_zone
        label = city.nano7_label or city.label
    detail = (
        f"Firmware city ID {value}; packaged base offset {minutes:+d} minutes. "
        "This is historical firmware data, not a current UTC offset or an IANA "
        "timezone selection. Seasonal rules, saved bias and a device table override "
        "are not applied."
    )
    if zone:
        detail += f" Packaged record name: {zone}."
    if value == 205 and profile is NamedPreferencesProfile.NANO_5_1_0_2:
        detail += (
            " The lookup contains ID 205 although this firmware registers maximum 204."
        )
    if value == 118 and profile is not NamedPreferencesProfile.NANO_5_1_0_2:
        detail += " The native table binds Cape Town to Africa/Bissau; no geographic correction is invented."
    return label, detail, True


def _timer(text: str) -> tuple[str, str, bool]:
    detail = (
        "Native YYYYMMDDhhmmss civil calendar value, without a zone or UTC "
        "offset. It is not converted using the Host timezone or resolved across DST."
    )
    if text == "":
        return "No saved deadline", detail, True
    if not _TIMER.fullmatch(text):
        return (
            _preview(text),
            detail + " Unrecognized deadline spelling is retained.",
            False,
        )
    try:
        civil = PlainDateTime(
            int(text[:4]),
            int(text[4:6]),
            int(text[6:8]),
            int(text[8:10]),
            int(text[10:12]),
            int(text[12:14]),
        )
    except (ValueError, OverflowError):
        return (
            text,
            detail
            + " Invalid calendar components are retained without blocking loading.",
            False,
        )
    return civil.format_iso(), detail, True


def _interpret(
    spec: NamedFieldSpec, text: str, profile: NamedPreferencesProfile
) -> tuple[str, str, bool]:
    key = spec.key
    detail = _DETAILS.get(
        key, "Registered saved field; complete consumer effects remain unresolved."
    )
    choices = dict(spec.choices)
    if key == "Photos.Transitions" and profile is NamedPreferencesProfile.NANO_6_1_2:
        detail += " Nano 6's legacy label switch also names non-menu values; its current menu contains only 2, 7, 9, 4, 10."
    if key == "Timer.DateTime":
        return _timer(text)
    if spec.kind == "string":
        if text in choices:
            return choices[text], detail, True
        if key == "Settings.SoftwareVersion":
            return _preview(text), detail, True
        return (
            _preview(text),
            detail
            + " The string has no qualified interpretation; it is retained verbatim.",
            False,
        )
    bits = 64 if spec.kind == "int64" else 32
    number = unsigned_decimal(text, bits, boolean=spec.kind == "boolean")
    if number is None:
        return (
            _preview(text),
            detail + " Unrecognized or oversized numeric spelling is retained.",
            False,
        )
    if spec.kind == "boolean":
        if number in (0, 1):
            return ("On" if number else "Off"), detail, True
        return (
            str(number),
            detail + " Noncanonical boolean; no truth-value normalization is applied.",
            False,
        )
    if key in ("Trainer.Weight", "Trainer.Height"):
        # Height's canonical cm interpretation is independently static-qualified:
        # Nano6 getter 083150c0 -> 082c1b74 divides/multiplies by binary64 2.54
        # at 082c1bec (soft-float helpers 0817763c/08177628). Nano7 getter
        # 08449f7c -> 083e5380 uses 2.54 at 083e5414; refresh's getter at
        # 08449f7c -> 083e539c uses 2.54 at 083e5430. Each getter key pointer
        # independently resolves Trainer.Height in the catalog-pinned image.
        # This establishes storage units, not UI bounds or rounding behavior.
        value = struct.unpack("<d", struct.pack("<Q", number))[0]
        unit = "kg" if key == "Trainer.Weight" else "cm"
        detail = (
            f"IEEE-754 binary64 bits 0x{number:016X} in an int64 container. "
            f"Canonical unit: {unit}; measurement-system selection affects display/input. "
            "Human-value bounds and rounding are not fully qualified."
        )
        if not math.isfinite(value) or value <= 0:
            return (
                _preview(text),
                detail
                + " Nonpositive or nonfinite value is retained without a physical interpretation.",
                False,
            )
        return f"{value:.12g} {unit}", detail, True
    # A canonical unsigned word may encode a negative native signed value.
    signed = number if number < 1 << (bits - 1) else number - (1 << bits)
    if key in (
        "DateTime.TimeZone",
        "DateTime.WorldClock1TimeZone",
        "DateTime.WorldClock2TimeZone",
    ):
        return _city(signed, profile)
    if (spec.minimum is not None and signed < spec.minimum) or (
        spec.maximum is not None and signed > spec.maximum
    ):
        return (
            str(signed),
            detail
            + f" Outside registered bounds {spec.minimum}..{spec.maximum}; saved bits are retained.",
            False,
        )
    if str(signed) in choices:
        return choices[str(signed)], detail, True
    if key == "General.Brightness":
        return f"{signed}/100", detail, True
    if key in ("Timer.Hours", "Timer.Minutes"):
        unit = "hours" if key.endswith("Hours") else "minutes"
        return (
            f"{signed} {unit}",
            "Saved timer duration component; not an absolute clock value.",
            True,
        )
    if key == "Trainer.PedometerStepGoal":
        return (
            f"{signed} steps",
            "Saved daily step goal; constructor bounds differ by firmware.",
            True,
        )
    bounds = f" Registered {spec.kind} bounds: {spec.minimum}..{spec.maximum}."
    if key.endswith("BacklightTimer"):
        detail = "Backlight timing/override word; full sentinel and hardware-duration semantics remain unresolved."
        if profile is NamedPreferencesProfile.NANO_5_1_0_2:
            detail += " Nano 5 UI actions emit 0, 2, 5, 10, 15, 20, 30 and -1."
    if key == "Photos.TimePerSlide" and signed == 0:
        detail += " Zero is registered on this model but is not a qualified current UI choice; timing fallback is three seconds."
    return str(signed), detail + bounds, False


def inspect_named_preferences(
    data: bytes, *, profile: NamedPreferencesProfile, timer: bool = False
) -> PreferenceInspection:
    """Describe present scalar fields without granting writes or inventing defaults.

    Every currently registered key is recognized per exact profile/store. Unknown
    keys and values remain observations, with bounded display text. Structural
    ambiguity is reported without selecting a duplicate's winning value. Timer
    and calendar interpretation failures are always nonblocking issues.
    """
    if type(profile) is not NamedPreferencesProfile:
        return PreferenceInspection(
            issues=("An exact named Preferences profile is required.",)
        )
    if type(data) is not bytes:
        return PreferenceInspection(
            issues=("Named Preferences inspection requires captured bytes.",)
        )
    if timer and profile is not NamedPreferencesProfile.NANO_6_1_2:
        return PreferenceInspection(
            issues=("This profile has no qualified separate timer store.",)
        )
    specs = {
        item.key: item
        for item in (NANO6_TIMER_FIELDS if timer else FIELDS_BY_PROFILE[profile])
    }
    root, issues_tuple = parse_named_xml(data)
    if root is None:
        return PreferenceInspection(issues=issues_tuple)
    issues = list(issues_tuple)
    section_counts = Counter(section.name for section in root.children)
    candidates: list[tuple[str, NamedNode, bool]] = []
    for section in root.children:
        node_counts = Counter(node.name for node in section.children)
        ambiguous_section = bool(section.attributes) or section_counts[section.name] > 1
        for node in section.children:
            key = f"{section.name}.{node.name}"
            ambiguous = (
                ambiguous_section
                or node_counts[node.name] > 1
                or bool(node.attributes)
                or bool(node.children)
                or node.complex
            )
            candidates.append((key, node, ambiguous))
    # Prefer recognized fields if unrecognized extension data would fill the
    # display budget. This affects display only, never byte preservation.
    candidates.sort(key=lambda item: item[0] not in specs)
    if len(candidates) > _MAX_ROWS:
        issues.append(
            f"Inspection displays {_MAX_ROWS} fields; {len(candidates) - _MAX_ROWS} additional fields are omitted from display."
        )
    observations: list[PreferenceObservation] = []
    for key, node, ambiguous in candidates[:_MAX_ROWS]:
        raw = data[node.start : node.end].decode("utf-8")
        text = "".join(node.text)
        spec = specs.get(key)
        if ambiguous:
            value, detail, known = (
                _preview(raw),
                "Ambiguous or structured content; no scalar interpretation is selected.",
                False,
            )
            issues.append(f"{_preview(key)} is ambiguous or is not a plain scalar.")
        elif spec is None:
            value, detail, known = (
                _preview(text),
                "No registration is qualified for this key in this exact profile and store.",
                False,
            )
        else:
            value, detail, known = _interpret(spec, text, profile)
            if key == "Timer.DateTime" and not known:
                issues.append(
                    "Timer.DateTime is retained without interpreting an invalid or unknown calendar value."
                )
        if len(raw) > _MAX_TEXT or len(key) > _MAX_TEXT:
            issues.append(
                f"Display text for {_preview(key)} is truncated; captured bytes are unchanged."
            )
        section_name, _, field_name = key.partition(".")
        label = _LABELS.get(
            key, re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", field_name).replace("_", " ")
        )
        observation_key = (
            _AUTHORABLE_KEYS.get(key, key) if spec and not ambiguous else key
        )
        observations.append(
            PreferenceObservation(
                key=_preview(observation_key),
                label=_preview(label),
                raw_value=_preview(raw),
                value=_preview(value),
                category=_CATEGORIES.get(section_name, _preview(section_name)),
                detail=detail,
                known=known,
            )
        )
    if len(issues) > _MAX_ISSUES:
        omitted = len(issues) - _MAX_ISSUES
        issues = [
            *issues[:_MAX_ISSUES],
            f"{omitted} additional inspection issues omitted from display.",
        ]
    return PreferenceInspection(tuple(observations), tuple(issues))


def inspect_named_binary_preferences(
    data: bytes, *, profile: NamedPreferencesProfile
) -> PreferenceInspection:
    """Inspect the separate legacy blob without borrowing any Classic offsets.

    Latest Nano 5/6/7 save exactly 2960 bytes with version 0x3e. Only version is
    semantically complete; the volume snapshot at +8 has partial structural
    meaning. The unresolved range deliberately includes that word. No binary
    framing or value is a prerequisite for reading or authoring named XML.
    """
    if (
        type(profile) is not NamedPreferencesProfile
        or profile is NamedPreferencesProfile.NANO_4_1_0_4
    ):
        return PreferenceInspection(
            issues=("This named profile has no qualified legacy binary inspection.",)
        )
    if type(data) is not bytes or len(data) != 2960:
        return PreferenceInspection(
            issues=(
                "Legacy Nano Preferences require the qualified 2960-byte framing; bytes remain uninterpreted.",
            )
        )
    version = int.from_bytes(data[:4], "little")
    if version != 0x3E:
        return PreferenceInspection(
            issues=(
                f"Legacy Nano Preferences version 0x{version:08X} is unqualified; bytes remain uninterpreted.",
            )
        )
    volume = int.from_bytes(data[8:12], "little")
    return PreferenceInspection(
        observations=(
            PreferenceObservation(
                "legacy.version",
                "Legacy format version",
                "0x0000003E",
                "62 (0x3E)",
                "Legacy binary",
                "File bytes 0..3, little-endian uint32; distinct from named XML.",
            ),
            PreferenceObservation(
                "legacy.volume",
                "Legacy volume snapshot",
                f"0x{volume:08X}",
                str(volume),
                "Legacy binary",
                "File bytes 8..11, little-endian raw word refreshed by the saver. Hardware maximum, physical units and live adoption remain unresolved; not a percentage or VolumeLimit.",
                False,
            ),
            PreferenceObservation(
                "legacy.unresolved",
                "Unresolved binary data",
                data[4:36].hex(" ") + " …",
                "2956 bytes retain unresolved semantics",
                "Legacy binary",
                "Range [4, 2960), including the partially identified volume word. Preview shows the first 32 bytes. Zero bytes and initializer literals do not prove reserved padding; no Classic clock or alarm layout is inherited.",
                False,
            ),
        )
    )
