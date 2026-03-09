"""
Smart Playlist Evaluator — evaluate SPL rules against a track library.

Port of libgpod's itdb_spl_update() / itdb_splr_eval() from itdb_playlist.c.
Takes parsed smart playlist rules + a list of parsed tracks, returns matching
track IDs that should be written as MHIPs.

Usage:
    from SyncEngine.spl_evaluator import spl_update, spl_update_all

    # Single playlist
    track_ids = spl_update(smart_playlist_data, smart_playlist_rules, tracks)

    # All live-update playlists
    for pl in playlists:
        if pl.is_smart and pl.smart_prefs.live_update:
            pl.track_ids = spl_update(
                pl.smart_prefs, pl.smart_rules, tracks
            )
"""

from __future__ import annotations

import random
import time

from iTunesDB_Writer.mhod_spl_writer import (
    SmartPlaylistPrefs,
    SmartPlaylistRule,
    SmartPlaylistRules,
)
from iTunesDB_Shared.mhod_defs import SPL_FIELD_TYPE_MAP as _FIELD_TYPE_MAP


# ────────────────────────────────────────────────────────────
# Field accessor: maps SPL field IDs → parsed track dict keys
# ────────────────────────────────────────────────────────────

# String fields — track dict key, used for string comparisons
_STRING_FIELD_KEY: dict[int, str] = {
    0x02: "Title",           # Song Name
    0x03: "Album",           # Album
    0x04: "Artist",          # Artist
    0x08: "Genre",           # Genre
    0x09: "filetype",        # Kind (e.g. "MP3", "Apple Lossless / AAC")
    0x0E: "Comment",         # Comment
    0x12: "Composer",        # Composer
    0x27: "Grouping",        # Grouping
    0x36: "Description Text",  # Description
    0x37: "Category",        # Category
    0x3E: "Show",            # TV Show
    0x47: "Album Artist",    # Album Artist
    0x4E: "Sort Title",      # Sort Song Name
    0x4F: "Sort Album",      # Sort Album
    0x50: "Sort Artist",     # Sort Artist
    0x51: "Sort Album Artist",  # Sort Album Artist
    0x52: "Sort Composer",   # Sort Composer
    0x53: "Sort Show",       # Sort TV Show
}

# Integer fields — track dict key
_INT_FIELD_KEY: dict[int, str] = {
    0x05: "bitrate",         # Bitrate (kbps)
    0x06: "sample_rate_1",   # Sample Rate (Hz)
    0x07: "year",            # Year
    0x0B: "track_number",    # Track Number
    0x0C: "size",            # Size (bytes)
    0x0D: "length",          # Time (milliseconds)
    0x16: "play_count_1",    # Play Count
    0x18: "disc_number",     # Disc Number
    0x19: "rating",          # Rating (0-100, stars×20)
    0x23: "bpm",             # BPM
    0x3F: "season_number",   # Season Number
    0x40: "episode_number",  # Episode Number
    0x44: "skip_count",      # Skip Count
    0x39: "podcast_flag",    # Podcast flag
}

# Date fields — track dict key (values are Unix timestamps)
_DATE_FIELD_KEY: dict[int, str] = {
    0x0A: "last_modified",   # Date Modified
    0x10: "date_added",      # Date Added
    0x17: "last_played",     # Last Played
    0x45: "last_skipped",    # Last Skipped
}

# Boolean fields
_BOOL_FIELD_KEY: dict[int, str] = {
    0x1F: "compilation_flag",  # Compilation
}

# Binary AND field
_BINARY_AND_FIELD_KEY: dict[int, str] = {
    0x3C: "media_type",      # Media Type (bitmask)
}


# ────────────────────────────────────────────────────────────
# Limit sort constants (from libgpod ItdbLimitSort)
# ────────────────────────────────────────────────────────────

LIMITSORT_RANDOM = 0x02
LIMITSORT_SONG_NAME = 0x03
LIMITSORT_ALBUM = 0x04
LIMITSORT_ARTIST = 0x05
LIMITSORT_GENRE = 0x07
LIMITSORT_MOST_RECENTLY_ADDED = 0x10
LIMITSORT_LEAST_RECENTLY_ADDED = 0x80000010
LIMITSORT_MOST_OFTEN_PLAYED = 0x14
LIMITSORT_LEAST_OFTEN_PLAYED = 0x80000014
LIMITSORT_MOST_RECENTLY_PLAYED = 0x15
LIMITSORT_LEAST_RECENTLY_PLAYED = 0x80000015
LIMITSORT_HIGHEST_RATING = 0x17
LIMITSORT_LOWEST_RATING = 0x80000017

# Limit type constants
LIMITTYPE_MINUTES = 0x01
LIMITTYPE_MB = 0x02
LIMITTYPE_SONGS = 0x03
LIMITTYPE_HOURS = 0x04
LIMITTYPE_GB = 0x05


