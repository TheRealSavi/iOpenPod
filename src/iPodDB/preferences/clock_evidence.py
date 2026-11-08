"""Saved Nano clock identity, separate from firmware rules and live clock state.

This reader selects only the primary ``DateTime.TimeZone`` city. World-clock
selectors and clock-display flags do not identify the primary clock. The exact
profile comes from the caller; XML version or SoftwareVersion cannot establish
firmware identity. Unknown, ambiguous and malformed input remains nonblocking.

``iana_timezone`` is an explicit Host interpretation policy, not proof that the
device evaluates the same historical rules. Later Nano images supply a packaged
zone name; Nano 5 supplies a city label and offset code, so its geographical map
is audited separately. Packaged base offsets are observations only: they omit
seasonal correction and do not establish the live saved bias. Neither they nor
an unresolved city authorize a fixed-offset fallback, a clock write or a manual
DST adjustment. Device iPodTZData.dat overrides are outside this reader.

Native evidence: docs/research/preferences-nano567-consumers-2026-11-07.md and
the source/receipt hashes retained in _named_catalog.py. The Nano 5 geographical
policy below was checked by city label against IANA's public-domain zone1970.tab,
zone.tab and backward (read 2026-11-07):
https://data.iana.org/time-zones/tzdb/zone1970.tab
https://data.iana.org/time-zones/tzdb/zone.tab
https://data.iana.org/time-zones/tzdb/backward
Those files qualify zone identities, not Apple's historical DST implementation.
"""

from dataclasses import dataclass, replace
from typing import Literal

from iPodDB.preferences._named_catalog import FIRMWARE_CITIES
from iPodDB.preferences._named_xml import parse_named_xml, unsigned_decimal
from iPodDB.preferences.definitions import NamedPreferencesProfile


@dataclass(frozen=True, slots=True)
class NamedClockEvidence:
    """Immutable clock evidence without timezone conversion or write authority.

    ``raw_value`` retains the exact unique scalar bytes, including whitespace
    and entity spelling. It is absent when no unique plain scalar is available.
    ``firmware_timezone_name`` is the original packaged record, even when it is
    contradictory and ``iana_timezone`` is withheld. A base offset is never an
    effective offset. ``profile`` is None only for an invalid caller assertion.
    """

    profile: NamedPreferencesProfile | None
    raw_value: bytes | None = None
    city_id: int | None = None
    city_label: str | None = None
    iana_timezone: str | None = None
    firmware_timezone_name: str | None = None
    firmware_base_offset_minutes: int | None = None
    interpretation: Literal["unresolved", "firmware_record", "geographical_city"] = (
        "unresolved"
    )
    detail: str = ""
    issues: tuple[str, ...] = ()


