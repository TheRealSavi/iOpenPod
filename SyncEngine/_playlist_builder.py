"""Playlist building helpers — construct PlaylistInfo lists from parsed data.

Extracted from sync_executor.py.  These functions take parsed playlist
dicts (from _read_existing_database) and produce PlaylistInfo objects
ready for write_itunesdb().
"""

import base64
import logging
import os
from pathlib import Path

from iTunesDB_Writer.mhit_writer import TrackInfo
from iTunesDB_Writer.mhod_spl_writer import prefs_from_parsed, rules_from_parsed
from iTunesDB_Writer.mhyp_writer import PlaylistInfo, PlaylistItemMeta

logger = logging.getLogger(__name__)

# ── Playlist sort-order implementation ────────────────────────────────────
#
# The iPod firmware does NOT sort playlist tracks.  The MHIP order in the
# binary DB is exactly what the iPod displays.  We must sort the track list
# before writing.
#
# sort_order value → (primary_key, secondary_key) where each key is either:
#   - A string attribute name on TrackInfo / track-dict
#   - None (= no secondary)
# String fields sort case-insensitively; numeric fields sort ascending.
# "Sort Title" / "Sort Artist" / "Sort Album" override the base fields when
# present (matching iTunes behaviour — strips leading "The", etc.).

# Maps sort_order int → list of (track_dict_key, is_string, sort_override_key | None)
# The sort is stable so equal-primary items keep their original (or secondary) order.
_SORT_ORDER_KEYS: dict[int, list[tuple[str, bool, str | None]]] = {
    # 1 = Manual — no sort applied (preserved as-is)
    3: [("Title", True, "Sort Title")],
    4: [("Album", True, "Sort Album"), ("disc_number", False, None), ("track_number", False, None)],
    5: [("Artist", True, "Sort Artist"), ("Album", True, "Sort Album"), ("disc_number", False, None), ("track_number", False, None)],
    6: [("bitrate", False, None)],
    7: [("Genre", True, None), ("Artist", True, "Sort Artist"), ("Album", True, "Sort Album"), ("track_number", False, None)],
    8: [("filetype", True, None)],
    9: [("last_modified", False, None)],
    10: [("disc_number", False, None), ("track_number", False, None)],
    11: [("size", False, None)],
    12: [("length", False, None)],
    13: [("year", False, None), ("Artist", True, "Sort Artist"), ("Album", True, "Sort Album")],
    14: [("sample_rate_1", False, None)],
    15: [("Comment", True, None)],
    16: [("date_added", False, None)],
    17: [("eq_setting", True, None)],
    18: [("Composer", True, None)],
    20: [("play_count_1", False, None)],
    21: [("last_played", False, None)],
    22: [("disc_number", False, None), ("track_number", False, None)],
    23: [("rating", False, None)],
    24: [("date_released", False, None)],
    25: [("bpm", False, None)],
    26: [("Grouping", True, None)],
}


def _sort_key_for_track(track: dict, keys: list[tuple[str, bool, str | None]]) -> tuple:
    """Build a comparable sort-key tuple from a track dict."""
    parts: list = []
    for field, is_str, override in keys:
        val = None
        if override:
            val = track.get(override)
        if not val:
            val = track.get(field)
        if val is None:
            val = "" if is_str else 0
        if is_str:
            parts.append(str(val).casefold())
        else:
            parts.append(val if isinstance(val, (int, float)) else 0)
    return tuple(parts)


def sort_tracks_by_order(tracks: list[dict], sort_order: int) -> list[dict]:
    """Return *tracks* sorted according to *sort_order*.

    If sort_order is 0, 1 (Manual), or unknown, the list is returned as-is.
    This works on parsed track dicts (from the iTunesDB parser).
    """
    keys = _SORT_ORDER_KEYS.get(sort_order)
    if not keys:
        return tracks  # Manual / Default / unknown → preserve order
    return sorted(tracks, key=lambda t: _sort_key_for_track(t, keys))


def _sort_key_for_trackinfo(ti: TrackInfo, keys: list[tuple[str, bool, str | None]]) -> tuple:
    """Build a comparable sort-key tuple from a TrackInfo object."""
    # TrackInfo uses slightly different attribute names than parsed dicts.
    _TI_ATTR = {
        "Title": "title", "Artist": "artist", "Album": "album",
        "Album Artist": "album_artist", "Genre": "genre",
        "Composer": "composer", "Comment": "comment",
        "Grouping": "grouping", "filetype": "filetype",
        "bitrate": "bitrate", "size": "size", "length": "length",
        "year": "year", "track_number": "track_number",
        "disc_number": "disc_number", "bpm": "bpm",
        "rating": "rating", "play_count_1": "play_count",
        "skip_count": "skip_count", "sample_rate_1": "sample_rate",
        "date_added": "date_added", "last_modified": "date_modified",
        "last_played": "last_played", "date_released": "release_date",
    }
    parts: list = []
    for field, is_str, _override in keys:
        # TrackInfo has no sort-override fields; just use the base attribute
        attr = _TI_ATTR.get(field, field)
        val = getattr(ti, attr, None)
        if val is None:
            val = "" if is_str else 0
        if is_str:
            parts.append(str(val).casefold())
        else:
            parts.append(val if isinstance(val, (int, float)) else 0)
    return tuple(parts)


