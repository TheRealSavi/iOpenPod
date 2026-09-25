"""
Smart Playlist Evaluator — evaluate SPL rules against a track library.

Port of libgpod's itdb_spl_update() / itdb_splr_eval() from itdb_playlist.c.
Takes parsed smart playlist rules + a list of parsed tracks, returns matching
track IDs that should be written as MHIPs.

Usage:
    from iopenpod.sync.spl_evaluator import spl_update, spl_update_all

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
from collections.abc import Callable

from iopenpod.itunesdb_shared.device_time import (
    DeviceTimeContext,
    current_device_time_context,
)
from iopenpod.itunesdb_shared.field_base import MAC_EPOCH_OFFSET
from iopenpod.itunesdb_shared.mhod_defs import (
    SPL_FIELD_TYPE_MAP,
    SPL_HOST_BINARY_AND_FIELD_KEYS,
    SPL_HOST_BOOLEAN_FIELD_KEYS,
    SPL_HOST_DATE_FIELD_KEYS,
    SPL_HOST_INT_FIELD_KEYS,
    SPL_HOST_STRING_FIELD_KEYS,
    SPL_LIMIT_SORT_ALBUM,
    SPL_LIMIT_SORT_ARTIST,
    SPL_LIMIT_SORT_GENRE,
    SPL_LIMIT_SORT_HIGHEST_RATING,
    SPL_LIMIT_SORT_MOST_OFTEN_PLAYED,
    SPL_LIMIT_SORT_MOST_RECENTLY_ADDED,
    SPL_LIMIT_SORT_MOST_RECENTLY_PLAYED,
    SPL_LIMIT_SORT_RANDOM,
    SPL_LIMIT_SORT_SONG_NAME,
    SPL_LIMIT_TYPE_GB,
    SPL_LIMIT_TYPE_HOURS,
    SPL_LIMIT_TYPE_MB,
    SPL_LIMIT_TYPE_MINUTES,
    SPL_LIMIT_TYPE_SONGS,
)
from iopenpod.itunesdb_writer.mhod_spl_writer import (
    RuleGroup,
    SmartPlaylistPrefs,
    SmartPlaylistRule,
    SmartPlaylistRules,
)

# ────────────────────────────────────────────────────────────
# Field accessor: maps SPL field IDs → parsed track dict keys
# ────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────
# Rule evaluation
# ────────────────────────────────────────────────────────────

def _get_string_value(track: dict, field_id: int) -> str:
    """Get the string value for a track field, case-folded for comparison."""
    key = SPL_HOST_STRING_FIELD_KEYS.get(field_id)
    if key is None:
        return ""
    val = track.get(key, "")
    return val.casefold() if isinstance(val, str) else ""


def _get_int_value(track: dict, field_id: int) -> int:
    """Get the integer value for a track field."""
    key = SPL_HOST_INT_FIELD_KEYS.get(field_id)
    if key is None:
        # Check binary AND fields too
        key = SPL_HOST_BINARY_AND_FIELD_KEYS.get(field_id)
    if key is None:
        return 0
    val = track.get(key, 0)
    return val if isinstance(val, int) else 0


def _get_date_value(track: dict, field_id: int) -> int:
    """Get the date (Unix timestamp) value for a track field."""
    key = SPL_HOST_DATE_FIELD_KEYS.get(field_id)
    if key is None:
        return 0
    val = track.get(key, 0)
    return val if isinstance(val, int) else 0


def _get_bool_value(track: dict, field_id: int) -> bool:
    """Get the boolean value for a track field."""
    if field_id == 0x1D:
        return track.get("checked_flag", 0) == 0
    if field_id == 0x25:
        return bool(
            track.get("has_artwork")
            or track.get("artwork_count")
            or track.get("artwork_id_ref")
        )
    if field_id == 0x29:
        return bool(track.get("purchased_flag") or track.get("Purchased"))
    key = SPL_HOST_BOOLEAN_FIELD_KEYS.get(field_id)
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
        case 0x01000004:  # begins with
            return track_val.startswith(rule_val)
        case 0x03000004:  # does not begin with
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


def _eval_date(
    track_val: int,
    rule: SmartPlaylistRule,
    time_context: DeviceTimeContext,
) -> bool:
    """Evaluate a date-type rule.

    Date values are Unix timestamps. "is in the last" rules use from_date
    and from_units to compute a relative threshold.
    """
    action = rule.action_id

    # Relative rules use their value fields as iPod format markers, rather
    # than absolute timestamps.  Evaluate them before decoding those markers.
    if action == 0x00000200:  # is in the last
        # from_date is the count, from_units is the unit size in seconds.
        # libgpod: t += (splr->fromdate * splr->fromunits), where both are
        # negative for a point in the past.
        threshold = int(time.time()) + (rule.from_date * rule.from_units)
        return track_val > threshold
    if action == 0x02000200:  # is not in the last
        threshold = int(time.time()) + (rule.from_date * rule.from_units)
        return track_val <= threshold

    fv = _rule_date_to_unix(rule.from_value, time_context)
    tv = _rule_date_to_unix(rule.to_value, time_context)

    match action:
        case 0x00000001:  # is
            return fv <= track_val <= (tv or fv)
        case 0x02000001:  # is not
            return not (fv <= track_val <= (tv or fv))
        case 0x00000010:  # is after
            return track_val > fv
        case 0x02000010:  # is not after
            return track_val <= fv
        case 0x00000040:  # is before
            return track_val < fv
        case 0x02000040:  # is not before
            return track_val >= fv
        case 0x00000100:  # is in the range
            lo, hi = min(fv, tv), max(fv, tv)
            return lo <= track_val <= hi
        case 0x02000100:  # is not in the range
            lo, hi = min(fv, tv), max(fv, tv)
            return track_val < lo or track_val > hi
        case _:
            return False


def _rule_date_to_unix(
    value: int,
    time_context: DeviceTimeContext | None = None,
) -> int:
    """Decode an absolute SPL date through the target iPod's clock."""
    value = int(value or 0)
    if value >= MAC_EPOCH_OFFSET:
        return (time_context or current_device_time_context()).mac_to_unix(value)
    return value