# ────────────────────────────────────────────────────────────
# Rule evaluation
# ────────────────────────────────────────────────────────────

def _get_string_value(track: dict, field_id: int) -> str:
    """Get the string value for a track field, case-folded for comparison."""
    key = _STRING_FIELD_KEY.get(field_id)
    if key is None:
        return ""
    val = track.get(key, "")
    return val.casefold() if isinstance(val, str) else ""


def _get_int_value(track: dict, field_id: int) -> int:
    """Get the integer value for a track field."""
    key = _INT_FIELD_KEY.get(field_id)
    if key is None:
        # Check binary AND fields too
        key = _BINARY_AND_FIELD_KEY.get(field_id)
    if key is None:
        return 0
    val = track.get(key, 0)
    return val if isinstance(val, int) else 0


def _get_date_value(track: dict, field_id: int) -> int:
    """Get the date (Unix timestamp) value for a track field."""
    key = _DATE_FIELD_KEY.get(field_id)
    if key is None:
        return 0
    val = track.get(key, 0)
    return val if isinstance(val, int) else 0


def _get_bool_value(track: dict, field_id: int) -> bool:
    """Get the boolean value for a track field."""
    key = _BOOL_FIELD_KEY.get(field_id)
    if key is None:
        return False
    val = track.get(key, 0)
    return bool(val)


def _eval_string(track_val: str, rule: SmartPlaylistRule) -> bool:
    """Evaluate a string-type rule against a case-folded track value."""
    if rule.string_value is None:
        return False
    rule_val = rule.string_value.casefold()

    action = rule.action_id
    match action:
        case 0x01000001:  # is (string)
            return track_val == rule_val
        case 0x03000001:  # is not (string)
            return track_val != rule_val
        case 0x01000002:  # contains
            return rule_val in track_val
        case 0x03000002:  # does not contain
            return rule_val not in track_val
        case 0x01000004:  # starts with
            return track_val.startswith(rule_val)
        case 0x03000004:  # does not start with
            return not track_val.startswith(rule_val)
        case 0x01000008:  # ends with
            return track_val.endswith(rule_val)
        case 0x03000008:  # does not end with
            return not track_val.endswith(rule_val)
        case _:
            return False


def _eval_int(track_val: int, rule: SmartPlaylistRule) -> bool:
    """Evaluate an integer-type rule."""
    action = rule.action_id
    fv = rule.from_value
    tv = rule.to_value

    match action:
        case 0x00000001:  # is
            return track_val == fv
        case 0x02000001:  # is not
            return track_val != fv
        case 0x00000010:  # is greater than
            return track_val > fv
        case 0x02000010:  # is not greater than
            return track_val <= fv
        case 0x00000040:  # is less than
            return track_val < fv
        case 0x02000040:  # is not less than
            return track_val >= fv
        case 0x00000100:  # is in the range
            lo, hi = min(fv, tv), max(fv, tv)
            return lo <= track_val <= hi
        case 0x02000100:  # is not in the range
            lo, hi = min(fv, tv), max(fv, tv)
            return track_val < lo or track_val > hi
        case _:
            return False


def _eval_date(track_val: int, rule: SmartPlaylistRule) -> bool:
    """Evaluate a date-type rule.

    Date values are Unix timestamps. "is in the last" rules use from_date
    and from_units to compute a relative threshold.
    """
    action = rule.action_id
    fv = rule.from_value
    tv = rule.to_value

    match action:
        case 0x00000001:  # is
            return track_val == fv
        case 0x02000001:  # is not
            return track_val != fv
        case 0x00000010:  # is greater than
            return track_val > fv
        case 0x02000010:  # is not greater than
            return track_val <= fv
        case 0x00000040:  # is less than
            return track_val < fv
        case 0x02000040:  # is not less than
            return track_val >= fv
        case 0x00000200:  # is in the last
            # from_date is the count, from_units is the unit size in seconds
            # libgpod: t += (splr->fromdate * splr->fromunits)
            #   ... where both are negative (time in the past)
            now = int(time.time())
            threshold = now + (rule.from_date * rule.from_units)
            return track_val > threshold
        case 0x02000200:  # is not in the last
            now = int(time.time())
            threshold = now + (rule.from_date * rule.from_units)
            return track_val <= threshold
        case 0x00000100:  # is in the range
            lo, hi = min(fv, tv), max(fv, tv)
            return lo <= track_val <= hi
        case 0x02000100:  # is not in the range
            lo, hi = min(fv, tv), max(fv, tv)
            return track_val < lo or track_val > hi
        case _:
            return False


