"""Read-only observations of exact, independently studied binary Preferences.

All observations describe the captured source, including when an editor has
pending changes. This is deliberately separate from the writer's allowlist and
from firmware adoption. Shared offsets alone never choose a profile or domain.
Partial clock fields remain raw observations; no Host clock, date conversion or
timezone database is consulted. Malformed optional state produces bounded issues
and never an exception solely because its date/time meaning is unknown.
"""

from iPodDB.preferences._binary_inspection_data import (
    BINARY_PROFILE_EVIDENCE,
    BinaryObservationField,
)
from iPodDB.preferences.definitions import PreferencesProfile, definition_for_size
from iPodDB.preferences.inspection_models import (
    PreferenceInspection,
    PreferenceObservation,
)
from iPodDB.preferences.models import PreferencesDocument
from iPodDB.preferences.timezones import (
    CITY_TIMEZONE_NAMES,
    CLASSIC_UNRESOLVED_CITY_IDS,
    TIME_ZONE_ALIASES,
)

_MAX_ISSUES = 16
_MAX_PREVIEW_BYTES = 24
_ENGLISH_EQ_NAMES = frozenset(
    (
        "Acoustic",
        "Bass Booster",
        "Bass Reducer",
        "Classical",
        "Dance",
        "Deep",
        "Electronic",
        "Flat",
        "Hip Hop",
        "Jazz",
        "Latin",
        "Loudness",
        "Lounge",
        "Piano",
        "Pop",
        "R&B",
        "Rock",
        "Small Speakers",
        "Spoken Word",
        "Treble Booster",
        "Treble Reducer",
        "Vocal Booster",
    )
)


def _raw(source: bytes, field: BinaryObservationField) -> str:
    data = source[field.offset : field.offset + field.size]
    if field.kind in ("early_transition", "later_transition"):
        return f"Mode 0x{source[0xB3B]:02X}, effect 0x{source[0xB49]:02X}"
    if field.size <= 8:
        integer = int.from_bytes(data, "little", signed=field.signed)
        return f"{integer} (0x{int.from_bytes(data, 'little'):0{field.size * 2}X})"
    preview = data[:_MAX_PREVIEW_BYTES].hex(" ").upper()
    return f"{preview} … ({len(data)} bytes)"


def _lookup(value: int, field: BinaryObservationField) -> tuple[str, bool]:
    label = dict(field.choices).get(value)
    return (label, True) if label is not None else (f"Unknown ({value})", False)


def _mask(value: int, field: BinaryObservationField) -> tuple[str, bool]:
    selected: list[str] = []
    known_mask = 0
    for mask, label in field.choices:
        known_mask |= mask
        if value & mask:
            selected.append(label)
    residual = value & ~known_mask
    result = ", ".join(selected) if selected else "No named entries selected"
    if residual:
        result += f"; unknown bits 0x{residual:08X}"
    return result, residual == 0


def _utf16(source: bytes, field: BinaryObservationField) -> tuple[str, bool]:
    count = int.from_bytes(source[0x8EA:0x8EC], "little")
    if count > field.size // 2:
        return f"Unknown (name length {count} exceeds the saved buffer)", False
    data = source[field.offset : field.offset + count * 2]
    try:
        name = data.decode("utf-16-le")
    except UnicodeDecodeError:
        return "Unknown (invalid UTF-16 preset name)", False
    if "\0" in name:
        return "Unknown (embedded NUL in the counted preset name)", False
    # Keep source control characters out of UI layout; this changes no bytes.
    name = " ".join(name.split())
    if source[0x8E0] == 0:
        return (f"Off; retained name: {name}" if name else "Off"), True
    if source[0x8E0] != 1:
        return f"{name or 'Empty name'}; noncanonical EQ enable flag", False
    language = int.from_bytes(source[0xAF8:0xAFC], "little")
    if language == 0 and name in _ENGLISH_EQ_NAMES:
        return name, True
    return f"{name or 'Empty preset name'}; compiled preset match unverified", False


def _transition(
    source: bytes, value: int, field: BinaryObservationField
) -> tuple[str, bool]:
    mode = source[0xB3B]
    if field.kind == "later_transition":
        if mode == 255:
            return "Random", True
        label, known = _lookup(value, field)
        if mode != 254:
            return f"{label}; noncanonical mode {mode}", False
        return label, known
    if mode == 0:
        return "Off", True
    if mode == 1:
        return "Random", True
    label, known = _lookup(value, field)
    if mode != 2:
        return f"{label}; unknown mode {mode}", False
    # FF is an Off/Random sentinel, not a named specific transition.
    return (
        (f"Unknown specific effect ({value})", False)
        if value == 255
        else (label, known)
    )


