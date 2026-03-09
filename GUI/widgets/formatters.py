"""
Shared formatting utilities for the GUI.

Provides consistent human-readable formatting for sizes, durations, ratings, etc.
Import these instead of defining local static _format_* methods.
"""

from iTunesDB_Shared.mhod_defs import (
    SPL_ACTION_MAP,
    SPL_FIELD_MAP,
    SPL_LIMIT_SORT_MAP,
    SPL_LIMIT_TYPE_MAP,
    SPL_DATE_UNITS_MAP,
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

# Sort order names from libgpod ItdbPlaylistSortOrder enum.
# NOTE: libgpod defines 1=Manual (ITDB_PSO_MANUAL), NOT 0.
_SORT_ORDER_MAP = {
    0: "Default",
    1: "Manual",
    2: "Unknown (2)",
    3: "Title",
    4: "Album",
    5: "Artist",
    6: "Bitrate",
    7: "Genre",
    8: "Kind",
    9: "Date Modified",
    10: "Track Number",
    11: "Size",
    12: "Time",
    13: "Year",
    14: "Sample Rate",
    15: "Comment",
    16: "Date Added",
    17: "Equalizer",
    18: "Composer",
    19: "Unknown (19)",
    20: "Play Count",
    21: "Last Played",
    22: "Disc Number",
    23: "Rating",
    24: "Release Date",
    25: "BPM",
    26: "Grouping",
    27: "Category",
    28: "Description",
    29: "Show",
    30: "Season",
    31: "Episode Number",
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

# From libgpod ItdbMediatype enum — bitmask flags used by smart playlist
# "Media Type" (field 0x3C) rules with BINARY_AND actions.
_MEDIATYPE_FLAGS = {
    0x00000001: "Music",
    0x00000002: "Movie",
    0x00000004: "Podcast",
    0x00000006: "Video Podcast",
    0x00000008: "Audiobook",
    0x00000020: "Music Video",
    0x00000040: "TV Show",
    0x00000100: "Ringtone",
    0x00000400: "Rental",
    0x00008000: "iTunes Extra",
    0x00010000: "Memo",
    0x00100000: "iTunes U",
    0x00200000: "EPUB Book",
    0x00400000: "PDF Book",
}


def _decode_mediatype(value: int) -> str:
    """Decode a media type bitmask into human-readable flag names."""
    if value == 0:
        return "None"
    names = []
    remaining = value
    for bit, name in sorted(_MEDIATYPE_FLAGS.items()):
        if value & bit:
            names.append(name)
            remaining &= ~bit
    if remaining:
        names.append(f"0x{remaining:X}")
    return " | ".join(names) if names else str(value)


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

    # String rules
    if field_type == 1:  # SPLFT_STRING
        value = rule.get("string_value", "")
        return f"{field} {action} \"{value}\""

    # Rating special case — show stars
    if field_id == 0x19:  # Rating
        from_stars = rule.get("from_value_stars", 0)
        to_stars = rule.get("to_value_stars", 0)
        star_str = "★" * from_stars + "☆" * (5 - from_stars)
        if "range" in action.lower():
            to_star_str = "★" * to_stars + "☆" * (5 - to_stars)
            return f"{field} is in the range {star_str} - {to_star_str}"
        return f"{field} {action} {star_str}"

    # Date rules with relative units
    if field_type == 4:  # SPLFT_DATE
        from_val = rule.get("from_value", 0)
        # Resolve raw unit seconds to human name
        from_units = rule.get("from_units", 0)
        units_name = rule.get("units_name", "") or SPL_DATE_UNITS_MAP.get(from_units, "")
        if units_name and from_val:
            # Convert seconds-based value to the unit count
            if from_units and from_units > 0:
                count = abs(from_val) // from_units
                return f"{field} {action} {count} {units_name}"
            return f"{field} {action} {from_val} {units_name}"
        if from_val:
            return f"{field} {action} {from_val}"
        return f"{field} {action}"

    # Range rules (int)
    from_val = rule.get("from_value", 0)
    to_val = rule.get("to_value", 0)
    if "range" in action.lower():
        return f"{field} is in the range {from_val} - {to_val}"

    # Boolean rules
    if field_type == 3:  # SPLFT_BOOLEAN
        val = "True" if from_val else "False"
        return f"{field} {action} {val}"

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
    if from_val:
        return f"{field} {action} {from_val}"

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