# This is deliberately an explicit (ID, source-label, zone) catalog, not an
# ordinal join or reuse of Classic CITY_TIMEZONE_NAMES. The Nano 5 native labels
# were audited individually. Corrections from the older shared mapping include
# Calgary, Ottawa, Geneva, Ljubljana, Zagreb, Ankara, Tashkent, Canberra and Sydney.
# Manchester (38) is withheld: -300 minutes contradicts the old London guess and
# the label alone cannot distinguish the British and American cities. Alias
# spellings are modernized only in this Host geographical policy, never on disk.
_NANO5_GEOGRAPHICAL_CITIES: dict[int, tuple[str, str]] = {
    1: ("California", "America/Los_Angeles"),
    2: ("Chicago", "America/Chicago"),
    3: ("Honolulu", "Pacific/Honolulu"),
    4: ("Anchorage", "America/Anchorage"),
    5: ("Cupertino", "America/Los_Angeles"),
    6: ("Los Angeles", "America/Los_Angeles"),
    7: ("Portland", "America/Los_Angeles"),
    8: ("San Diego", "America/Los_Angeles"),
    9: ("San Francisco", "America/Los_Angeles"),
    10: ("Seattle", "America/Los_Angeles"),
    11: ("Vancouver", "America/Vancouver"),
    12: ("Calgary", "America/Edmonton"),
    13: ("Denver", "America/Denver"),
    14: ("Phoenix", "America/Phoenix"),
    15: ("Salt Lake City", "America/Denver"),
    16: ("Austin", "America/Chicago"),
    17: ("Dallas", "America/Chicago"),
    18: ("Guatemala", "America/Guatemala"),
    19: ("Managua", "America/Managua"),
    20: ("Memphis", "America/Chicago"),
    21: ("Mexico City", "America/Mexico_City"),
    22: ("Minneapolis", "America/Chicago"),
    23: ("Regina", "America/Regina"),
    24: ("San José", "America/Costa_Rica"),
    25: ("San Salvador", "America/El_Salvador"),
    26: ("St. Louis", "America/Chicago"),
    27: ("Tegucigalpa", "America/Tegucigalpa"),
    28: ("Winnipeg", "America/Winnipeg"),
    29: ("Atlanta", "America/New_York"),
    30: ("Bogotá", "America/Bogota"),
    31: ("Boston", "America/New_York"),
    32: ("Columbus", "America/New_York"),
    33: ("Detroit", "America/Detroit"),
    34: ("Havana", "America/Havana"),
    35: ("Indianapolis", "America/Indiana/Indianapolis"),
    36: ("Knoxville", "America/New_York"),
    37: ("Lima", "America/Lima"),
    39: ("Miami", "America/New_York"),
    40: ("Montréal", "America/Toronto"),
    41: ("New York", "America/New_York"),
    42: ("Ottawa", "America/Toronto"),
    43: ("Panama", "America/Panama"),
    44: ("Philadelphia", "America/New_York"),
    45: ("Port-au-Prince", "America/Port-au-Prince"),
    46: ("Quito", "America/Guayaquil"),
    47: ("Toronto", "America/Toronto"),
    48: ("Washington, D.C.", "America/New_York"),
    49: ("Asunción", "America/Asuncion"),
    50: ("Caracas", "America/Caracas"),
    51: ("Georgetown", "America/Guyana"),
    52: ("Halifax", "America/Halifax"),
    53: ("La Paz", "America/La_Paz"),
    54: ("San Juan", "America/Puerto_Rico"),
    55: ("Santiago", "America/Santiago"),
    56: ("Santo Domingo", "America/Santo_Domingo"),
    57: ("St. John's", "America/St_Johns"),
    58: ("Brasília", "America/Sao_Paulo"),
    59: ("Buenos Aires", "America/Argentina/Buenos_Aires"),
    60: ("Cayenne", "America/Cayenne"),
    61: ("Montevideo", "America/Montevideo"),
    62: ("Nuuk", "America/Nuuk"),
    63: ("Paramaribo", "America/Paramaribo"),
    64: ("Recife", "America/Recife"),
    65: ("Rio de Janeiro", "America/Sao_Paulo"),
    66: ("São Paulo", "America/Sao_Paulo"),
    67: ("Grytviken", "Atlantic/South_Georgia"),
    68: ("Ponta Delgada", "Atlantic/Azores"),
    69: ("Cork", "Europe/Dublin"),
    70: ("Accra", "Africa/Accra"),
    71: ("Bamako", "Africa/Bamako"),
    72: ("Cardiff", "Europe/London"),
    73: ("Conakry", "Africa/Conakry"),
    74: ("Dakar", "Africa/Dakar"),
    75: ("Dublin", "Europe/Dublin"),
    76: ("Edinburgh", "Europe/London"),
    77: ("Freetown", "Africa/Freetown"),
    78: ("Lisbon", "Europe/Lisbon"),
    79: ("London", "Europe/London"),
    80: ("Monrovia", "Africa/Monrovia"),
    81: ("Nouakchott", "Africa/Nouakchott"),
    82: ("Ouagadougou", "Africa/Ouagadougou"),
    83: ("Reykjavík", "Atlantic/Reykjavik"),
    84: ("Algiers", "Africa/Algiers"),
    85: ("Amsterdam", "Europe/Amsterdam"),
    86: ("Bangui", "Africa/Bangui"),
    87: ("Belgrade", "Europe/Belgrade"),
    88: ("Berlin", "Europe/Berlin"),
    89: ("Brussels", "Europe/Brussels"),
    90: ("Budapest", "Europe/Budapest"),
    91: ("Copenhagen", "Europe/Copenhagen"),
    92: ("Douala", "Africa/Douala"),
    93: ("Geneva", "Europe/Zurich"),
    94: ("Kinshasa", "Africa/Kinshasa"),
    95: ("Lagos", "Africa/Lagos"),
    96: ("Ljubljana", "Europe/Ljubljana"),
    97: ("Luanda", "Africa/Luanda"),
    98: ("Madrid", "Europe/Madrid"),
    99: ("Munich", "Europe/Berlin"),
    100: ("Ndjamena", "Africa/Ndjamena"),
    101: ("Oslo", "Europe/Oslo"),
    102: ("Paris", "Europe/Paris"),
    103: ("Prague", "Europe/Prague"),
    104: ("Rabat", "Africa/Casablanca"),
    105: ("Roma (Rome)", "Europe/Rome"),
    106: ("Stockholm", "Europe/Stockholm"),
    107: ("Tripoli", "Africa/Tripoli"),
    108: ("Tunis", "Africa/Tunis"),
    109: ("Vienna", "Europe/Vienna"),
    110: ("Warsaw", "Europe/Warsaw"),
    111: ("Zagreb", "Europe/Zagreb"),
    112: ("Zurich", "Europe/Zurich"),
    113: ("Amman", "Asia/Amman"),
    114: ("Ankara", "Europe/Istanbul"),
    115: ("Beirut", "Asia/Beirut"),
    116: ("Bucharest", "Europe/Bucharest"),
    117: ("Cairo", "Africa/Cairo"),
    118: ("Cape Town", "Africa/Johannesburg"),
    119: ("Harare", "Africa/Harare"),
    120: ("Helsinki", "Europe/Helsinki"),
    121: ("Istanbul", "Europe/Istanbul"),
    122: ("Jerusalem", "Asia/Jerusalem"),
    123: ("Khartoum", "Africa/Khartoum"),
    124: ("Kiev", "Europe/Kyiv"),
    125: ("Lusaka", "Africa/Lusaka"),
    126: ("Maputo", "Africa/Maputo"),
    127: ("Sofia", "Europe/Sofia"),
    128: ("Addis Ababa", "Africa/Addis_Ababa"),
    129: ("Antananarivo", "Indian/Antananarivo"),
    130: ("Asmera", "Africa/Asmara"),
    131: ("Baghdad", "Asia/Baghdad"),
    132: ("Damascus", "Asia/Damascus"),
    133: ("Dar es Salaam", "Africa/Dar_es_Salaam"),
    134: ("Djibouti", "Africa/Djibouti"),
    135: ("Doha", "Asia/Qatar"),
    136: ("Kampala", "Africa/Kampala"),
    137: ("Manama", "Asia/Bahrain"),
    138: ("Mecca", "Asia/Riyadh"),
    139: ("Mogadishu", "Africa/Mogadishu"),
    140: ("Moscow", "Europe/Moscow"),
    141: ("Nairobi", "Africa/Nairobi"),
    142: ("Riyadh", "Asia/Riyadh"),
    143: ("Sanaa", "Asia/Aden"),
    144: ("St. Petersburg", "Europe/Moscow"),
    145: ("Volgograd", "Europe/Volgograd"),
    146: ("Abu Dhabi", "Asia/Dubai"),
    147: ("Muscat", "Asia/Muscat"),
    148: ("Port Louis", "Indian/Mauritius"),
    149: ("Victoria", "Indian/Mahe"),
    150: ("Islamabad", "Asia/Karachi"),
    151: ("Male", "Indian/Maldives"),
    152: ("Tashkent", "Asia/Tashkent"),
    153: ("Yekaterinburg", "Asia/Yekaterinburg"),
    154: ("Omsk", "Asia/Omsk"),
    155: ("Dhaka", "Asia/Dhaka"),
    156: ("Novosibirsk", "Asia/Novosibirsk"),
    157: ("Beijing", "Asia/Shanghai"),
    158: ("Canton", "Asia/Shanghai"),
    159: ("Hong Kong", "Asia/Hong_Kong"),
    160: ("Kuala Lumpur", "Asia/Kuala_Lumpur"),
    161: ("Manila", "Asia/Manila"),
    162: ("Perth", "Australia/Perth"),
    163: ("Shanghai", "Asia/Shanghai"),
    164: ("Singapore", "Asia/Singapore"),
    165: ("Taipei", "Asia/Taipei"),
    166: ("Tientsin", "Asia/Shanghai"),
    167: ("Ulaanbaatar", "Asia/Ulaanbaatar"),
    168: ("Darwin", "Australia/Darwin"),
    169: ("Adelaide", "Australia/Adelaide"),
    170: ("Brisbane", "Australia/Brisbane"),
    171: ("Canberra", "Australia/Sydney"),
    172: ("Guam", "Pacific/Guam"),
    173: ("Hobart", "Australia/Hobart"),
    174: ("Melbourne", "Australia/Melbourne"),
    175: ("Sydney", "Australia/Sydney"),
    176: ("Vladivostok", "Asia/Vladivostok"),
    177: ("Magadan", "Asia/Magadan"),
    178: ("Nouméa", "Pacific/Noumea"),
    179: ("Anadyr", "Asia/Anadyr"),
    180: ("Wellington", "Pacific/Auckland"),
    181: ("Adak", "America/Adak"),
    182: ("Pago Pago", "Pacific/Pago_Pago"),
    183: ("Tehran", "Asia/Tehran"),
    184: ("Kabul", "Asia/Kabul"),
    185: ("Chennai (Madras)", "Asia/Kolkata"),
    186: ("Colombo", "Asia/Colombo"),
    187: ("Kolkata (Calcutta)", "Asia/Kolkata"),
    188: ("Mumbai (Bombay)", "Asia/Kolkata"),
    189: ("New Delhi", "Asia/Kolkata"),
    190: ("Katmandu", "Asia/Kathmandu"),
    191: ("Osaka", "Asia/Tokyo"),
    192: ("Pyongyang", "Asia/Pyongyang"),
    193: ("Seoul", "Asia/Seoul"),
    194: ("Tokyo", "Asia/Tokyo"),
    195: ("Yakutsk", "Asia/Yakutsk"),
    196: ("Athens", "Europe/Athens"),
    197: ("Rangoon", "Asia/Yangon"),
    198: ("Thanh Pho Ho Chi Minh", "Asia/Ho_Chi_Minh"),
    199: ("Des Moines", "America/Chicago"),
    200: ("Bangkok", "Asia/Bangkok"),
    201: ("Hanoi", "Asia/Ho_Chi_Minh"),
    202: ("Jakarta", "Asia/Jakarta"),
    203: ("Krasnoyarsk", "Asia/Krasnoyarsk"),
    204: ("Kuwait", "Asia/Kuwait"),
    205: ("Phnom Penh", "Asia/Phnom_Penh"),
}