def sort_trackinfos_by_order(
    track_ids: list[int],
    sort_order: int,
    db_track_id_to_info: dict[int, TrackInfo],
) -> list[int]:
    """Return *track_ids* sorted according to *sort_order*.

    Looks up each db_track_id in *db_track_id_to_info* to read sort fields.
    Unknown db_track_ids are appended at the end.
    """
    keys = _SORT_ORDER_KEYS.get(sort_order)
    if not keys:
        return track_ids  # Manual / Default / unknown → preserve order

    # Partition into known and unknown
    known = [(tid, db_track_id_to_info[tid]) for tid in track_ids if tid in db_track_id_to_info]
    unknown = [tid for tid in track_ids if tid not in db_track_id_to_info]

    known.sort(key=lambda pair: _sort_key_for_trackinfo(pair[1], keys))
    return [tid for tid, _ in known] + unknown


def decode_raw_blob(value) -> bytes | None:
    """Decode a raw MHOD blob from parsed playlist data.

    The parser stores bytes, but mhbd_parser's replace_bytes_with_base64()
    converts them to base64 strings for JSON serialization. This function
    handles both cases.
    """
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        try:
            return base64.b64decode(value)
        except Exception:
            return None
    return None


def _source_path_key(path: str) -> str:
    try:
        return os.path.normcase(str(Path(path).expanduser().resolve()))
    except OSError:
        return os.path.normcase(str(Path(path).expanduser()))


def _mhsd5_type_value(playlist: dict) -> int:
    try:
        return int(playlist.get("mhsd5_type", 0) or 0)
    except (TypeError, ValueError):
        return 0


def build_and_evaluate_playlists(
    existing_tracks_data: list[dict],
    existing_playlists_raw: list[dict],
    existing_smart_raw: list[dict],
    all_track_infos: list[TrackInfo],
    user_playlists: list[dict],
    source_path_to_db_track_id: dict[str, int] | None = None,
) -> tuple[str, list[PlaylistInfo], list[PlaylistInfo]]:
    """Build PlaylistInfo lists and evaluate smart playlist rules.

    Returns (master_playlist_name, regular_playlists, smart_playlists)
    ready for write_itunesdb().
    """
    from ._track_conversion import trackinfo_to_eval_dict
    from .spl_evaluator import spl_update

    old_tid_to_db_track_id: dict[int, int] = {}
    for t in existing_tracks_data:
        tid = t.get("track_id", 0)
        db_track_id = t.get("db_track_id", t.get("db_id", 0))
        if tid and db_track_id:
            old_tid_to_db_track_id[tid] = db_track_id

    valid_db_track_ids: set[int] = {t.db_track_id for t in all_track_infos if t.db_track_id}
    eval_tracks = [trackinfo_to_eval_dict(t) for t in all_track_infos]

    source_lookup = {
        _source_path_key(path): db_track_id
        for path, db_track_id in (source_path_to_db_track_id or {}).items()
    }

    migrated_smart_raw, category_smart_raw = _partition_dataset5_playlists(
        existing_smart_raw,
    )
    if migrated_smart_raw:
        logger.info(
            "Migrating %d dataset-5 user smart playlist(s) to the visible playlist dataset",
            len(migrated_smart_raw),
        )
    visible_playlists_raw = _merge_visible_playlist_rows(
        existing_playlists_raw,
        migrated_smart_raw,
    )

    master_name, master_id, playlists = _build_regular_playlists(
        visible_playlists_raw, old_tid_to_db_track_id,
        valid_db_track_ids, eval_tracks, spl_update,
        source_lookup,
    )
    _sanitize_playlists(playlists, master_id)
    _rebuild_podcast_playlist(playlists, all_track_infos)

    smart_playlists = _build_smart_playlists(
        category_smart_raw, valid_db_track_ids, eval_tracks, spl_update,
    )

    _reevaluate_live_update(
        playlists, smart_playlists, valid_db_track_ids, eval_tracks, spl_update,
    )

    # ── Apply sort order to all playlists ─────────────────────
    db_track_id_to_info = {t.db_track_id: t for t in all_track_infos if t.db_track_id}
    for pl in playlists + smart_playlists:
        if pl.sortorder not in (0, 1) and pl.track_ids:
            pl.track_ids = sort_trackinfos_by_order(
                pl.track_ids, pl.sortorder, db_track_id_to_info,
            )
            # Item metadata is positional — clear it when we re-sort so
            # the writer generates fresh positional MHODs.
            pl.item_metadata = None

    return master_name, playlists, smart_playlists