def _eval_boolean(track_val: bool, rule: SmartPlaylistRule) -> bool:
    """Evaluate a boolean-type rule (is true / is false)."""
    action = rule.action_id
    match action:
        case 0x00000001:  # is true
            return track_val
        case 0x02000001:  # is false
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
    rule: SmartPlaylistRule | RuleGroup,
    track: dict,
    playlist_lookup: dict[int, set[int]] | None = None,
    time_context: DeviceTimeContext | None = None,
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
    if isinstance(rule, RuleGroup):
        return _eval_rule_container(
            rule.group,
            track,
            playlist_lookup,
            time_context,
        )

    ft = SPL_FIELD_TYPE_MAP.get(rule.field_id)

    if rule.field_id == 0x3C and rule.action_id in (0x00000400, 0x02000400):
        return _eval_binary_and(_get_int_value(track, rule.field_id), rule)

    match ft:
        case 1:  # SPLFT_STRING
            return _eval_string(_get_string_value(track, rule.field_id), rule)
        case 2:  # SPLFT_INT
            return _eval_int(_get_int_value(track, rule.field_id), rule)
        case 3:  # SPLFT_BOOLEAN
            return _eval_boolean(_get_bool_value(track, rule.field_id), rule)
        case 4:  # SPLFT_DATE
            return _eval_date(
                _get_date_value(track, rule.field_id),
                rule,
                time_context or current_device_time_context(),
            )
        case 5:  # SPLFT_PLAYLIST
            return _eval_playlist(track, rule, playlist_lookup)
        case 7:  # SPLFT_BINARY_AND
            return _eval_binary_and(_get_int_value(track, rule.field_id), rule)
        case _:
            # Unknown field type — default to no match
            return False