def _interpret(source: bytes, field: BinaryObservationField) -> tuple[str, bool]:
    value = int.from_bytes(
        source[field.offset : field.offset + field.size], "little", signed=field.signed
    )
    match field.kind:
        case "version":
            return f"0x{value:X}", True
        case "reset":
            return ("Defaults requested" if value else "Load saved values"), True
        case "shuffle":
            albums = source[0x8A]
            if value not in (0, 1) or albums not in (0, 1):
                return f"Unknown (enabled {value}, albums {albums})", False
            return ("Off" if value == 0 else "Albums" if albums else "Songs"), True
        case "clicker":
            label, known = _lookup(value & 3, field)
            upper = value & ~3
            return (f"{label}; unknown bits 0x{upper:08X}" if upper else label), (
                known and not upper
            )
        case "mask":
            return _mask(value, field)
        case "clock_format":
            label = "24-hour" if value & 1 else "12-hour"
            label += "; Time in Title " + ("On" if value & 2 else "Off")
            upper = value & ~3
            return (f"{label}; unknown bits 0x{upper:X}" if upper else label), not upper
        case "utf16":
            return _utf16(source, field)
        case "mini_zone":
            if not 1 <= value <= 50:
                return f"Unknown selector ({value})", False
            pair, dst = divmod(value - 1, 2)
            hours = pair - 12 + dst
            return f"UTC{hours:+03d}:00; saved DST {'On' if dst else 'Off'}", True
        case "city":
            if value == 0 or value in CLASSIC_UNRESOLVED_CITY_IDS:
                return f"City {value}; geographic timezone unresolved", False
            zone = CITY_TIMEZONE_NAMES.get(value)
            if zone is None:
                return f"Unknown city ({value})", False
            return f"City {value}; {TIME_ZONE_ALIASES.get(zone, zone)}", True
        case "percentage":
            return (
                (f"{value}%", True) if value <= 100 else (f"Unknown ({value})", False)
            )
        case "balance":
            if value > 100:
                return f"Unknown ({value}; setter clamps to 0-100)", False
            return f"{value} (50 is centered)", True
        case "boolean":
            return ("Enabled" if value else "Disabled"), True
        case "early_transition" | "later_transition":
            return _transition(source, value, field)
        case _:
            if field.choices:
                return _lookup(value, field)
            return str(value), not field.partial


def _unmapped(
    size: int, fields: tuple[BinaryObservationField, ...]
) -> PreferenceObservation:
    covered = set[int]()
    for field in fields:
        covered.update(range(field.offset, field.offset + field.size))
    ranges: list[tuple[int, int]] = []
    for offset in range(size):
        if offset in covered:
            continue
        if ranges and ranges[-1][1] == offset:
            ranges[-1] = ranges[-1][0], offset + 1
        else:
            ranges.append((offset, offset + 1))
    count = sum(end - start for start, end in ranges)
    preview = ", ".join(f"0x{start:X}-0x{end - 1:X}" for start, end in ranges[:8])
    if len(ranges) > 8:
        preview += f", and {len(ranges) - 8} more ranges"
    return PreferenceObservation(
        "unknown_data",
        "Unknown Data",
        f"{count} bytes in {len(ranges)} ranges",
        "Retained without interpretation",
        "Internal",
        f"Ranges not projected as named fields: {preview or 'none'}. "
        "Partly understood named fields are described separately. No bytes are inferred to be padding.",
        False,
    )


def inspect_binary_preferences(document: PreferencesDocument) -> PreferenceInspection:
    """Observe saved bytes under an exact asserted profile, without authorizing edits.

    Generic layouts, similar sizes and wrong versions are not fallback profiles.
    Reset-request files are readable but explicitly described as discardable saved
    state. Interpretation issues stay within this optional observation result.
    """
    if type(document.profile) is not PreferencesProfile:
        return PreferenceInspection(
            issues=("Binary preference profile is unqualified.",)
        )
    evidence = BINARY_PROFILE_EVIDENCE.get(document.profile)
    source = document.source_bytes
    definition = definition_for_size(len(source), document.profile)
    if (
        evidence is None
        or definition is None
        or definition.format_version is None
        or document.layout is not definition.layout
        or type(document.settings) is not definition.settings_type
        or not definition.matches(source)
    ):
        return PreferenceInspection(
            issues=(
                "No exact studied profile, version and extent match these saved bytes.",
            )
        )
    issues: list[str] = []
    if document.reset_requested:
        issues.append(
            "Reset requested: firmware may discard these saved values and use defaults."
        )
    if document.preference_edits:
        issues.append("Observations describe saved source bytes, before pending edits.")
    observations: list[PreferenceObservation] = []
    omitted_issues = False
    for field in evidence.fields:
        value, known = _interpret(source, field)
        detail = (
            f"File 0x{field.offset:X}, {field.size} byte{'s' if field.size != 1 else ''}. "
            f"{field.detail}"
        )
        if field.partial:
            detail += " Complete semantics remain partly understood."
        observations.append(
            PreferenceObservation(
                field.key,
                field.label,
                _raw(source, field),
                value,
                field.category,
                detail,
                known,
            )
        )
        # A partial but readable integer is not an error. Unknown enumerations,
        # malformed strings and residual flags are useful bounded diagnostics.
        if not known and (field.kind != "integer" or field.choices):
            if len(issues) < _MAX_ISSUES:
                issues.append(f"{field.label}: {value}. Raw bytes are retained.")
            else:
                omitted_issues = True
    if omitted_issues:
        issues.append("Additional unknown values are shown in the observations.")
    observations.append(_unmapped(len(source), evidence.fields))
    return PreferenceInspection(tuple(observations), tuple(issues))
