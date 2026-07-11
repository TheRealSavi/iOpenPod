"""Shared formatting utilities for the iopenpod.gui."""

from datetime import UTC, datetime

from iopenpod.itunesdb_shared.constants import MEDIA_TYPE_MAP, PLAYLIST_SORT_ORDER_MAP
from iopenpod.itunesdb_shared.field_base import MAC_EPOCH_OFFSET
from iopenpod.itunesdb_shared.mhod_defs import (
    SPL_ACTION_MAP,
    SPL_CHOICE_FIELD_IDS,
    SPL_CHOICE_VALUE_MAP,
    SPL_DATE_RELATIVE_ACTION_IDS,
    SPL_DATE_UNITS_MAP,
    SPL_FIELD_MAP,
    SPL_LIMIT_SORT_MAP,
    SPL_LIMIT_TYPE_MAP,
    spl_get_field_type,
)


def format_size(bytes_val: int) -> str:
    """Format bytes as human-readable string (B, KB, MB, GB)."""
    if not bytes_val or bytes_val <= 0:
        return ""
    val = float(bytes_val)
    if val < 1024:
        return f"{int(val)} B"
    elif val < 1024 * 1024:
        return f"{val / 1024:.1f} KB"
    elif val < 1024 * 1024 * 1024:
        return f"{val / (1024 * 1024):.1f} MB"
    return f"{val / (1024 * 1024 * 1024):.1f} GB"


def format_duration_mmss(ms: int) -> str:
    """Format milliseconds as M:SS or H:MM:SS for individual tracks."""
    if not ms or ms <= 0:
        return "—"
    total_seconds = ms // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_duration_human(ms: int) -> str:
    """Format milliseconds as 'X hours' or 'X min' for aggregate displays."""
    if not ms or ms <= 0:
        return "0 min"
    hours = ms / (1000 * 60 * 60)
    if hours >= 1:
        return f"{hours:.1f} hours"
    minutes = ms / (1000 * 60)
    return f"{minutes:.0f} min"