def _eval_boolean(track_val: bool, rule: SmartPlaylistRule) -> bool:
    """Evaluate a boolean-type rule (is set / is not set)."""
    action = rule.action_id
    match action:
        case 0x00000001:  # is (set)
            return track_val
        case 0x02000001:  # is not (not set)
            return not track_val
        case _:
            return False


def _eval_binary_and(track_val: int, rule: SmartPlaylistRule) -> bool:
    """Evaluate a binary AND rule (e.g. mediaType includes flags)."""
    action = rule.action_id
    fv = rule.from_value

    match action:
        case 0x00000400:  # binary AND (includes)
            return bool(track_val & fv)
        case 0x02000400:  # not binary AND (excludes)
            return not bool(track_val & fv)
        case _:
            return False


def _eval_playlist(
    track: dict,
    rule: SmartPlaylistRule,
    playlist_lookup: dict[int, set[int]] | None,
) -> bool:
    """Evaluate a playlist membership rule.

    playlist_lookup maps playlist ID → set of track IDs in that playlist.
    """
    if playlist_lookup is None:
        return False

    playlist_id = rule.from_value
    member_set = playlist_lookup.get(playlist_id, set())
    track_id = track.get("track_id", 0)

    action = rule.action_id
    match action:
        case 0x00000001:  # is in playlist
            return track_id in member_set
        case 0x02000001:  # is not in playlist
            return track_id not in member_set
        case _:
            return False


def eval_rule(
    rule: SmartPlaylistRule,
    track: dict,
    playlist_lookup: dict[int, set[int]] | None = None,
) -> bool:
    """Evaluate a single smart playlist rule against a track.

    Args:
        rule: The smart playlist rule to evaluate.
        track: Parsed track dict from the parser (mhit fields + MHOD strings).
        playlist_lookup: Optional map of playlistID → set of trackIDs
                         (needed for "is in playlist" rules).

    Returns:
        True if the track matches the rule.
    """
    ft = _FIELD_TYPE_MAP.get(rule.field_id)

    match ft:
        case 1:  # SPLFT_STRING
            return _eval_string(_get_string_value(track, rule.field_id), rule)
        case 2:  # SPLFT_INT
            return _eval_int(_get_int_value(track, rule.field_id), rule)
        case 3:  # SPLFT_BOOLEAN
            return _eval_boolean(_get_bool_value(track, rule.field_id), rule)
        case 4:  # SPLFT_DATE
            return _eval_date(_get_date_value(track, rule.field_id), rule)
        case 5:  # SPLFT_PLAYLIST
            return _eval_playlist(track, rule, playlist_lookup)
        case 7:  # SPLFT_BINARY_AND
            return _eval_binary_and(_get_int_value(track, rule.field_id), rule)
        case _:
            # Unknown field type — default to no match
            return False


# ────────────────────────────────────────────────────────────
# Track sorting for limit enforcement
# ────────────────────────────────────────────────────────────

def _sort_key(limit_sort: int):
    """Return a sort key function and reverse flag for the given limit sort.

    Returns:
        (key_func, reverse) tuple for sorted().
    """
    # Strip the high bit (reverse flag)
    base = limit_sort & 0x7FFFFFFF
    reverse = bool(limit_sort & 0x80000000)

    match base:
        case 0x02:  # Random
            return None, False  # handled specially
        case 0x03:  # Song Name
            return (lambda t: (t.get("Title", "") or "").casefold()), False
        case 0x04:  # Album
            return (lambda t: (t.get("Album", "") or "").casefold()), False
        case 0x05:  # Artist
            return (lambda t: (t.get("Artist", "") or "").casefold()), False
        case 0x07:  # Genre
            return (lambda t: (t.get("Genre", "") or "").casefold()), False
        case 0x10:  # Most recently added → sort by date_added descending
            # When NOT reversed (0x10): most recent first → reverse=True
            # When reversed (0x80000010): least recent first → reverse=False
            return (lambda t: t.get("date_added", 0)), not reverse
        case 0x14:  # Most often played
            return (lambda t: t.get("play_count_1", 0)), not reverse
        case 0x15:  # Most recently played
            return (lambda t: t.get("last_played", 0)), not reverse
        case 0x17:  # Highest rating
            return (lambda t: t.get("rating", 0)), not reverse
        case _:
            return (lambda t: 0), False


def _track_limit_value(track: dict, limit_type: int) -> float:
    """Get the value a track contributes toward the limit total.

    Returns the track's contribution in the unit specified by limit_type.
    """
    match limit_type:
        case 0x01:  # Minutes
            return track.get("length", 0) / (60 * 1000)
        case 0x02:  # MB
            return track.get("size", 0) / (1024 * 1024)
        case 0x03:  # Songs
            return 1.0
        case 0x04:  # Hours
            return track.get("length", 0) / (60 * 60 * 1000)
        case 0x05:  # GB
            return track.get("size", 0) / (1024 * 1024 * 1024)
        case _:
            return 1.0