def _partition_dataset5_playlists(
    playlists: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split user smart playlists from firmware browse categories."""

    user_smart: list[dict] = []
    categories: list[dict] = []
    for playlist in playlists:
        if _mhsd5_type_value(playlist):
            categories.append(playlist)
        else:
            user_smart.append(playlist)
    return user_smart, categories


def _merge_visible_playlist_rows(
    regular_playlists: list[dict],
    migrated_smart_playlists: list[dict],
) -> list[dict]:
    if not migrated_smart_playlists:
        return regular_playlists

    visible = list(regular_playlists)
    seen_ids = {
        playlist_id
        for playlist_id in (playlist.get("playlist_id", 0) for playlist in visible)
        if playlist_id
    }
    for playlist in migrated_smart_playlists:
        playlist_id = playlist.get("playlist_id", 0)
        if playlist_id and playlist_id in seen_ids:
            continue
        if playlist_id:
            seen_ids.add(playlist_id)
        visible.append(playlist)
    return visible


def _build_regular_playlists(
    existing_playlists_raw: list[dict],
    old_tid_to_db_track_id: dict[int, int],
    valid_db_track_ids: set[int],
    eval_tracks: list[dict],
    spl_update,
    source_path_to_db_track_id: dict[str, int],
) -> tuple[str, int | None, list[PlaylistInfo]]:
    """Build dataset-2 playlists, returning (master_name, master_id, playlists)."""
    master_playlist_name = "iPod"
    master_playlist_id: int | None = None
    playlists: list[PlaylistInfo] = []

    for pl in existing_playlists_raw:
        if pl.get("master_flag"):
            master_playlist_name = pl.get("Title", "iPod")
            master_playlist_id = pl.get("playlist_id")
            continue

        items = pl.get("items", [])
        track_ids = []
        item_meta = []
        for item in items:
            tid = item.get("track_id", 0)
            db_track_id = old_tid_to_db_track_id.get(tid, 0)
            if not db_track_id:
                db_track_id = item.get("db_track_id", item.get("db_id", 0))
            if not db_track_id:
                source_path = item.get("source_path") or item.get("_source_path")
                if source_path:
                    db_track_id = source_path_to_db_track_id.get(
                        _source_path_key(str(source_path)),
                        0,
                    )
            try:
                db_track_id = int(db_track_id or 0)
            except (TypeError, ValueError):
                db_track_id = 0
            if db_track_id in valid_db_track_ids:
                track_ids.append(db_track_id)
                item_meta.append(PlaylistItemMeta(
                    podcast_group_flag=item.get("podcast_group_flag", 0),
                    group_id=item.get("group_id", 0),
                    podcast_group_ref=item.get("group_id_ref", 0),
                ))

        info = PlaylistInfo(
            name=pl.get("Title", "Untitled"),
            track_ids=track_ids,
            playlist_id=pl.get("playlist_id"),
            master=False,
            sortorder=pl.get("sort_order", 0),
            podcast_flag=pl.get("podcast_flag", 0),
            raw_mhod100=decode_raw_blob(pl.get("playlist_prefs")),
            raw_mhod102=decode_raw_blob(pl.get("playlist_settings")),
            item_metadata=item_meta if item_meta else None,
        )

        # Evaluate smart playlist rules (dataset 2 smart playlists)
        prefs_data = pl.get("smart_playlist_data")
        rules_data = pl.get("smart_playlist_rules")
        if prefs_data and rules_data:
            info.smart_prefs = prefs_from_parsed(prefs_data)
            info.smart_rules = rules_from_parsed(rules_data)
            matched_db_track_ids = spl_update(
                info.smart_prefs, info.smart_rules, eval_tracks,
            )
            info.track_ids = [d for d in matched_db_track_ids if d in valid_db_track_ids]
            info.item_metadata = None
            logger.debug("SPL (ds2) '%s': %d tracks matched",
                         info.name, len(info.track_ids))

        playlists.append(info)

    logger.info("Prepared %d user playlists for writing", len(playlists))
    return master_playlist_name, master_playlist_id, playlists


def _sanitize_playlists(playlists: list[PlaylistInfo],
                        master_playlist_id: int | None) -> None:
    """Remove master duplicates and strip rogue master flags."""
    if master_playlist_id is not None:
        before = len(playlists)
        playlists[:] = [p for p in playlists
                        if p.playlist_id != master_playlist_id]
        dropped = before - len(playlists)
        if dropped:
            logger.warning("Dropped %d playlist(s) with master playlist_id=0x%X",
                           dropped, master_playlist_id)

    master_count = sum(1 for p in playlists if p.master)
    if master_count:
        logger.warning("Stripped master flag from %d user playlist(s) — "
                       "master is auto-generated", master_count)
        for p in playlists:
            p.master = False


def _rebuild_podcast_playlist(playlists: list[PlaylistInfo],
                              all_track_infos: list[TrackInfo]) -> None:
    """Ensure the Podcasts playlist reflects all current podcast tracks."""
    podcast_db_track_ids = [t.db_track_id for t in all_track_infos if t.media_type & 0x04]
    existing_podcast_pl = next((p for p in playlists if p.podcast_flag), None)

    if podcast_db_track_ids:
        if existing_podcast_pl is not None:
            existing_podcast_pl.track_ids = podcast_db_track_ids
            existing_podcast_pl.item_metadata = None
            logger.info("Rebuilt 'Podcasts' playlist with %d tracks",
                        len(podcast_db_track_ids))
        else:
            from iTunesDB_Writer.mhyp_writer import generate_playlist_id
            playlists.append(PlaylistInfo(
                name="Podcasts",
                track_ids=podcast_db_track_ids,
                playlist_id=generate_playlist_id(),
                podcast_flag=1,
            ))
            logger.info("Auto-created 'Podcasts' playlist with %d tracks",
                        len(podcast_db_track_ids))
    elif existing_podcast_pl is not None:
        playlists.remove(existing_podcast_pl)
        logger.info("Removed empty 'Podcasts' playlist (no podcast tracks)")


def _build_smart_playlists(
    existing_smart_raw: list[dict],
    valid_db_track_ids: set[int],
    eval_tracks: list[dict],
    spl_update,
) -> list[PlaylistInfo]:
    """Build dataset-5 smart playlists."""
    smart_playlists: list[PlaylistInfo] = []
    for pl in existing_smart_raw:
        prefs_data = pl.get("smart_playlist_data")
        rules_data = pl.get("smart_playlist_rules")
        mhsd5_type = _mhsd5_type_value(pl)

        info = PlaylistInfo(
            name=pl.get("Title", "Untitled"),
            playlist_id=pl.get("playlist_id"),
            master=bool(pl.get("master_flag", 0)) or bool(mhsd5_type),
            sortorder=pl.get("sort_order", 0),
            mhsd5_type=mhsd5_type,
            raw_mhod100=decode_raw_blob(pl.get("playlist_prefs")),
            raw_mhod102=decode_raw_blob(pl.get("playlist_settings")),
        )

        if prefs_data and rules_data:
            info.smart_prefs = prefs_from_parsed(prefs_data)
            info.smart_rules = rules_from_parsed(rules_data)
            matched_db_track_ids = spl_update(
                info.smart_prefs, info.smart_rules, eval_tracks,
            )

            if info.mhsd5_type:
                info.track_ids = [d for d in matched_db_track_ids if d in valid_db_track_ids]
                info.item_metadata = None
                logger.debug("SPL (ds5) '%s': %d tracks matched and assigned",
                             info.name, len(info.track_ids))
            elif info.smart_prefs.live_update:
                info.track_ids = [d for d in matched_db_track_ids if d in valid_db_track_ids]
                info.item_metadata = None
                logger.debug("SPL (ds5) '%s': %d tracks matched (live_update)",
                             info.name, len(info.track_ids))
            else:
                logger.debug("SPL (ds5) '%s': %d tracks would match "
                             "(live_update=False, keeping existing)",
                             info.name, len(matched_db_track_ids))

        smart_playlists.append(info)

    logger.info("Prepared %d smart playlists (dataset 5) for writing",
                len(smart_playlists))
    return smart_playlists


def _reevaluate_live_update(
    playlists: list[PlaylistInfo],
    smart_playlists: list[PlaylistInfo],
    valid_db_track_ids: set[int],
    eval_tracks: list[dict],
    spl_update,
) -> None:
    """Re-evaluate all live-update SPLs against the final track list."""
    for info in list(playlists) + [s for s in smart_playlists if not s.mhsd5_type]:
        if info.smart_prefs and info.smart_rules and info.smart_prefs.live_update:
            matched_db_track_ids = spl_update(
                info.smart_prefs, info.smart_rules, eval_tracks,
            )
            new_ids = [d for d in matched_db_track_ids if d in valid_db_track_ids]
            if new_ids != info.track_ids:
                logger.info("SPL live-update '%s': %d → %d tracks after "
                            "final re-evaluation",
                            info.name, len(info.track_ids), len(new_ids))
                info.track_ids = new_ids
                info.item_metadata = None