def format_rating(rating: int) -> str:
    """Format rating (0-100) as stars (★☆). Returns empty string for 0."""
    if not rating or rating <= 0:
        return ""
    stars = min(5, rating // 20)
    return "★" * stars + "☆" * (5 - stars)


# ── Playlist formatters ────────────────────────────────────────────────────

_SORT_ORDER_LABEL_OVERRIDES = {
    0: "Default",
    1: "Manual",
    23: "Rating",
}
_SORT_ORDER_MAP = {
    sort_order: _SORT_ORDER_LABEL_OVERRIDES.get(sort_order, label.title())
    for sort_order, label in PLAYLIST_SORT_ORDER_MAP.items()
}


def format_sort_order(sort_order: int) -> str:
    """Format playlist sort order as human-readable name."""
    return _SORT_ORDER_MAP.get(sort_order, f"Unknown ({sort_order})")


# MHSD type 5 playlist browsing category names.
# When a smart playlist lives in dataset type 5, the MHYP field at offset
# 0x50 (mhsd5Type) tells the iPod which built-in browsing category it
# represents.  Values derived from libgpod and empirical testing.
_MHSD5_TYPE_MAP = {
    0: "None / Master",
    1: "Music",
    2: "Movies",
    3: "TV Shows",
    4: "Music (Video)",
    5: "Audiobooks",
    6: "Podcasts",
    7: "Rentals",
}


def format_mhsd5_type(mhsd5_type: int) -> str:
    """Format mhsd5Type value as human-readable iPod browsing category."""
    return _MHSD5_TYPE_MAP.get(mhsd5_type, f"Unknown ({mhsd5_type})")


# ── Media type bitmask for smart playlist rules ─────────────────────────────

_SINGLE_BIT_MEDIA_TYPES = {
    value: label
    for value, label in MEDIA_TYPE_MAP.items()
    if value and value & (value - 1) == 0
}


def _decode_mediatype(value: int) -> str:
    """Decode a media type bitmask into human-readable flag names."""
    if value == 0:
        return "None"
    if value in MEDIA_TYPE_MAP:
        return MEDIA_TYPE_MAP[value]
    names = []
    remaining = value
    for bit, name in sorted(_SINGLE_BIT_MEDIA_TYPES.items()):
        if remaining & bit:
            names.append(name)
            remaining &= ~bit
    if remaining:
        names.append(f"0x{remaining:X}")
    return " | ".join(names) if names else str(value)


def _signed_i64(value: int) -> int:
    value = int(value or 0)
    if value >= (1 << 63):
        return value - (1 << 64)
    return value


def _relative_date_count(rule: dict) -> int:
    raw_date = int(rule.get("from_date", 0) or 0)
    if raw_date:
        return abs(raw_date)

    raw_value = _signed_i64(rule.get("from_value", 0) or 0)
    count = abs(raw_value)
    from_units = int(rule.get("from_units", 0) or 0)
    if from_units > 1 and count >= from_units and count % from_units == 0:
        return count // from_units
    return count


def _rule_date_label(value: int) -> str:
    if not value:
        return "0"
    unix_ts = max(0, int(value) - MAC_EPOCH_OFFSET)
    return datetime.fromtimestamp(unix_ts, tz=UTC).strftime("%Y-%m-%d")


def _date_action_label(action_id: int) -> str:
    return {
        0x00000001: "is",
        0x02000001: "is not",
        0x00000010: "is after",
        0x00000040: "is before",
        0x00000100: "is in the range",
        0x00000200: "is in the last",
        0x02000200: "is not in the last",
    }.get(action_id, SPL_ACTION_MAP.get(action_id, f"action 0x{action_id:08X}"))


def _int_rule_display(field_id: int, value: int) -> str:
    if field_id in (0x19, 0x5A):
        stars = max(0, min(5, int(value) // 20))
        return f"{stars} star{'s' if stars != 1 else ''}"
    if field_id == 0x0C:
        mb = int(value) // (1024 * 1024)
        return f"{mb} MB"
    return str(value)


def _choice_action_label(action_id: int) -> str:
    if action_id in (0x00000001, 0x00000400):
        return "is"
    if action_id in (0x02000001, 0x02000400):
        return "is not"
    return SPL_ACTION_MAP.get(action_id, f"action 0x{action_id:08X}")


def _choice_value_label(field_id: int, value: int) -> str:
    for raw_value, label in SPL_CHOICE_VALUE_MAP.get(field_id, ()):
        if raw_value == value:
            return label
    return f"raw value {value}"


def format_smart_rule(rule: dict) -> str:
    """Format a single smart playlist rule as human-readable text.

    Accepts raw parser output (field_id/action_id as ints) and resolves them
    to human-readable names via the SPL maps in mhod_defs.
    """
    field_id = rule.get("field_id", 0)
    action_id = rule.get("action_id", 0)
    field = SPL_FIELD_MAP.get(field_id, f"Field 0x{field_id:02X}")
    action = SPL_ACTION_MAP.get(action_id, f"action 0x{action_id:08X}")
    field_type = spl_get_field_type(field_id)
    from_val = rule.get("from_value", 0)

    if field_id in SPL_CHOICE_FIELD_IDS:
        choice_action = _choice_action_label(action_id)
        if field_id == 0x28:  # Playlist
            playlist_name = rule.get("playlist_name") or rule.get("playlist_title")
            if playlist_name:
                return f"{field} {choice_action} {playlist_name}"
            playlist_id = rule.get("playlist_id", from_val)
            return f"{field} {choice_action} (Playlist ID: {playlist_id})"
        return f"{field} {choice_action} {_choice_value_label(field_id, int(from_val or 0))}"

    # String rules
    if field_type == 1:  # SPLFT_STRING
        value = rule.get("string_value", "")
        return f"{field} {action} \"{value}\""

    # Date rules with relative units
    if field_type == 4:  # SPLFT_DATE
        date_action = _date_action_label(action_id)
        # Resolve raw unit seconds to human name
        from_units = rule.get("from_units", 0)
        units_name = rule.get("units_name", "") or SPL_DATE_UNITS_MAP.get(from_units, "")
        if action_id in SPL_DATE_RELATIVE_ACTION_IDS:
            count = _relative_date_count(rule)
            if units_name and count:
                return f"{field} {date_action} {count} {units_name}"
            if count:
                return f"{field} {date_action} {count}"
            return f"{field} {date_action}"
        if action_id == 0x00000100:
            return (
                f"{field} {date_action} "
                f"{_rule_date_label(from_val)} - {_rule_date_label(rule.get('to_value', 0))}"
            )
        if from_val:
            return f"{field} {date_action} {_rule_date_label(from_val)}"
        return f"{field} {date_action}"

    # Range rules (int)
    to_val = rule.get("to_value", 0)
    if "range" in action.lower():
        return (
            f"{field} is in the range "
            f"{_int_rule_display(field_id, int(from_val or 0))} - "
            f"{_int_rule_display(field_id, int(to_val or 0))}"
        )

    # Boolean rules
    if field_type == 3:  # SPLFT_BOOLEAN
        if action_id == 0x00000001:
            return f"{field} is true"
        if action_id == 0x02000001:
            return f"{field} is false"
        return f"{field} {action}"

    # Playlist rules
    if field_type == 5:  # SPLFT_PLAYLIST
        playlist_id = rule.get("playlist_id", from_val)
        return f"{field} {action} (Playlist ID: {playlist_id})"

    # Binary AND rules (media type bitmask)
    if field_type == 7:  # SPLFT_BINARY_AND
        from_val = rule.get("from_value", 0)
        decoded = _decode_mediatype(from_val)
        action_lower = action.lower()
        if "not" in action_lower:
            verb = "excludes"
        else:
            verb = "includes"
        return f"{field} {verb} {decoded}"

    # Generic int rules
    if field_type == 2:  # SPLFT_INT
        return f"{field} {action} {_int_rule_display(field_id, int(from_val or 0))}"

    return f"{field} {action}"


def format_smart_rules_summary(rules_data: dict | None, prefs_data: dict | None) -> list[str]:
    """Build a list of human-readable lines summarizing smart playlist rules.

    Args:
        rules_data: Parsed MHOD type 51 data (smart_playlist_rules)
        prefs_data: Parsed MHOD type 50 data (smart_playlist_data)

    Returns:
        List of display strings, one per logical section.
    """
    lines = []

    # Preferences summary
    if prefs_data:
        parts = []
        if prefs_data.get("live_update"):
            parts.append("Live updating")
        if prefs_data.get("match_checked_only"):
            parts.append("Checked items only")
        if parts:
            lines.append(" · ".join(parts))

        if prefs_data.get("check_limits"):
            limit_val = prefs_data.get("limit_value", 0)
            limit_type_id = prefs_data.get("limit_type", 0)
            limit_sort_id = prefs_data.get("limit_sort", 0)
            limit_type = prefs_data.get("limit_type_name") or SPL_LIMIT_TYPE_MAP.get(limit_type_id, "items")
            limit_sort = prefs_data.get("limit_sort_name") or SPL_LIMIT_SORT_MAP.get(limit_sort_id, "random")
            lines.append(f"Limit to {limit_val} {limit_type}, selected by {limit_sort}")

    # Rules
    if rules_data:
        raw_conj = rules_data.get("conjunction", "AND")
        if isinstance(raw_conj, int):
            conjunction = "ANY" if raw_conj == 1 else "ALL"
        else:
            conjunction = "ANY" if str(raw_conj).upper() == "OR" else "ALL"
        rules = rules_data.get("rules", [])
        if rules:
            lines.append(f"Match {conjunction} of the following:")
            for rule in rules:
                lines.append(f"  • {format_smart_rule(rule)}")

    return lines