# ────────────────────────────────────────────────────────────
# Main evaluator
# ────────────────────────────────────────────────────────────

def spl_update(
    prefs: SmartPlaylistPrefs,
    rules: SmartPlaylistRules,
    tracks: list[dict],
    playlist_lookup: dict[int, set[int]] | None = None,
) -> list[int]:
    """Evaluate smart playlist rules and return matching track IDs.

    Port of libgpod's itdb_spl_update() from itdb_playlist.c.

    Args:
        prefs: SmartPlaylistPrefs (live_update, limits, sorting).
        rules: SmartPlaylistRules (conjunction + rule list).
        tracks: List of parsed track dicts (from the parser).
        playlist_lookup: Optional map of playlistID → set of trackIDs
                         for evaluating "is in playlist" rules.

    Returns:
        List of trackID integers for tracks that match the rules,
        after applying limits and sorting.
    """
    # Phase 1: rule matching
    selected: list[dict] = []

    for track in tracks:
        # Skip unchecked tracks if match_checked_only is set
        # (checked=0 means checked, checked=1 means unchecked in the parser)
        if prefs.match_checked_only and track.get("checked_flag", 0) != 0:
            continue

        if prefs.check_rules and rules.rules:
            # Evaluate rules with AND/OR conjunction
            is_and = rules.conjunction == "AND"
            match_result = is_and  # start True for AND, False for OR

            for rule in rules.rules:
                rule_truth = eval_rule(rule, track, playlist_lookup)

                if is_and:
                    if not rule_truth:
                        match_result = False
                        break
                else:  # OR
                    if rule_truth:
                        match_result = True
                        break

            # No rules → everything matches (libgpod behavior)
            if not rules.rules:
                match_result = True

            if match_result:
                selected.append(track)
        else:
            # Not checking rules → everything goes in
            selected.append(track)

    if not selected:
        return []

    # Phase 2: apply limits
    if prefs.check_limits:
        # Sort the selected tracks
        key_func, reverse = _sort_key(prefs.limit_sort)
        if key_func is None:
            # Random sort
            random.shuffle(selected)
        else:
            selected.sort(key=key_func, reverse=reverse)

        # Take tracks up to the limit
        running_total = 0.0
        limited: list[dict] = []

        for track in selected:
            contribution = _track_limit_value(track, prefs.limit_type)
            if running_total + contribution <= prefs.limit_value:
                running_total += contribution
                limited.append(track)

        selected = limited

    # Phase 3: extract track IDs
    return [t["track_id"] for t in selected if "track_id" in t]


def spl_update_from_parsed(
    parsed_prefs: dict,
    parsed_rules: dict,
    tracks: list[dict],
    playlist_lookup: dict[int, set[int]] | None = None,
) -> list[int]:
    """Convenience wrapper that accepts parsed dicts directly from the parser.

    Takes the raw smart_playlist_data / smart_playlist_rules dicts and converts
    them to dataclasses before evaluation.
    """
    from iTunesDB_Writer.mhod_spl_writer import prefs_from_parsed, rules_from_parsed

    prefs = prefs_from_parsed(parsed_prefs)
    rules = rules_from_parsed(parsed_rules)
    return spl_update(prefs, rules, tracks, playlist_lookup)


def spl_update_all(
    playlists: list[dict],
    tracks: list[dict],
    live_only: bool = False,
) -> dict[str, list[int]]:
    """Evaluate all smart playlists, optionally only live-update ones.

    Args:
        playlists: List of parsed playlist dicts (from mhyp_parser).
        tracks: List of parsed track dicts (from mhit_parser).
        live_only: If True, only update playlists where live_update=True.

    Returns:
        Dict mapping playlist Title → list of matching track IDs.
    """
    # Build playlist lookup for "is in playlist" rules
    playlist_lookup: dict[int, set[int]] = {}
    for pl in playlists:
        pl_id = pl.get("playlist_id", 0)
        items = pl.get("items", [])
        if items:
            playlist_lookup[pl_id] = {
                item.get("track_id", 0) for item in items
            }

    results: dict[str, list[int]] = {}

    for pl in playlists:
        if not pl.get("smart_playlist_data"):  # was smartPlaylistData
            continue

        prefs_data = pl.get("smart_playlist_data")  # was smartPlaylistData
        rules_data = pl.get("smart_playlist_rules")  # was smartPlaylistRules
        if prefs_data is None or rules_data is None:
            continue

        if live_only and not prefs_data.get("live_update", False):  # was liveUpdate
            continue

        name = pl.get("Title", "?")
        results[name] = spl_update_from_parsed(
            prefs_data, rules_data, tracks, playlist_lookup
        )

    return results