def _eval_rule_container(
    rules: SmartPlaylistRules,
    track: dict,
    playlist_lookup: dict[int, set[int]] | None,
    time_context: DeviceTimeContext | None,
) -> bool:
    """Evaluate one root or nested rules container."""
    if rules.conjunction.upper() == "OR":
        return any(
            eval_rule(node, track, playlist_lookup, time_context)
            for node in rules.rules
        )
    return all(
        eval_rule(node, track, playlist_lookup, time_context)
        for node in rules.rules
    )


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

    if base == SPL_LIMIT_SORT_RANDOM:
        return None, False  # handled specially
    if base == SPL_LIMIT_SORT_SONG_NAME:
        return (lambda t: (t.get("Title", "") or "").casefold()), False
    if base == SPL_LIMIT_SORT_ALBUM:
        return (lambda t: (t.get("Album", "") or "").casefold()), False
    if base == SPL_LIMIT_SORT_ARTIST:
        return (lambda t: (t.get("Artist", "") or "").casefold()), False
    if base == SPL_LIMIT_SORT_GENRE:
        return (lambda t: (t.get("Genre", "") or "").casefold()), False
    if base == SPL_LIMIT_SORT_MOST_RECENTLY_ADDED:
        return (lambda t: t.get("date_added", 0)), not reverse
    if base == SPL_LIMIT_SORT_MOST_OFTEN_PLAYED:
        return (lambda t: t.get("play_count_1", 0)), not reverse
    if base == SPL_LIMIT_SORT_MOST_RECENTLY_PLAYED:
        return (lambda t: t.get("last_played", 0)), not reverse
    if base == SPL_LIMIT_SORT_HIGHEST_RATING:
        return (lambda t: t.get("rating", 0)), not reverse
    return (lambda t: 0), False


def _track_limit_value(track: dict, limit_type: int) -> float:
    """Get the value a track contributes toward the limit total.

    Returns the track's contribution in the unit specified by limit_type.
    """
    if limit_type == SPL_LIMIT_TYPE_MINUTES:
        return track.get("length", 0) / (60 * 1000)
    if limit_type == SPL_LIMIT_TYPE_MB:
        return track.get("size", 0) / (1024 * 1024)
    if limit_type == SPL_LIMIT_TYPE_SONGS:
        return 1.0
    if limit_type == SPL_LIMIT_TYPE_HOURS:
        return track.get("length", 0) / (60 * 60 * 1000)
    if limit_type == SPL_LIMIT_TYPE_GB:
        return track.get("size", 0) / (1024 * 1024 * 1024)
    return 1.0


# ────────────────────────────────────────────────────────────
# Main evaluator
# ────────────────────────────────────────────────────────────

def spl_update(
    prefs: SmartPlaylistPrefs,
    rules: SmartPlaylistRules,
    tracks: list[dict],
    playlist_lookup: dict[int, set[int]] | None = None,
    time_context: DeviceTimeContext | None = None,
    *,
    is_cancelled: Callable[[], bool] | None = None,
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

    for index, track in enumerate(tracks):
        if index % 128 == 0 and is_cancelled is not None and is_cancelled():
            return []
        # Skip unchecked tracks if match_checked_only is set
        # (checked_flag=0 means checked, checked_flag=1 means unchecked in the parser)
        if prefs.match_checked_only and track.get("checked_flag", 0) != 0:
            continue

        if prefs.check_rules and rules.rules:
            match_result = _eval_rule_container(
                rules,
                track,
                playlist_lookup,
                time_context,
            )

            if match_result:
                selected.append(track)
        else:
            # Not checking rules → everything goes in
            selected.append(track)

    if not selected:
        return []

    if is_cancelled is not None and is_cancelled():
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

        for index, track in enumerate(selected):
            if index % 128 == 0 and is_cancelled is not None and is_cancelled():
                return []
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
    time_context: DeviceTimeContext | None = None,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[int]:
    """Convenience wrapper that accepts parsed dicts directly from the parser.

    Takes the raw smart_playlist_data / smart_playlist_rules dicts and converts
    them to dataclasses before evaluation.
    """
    from iopenpod.itunesdb_writer.mhod_spl_writer import prefs_from_parsed, rules_from_parsed

    prefs = prefs_from_parsed(parsed_prefs)
    rules = rules_from_parsed(parsed_rules)
    return spl_update(
        prefs,
        rules,
        tracks,
        playlist_lookup,
        time_context,
        is_cancelled=is_cancelled,
    )


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