_LATER_UNRESOLVED_CITIES = {
    38: (
        "Manchester's packaged record is America/New_York, while the older "
        "geographical interpretation was London. The city identity is unresolved."
    ),
    118: (
        "Cape Town is bound to the packaged Africa/Bissau record. This contradicts "
        "the city label; the raw binding is retained without a geographical correction."
    ),
    185: (
        "Chennai (Madras) is bound to the packaged Asia/Colombo record. This is "
        "not India's geographical zone and its historical offsets can differ."
    ),
}
_POLICY_DETAIL = (
    "Saved primary-city evidence, not proof of live adoption. The Host's IANA "
    "rules may differ from Apple's historical rules and a device timezone-file "
    "override. The packaged base offset is not a DST-effective offset and is "
    "never used as a fallback."
)
_CLOCK_PROFILES = frozenset(
    {
        NamedPreferencesProfile.NANO_5_1_0_2,
        NamedPreferencesProfile.NANO_6_1_2,
        NamedPreferencesProfile.NANO_7_1_0_4,
        NamedPreferencesProfile.NANO_UPDATER_39_1_1_2,
    }
)


def _resolve_city(evidence: NamedClockEvidence) -> NamedClockEvidence:
    """Bind an already parsed city ID to this exact firmware's immutable data."""
    city_id = evidence.city_id
    profile = evidence.profile
    city = FIRMWARE_CITIES.get(city_id) if city_id is not None else None
    if city is None:
        message = (
            "DateTime.TimeZone 0 has no native city lookup result."
            if city_id == 0
            else f"DateTime.TimeZone city ID {city_id} has no qualified native record."
        )
        return replace(evidence, issues=(message,))
    if profile is NamedPreferencesProfile.NANO_5_1_0_2:
        evidence = replace(
            evidence,
            city_label=city.label,
            firmware_base_offset_minutes=city.nano5_base_minutes,
            detail=_POLICY_DETAIL,
        )
        if city_id == 205:
            return replace(
                evidence,
                issues=(
                    "DateTime.TimeZone 205 names Phnom Penh in the native lookup but "
                    "exceeds Nano 5's registered maximum 204. A saved out-of-range "
                    "value does not establish the adopted timezone.",
                ),
            )
        geographic = (
            _NANO5_GEOGRAPHICAL_CITIES.get(city_id) if city_id is not None else None
        )
        if geographic is None or geographic[0] != city.label:
            return replace(
                evidence,
                issues=(
                    f"Nano 5 city {city_id} ({city.label}) has no unambiguous, label-checked geographical timezone policy.",
                ),
            )
        return replace(
            evidence,
            iana_timezone=geographic[1],
            interpretation="geographical_city",
            detail="Nano 5 geographical city policy; no packaged IANA record is inferred. "
            + _POLICY_DETAIL,
        )
    if profile is NamedPreferencesProfile.NANO_6_1_2:
        label, name, base = city.label, city.nano6_zone, city.nano6_base_minutes
    else:
        label = city.nano7_label or city.label
        name, base = city.nano7_zone, city.nano7_base_minutes
    evidence = replace(
        evidence,
        city_label=label,
        firmware_timezone_name=name,
        firmware_base_offset_minutes=base,
        detail=_POLICY_DETAIL,
    )
    contradiction = (
        _LATER_UNRESOLVED_CITIES.get(city_id) if city_id is not None else None
    )
    if contradiction:
        return replace(evidence, issues=(contradiction,))
    if not name:
        return replace(
            evidence,
            issues=("The native city has no qualified packaged timezone name.",),
        )
    return replace(
        evidence,
        iana_timezone=name,
        interpretation="firmware_record",
        detail="Packaged firmware record name used as the Host's IANA policy key. "
        + _POLICY_DETAIL,
    )


def read_named_clock_evidence(
    data: bytes, *, profile: NamedPreferencesProfile
) -> NamedClockEvidence:
    """Read an exact Nano's primary city without throwing for captured bad state.

    Uses the shared bounded XML and numeric readers instead of
    maintaining a third XML parser or parsing human-readable inspection text.
    There is no Storage/Registry dependency, Host clock, timezone lookup, DST
    evaluator or serialization here. Callers preserve the captured file bytes.
    """
    if type(profile) is not NamedPreferencesProfile:
        return NamedClockEvidence(
            None,
            issues=(
                "An exact named Preferences profile is required for clock evidence.",
            ),
        )
    evidence = NamedClockEvidence(profile)
    if profile is NamedPreferencesProfile.NANO_4_1_0_4:
        return replace(
            evidence,
            issues=(
                "Nano 4's extensionless named store has no qualified primary timezone field.",
            ),
        )
    if profile not in _CLOCK_PROFILES:
        return replace(
            evidence,
            issues=(
                "This exact named Preferences profile has no qualified clock evidence.",
            ),
        )
    if type(data) is not bytes:
        return replace(
            evidence,
            issues=("Named clock evidence requires captured immutable bytes.",),
        )
    root, issues = parse_named_xml(data)
    if root is None:
        return replace(evidence, issues=issues)
    sections = [node for node in root.children if node.name == "DateTime"]
    if not sections:
        return replace(
            evidence,
            issues=(
                "DateTime.TimeZone is absent; no default or world-clock value is substituted.",
            ),
        )
    if len(sections) != 1 or sections[0].attributes:
        return replace(
            evidence,
            issues=("DateTime is ambiguous; no primary timezone is selected.",),
        )
    nodes = [node for node in sections[0].children if node.name == "TimeZone"]
    if not nodes:
        return replace(
            evidence,
            issues=(
                "DateTime.TimeZone is absent; no default or world-clock value is substituted.",
            ),
        )
    if len(nodes) != 1:
        return replace(
            evidence,
            issues=(
                "DateTime.TimeZone occurs more than once; no winning value is selected.",
            ),
        )
    node = nodes[0]
    if node.attributes or node.children or node.complex or node.end < node.start:
        return replace(
            evidence, issues=("DateTime.TimeZone is not a qualified plain scalar.",)
        )
    raw = data[node.start : node.end]
    value = unsigned_decimal("".join(node.text), 32)
    evidence = replace(evidence, raw_value=raw, city_id=value)
    if value is None:
        return replace(
            evidence,
            issues=(
                "DateTime.TimeZone has an unknown or oversized numeric spelling; raw bytes are retained.",
            ),
        )
    return _resolve_city(evidence)
