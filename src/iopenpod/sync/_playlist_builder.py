"""Playlist building helpers — construct PlaylistInfo lists from parsed data.

Extracted from sync_executor.py.  These functions take parsed playlist
dicts (from _read_existing_database) and produce PlaylistInfo objects
ready for write_itunesdb().
"""

import base64
import logging

from iopenpod.itunesdb_shared.constants import MEDIA_TYPE_PODCAST
from iopenpod.itunesdb_shared.playlist_properties import (
    playlist_description_from_row,
    playlist_property_raw_body_for_write,
)
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.itunesdb_writer.mhod_spl_writer import prefs_from_parsed, rules_from_parsed
from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo, PlaylistItemMeta

from .path_identity import coerce_int, stable_path_key

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


def _playlist_property_plist_raw(playlist: dict) -> bytes | None:
    return playlist_property_raw_body_for_write(playlist)


def _playlist_description(playlist: dict) -> str | None:
    description = playlist_description_from_row(playlist)
    return description if description or "playlist_description" in playlist else None


def _source_path_key(path: str) -> str:
    return stable_path_key(path)


def _mhsd5_type_value(playlist: dict) -> int:
    return coerce_int(playlist.get("mhsd5_type", 0))


def build_and_evaluate_playlists(
    existing_tracks_data: list[dict],
    dataset2_standard_playlists_raw: list[dict],
    dataset3_podcast_playlists_raw: list[dict],
    dataset5_smart_playlists_raw: list[dict],
    all_track_infos: list[TrackInfo],
    source_path_to_db_track_id: dict[str, int] | None = None,
) -> tuple[
    str,
    int | None,
    list[PlaylistInfo],
    str,
    int | None,
    list[PlaylistInfo],
    list[PlaylistInfo],
]:
    """Build PlaylistInfo lists and evaluate smart playlist rules.

    Returns (dataset2_master_name, dataset2_master_id, dataset2_playlists,
    dataset3_master_name, dataset3_master_id, dataset3_playlists,
    dataset5_playlists) ready for write_itunesdb().
    """
    from ._track_conversion import trackinfo_to_eval_dict
    from .spl_evaluator import spl_update

    old_tid_to_db_track_id: dict[int, int] = {}
    for t in existing_tracks_data:
        tid = coerce_int(t.get("track_id", 0))
        db_track_id = coerce_int(t.get("db_track_id", t.get("db_id", 0)))
        if tid and db_track_id:
            old_tid_to_db_track_id[tid] = db_track_id

    valid_db_track_ids: set[int] = set()
    for track_info in all_track_infos:
        db_track_id = coerce_int(track_info.db_track_id)
        if db_track_id:
            valid_db_track_ids.add(db_track_id)
    eval_tracks = [trackinfo_to_eval_dict(t) for t in all_track_infos]

    source_lookup = {
        _source_path_key(str(track.source_path)): db_track_id
        for track in all_track_infos
        if track.source_path and (db_track_id := coerce_int(track.db_track_id))
    }
    source_lookup.update(
        {
            _source_path_key(path): db_track_id
            for path, raw_db_track_id in (source_path_to_db_track_id or {}).items()
            if (db_track_id := coerce_int(raw_db_track_id))
        }
    )
    initial_playlist_lookup = _playlist_lookup_from_rows(
        [
            *dataset2_standard_playlists_raw,
            *dataset3_podcast_playlists_raw,
            *dataset5_smart_playlists_raw,
        ],
        old_tid_to_db_track_id,
        valid_db_track_ids,
        source_lookup,
    )

    master_name, _master_id, playlists = _build_standard_dataset_playlists(
        dataset2_standard_playlists_raw, old_tid_to_db_track_id,
        valid_db_track_ids, eval_tracks, spl_update,
        source_lookup, "dataset2", initial_playlist_lookup,
    )
    podcast_master_name, _podcast_master_id, podcast_playlists = _build_standard_dataset_playlists(
        dataset3_podcast_playlists_raw, old_tid_to_db_track_id,
        valid_db_track_ids, eval_tracks, spl_update,
        source_lookup, "dataset3", initial_playlist_lookup,
    )

    smart_playlists = _build_smart_playlists(
        dataset5_smart_playlists_raw,
        old_tid_to_db_track_id,
        valid_db_track_ids,
        eval_tracks,
        spl_update,
        source_lookup,
        initial_playlist_lookup,
    )

    _reevaluate_live_update(
        playlists + podcast_playlists,
        smart_playlists,
        valid_db_track_ids,
        eval_tracks,
        spl_update,
    )
    _sync_podcast_playlist_membership(playlists, podcast_playlists, all_track_infos)

    # ── Apply sort order to all playlists ─────────────────────
    db_track_id_to_info = {t.db_track_id: t for t in all_track_infos if t.db_track_id}
    for pl in playlists + podcast_playlists + smart_playlists:
        if pl.sortorder not in (0, 1) and pl.track_ids:
            pl.track_ids = sort_trackinfos_by_order(
                pl.track_ids, pl.sortorder, db_track_id_to_info,
            )
            # Item metadata is positional — clear it when we re-sort so
            # the writer generates fresh positional MHODs.
            pl.item_metadata = None

    return (
        master_name,
        _master_id,
        playlists,
        podcast_master_name,
        _podcast_master_id,
        podcast_playlists,
        smart_playlists,
    )


def _is_podcast_track(track: TrackInfo) -> bool:
    return bool(
        getattr(track, "media_type", 0) & MEDIA_TYPE_PODCAST
        or getattr(track, "podcast_flag", 0)
    )


def _sync_podcast_playlist_membership(
    playlists: list[PlaylistInfo],
    podcast_playlists: list[PlaylistInfo],
    all_track_infos: list[TrackInfo],
) -> None:
    """Keep the special Podcasts playlist aligned with podcast track contents."""

    podcast_db_track_ids = [
        track.db_track_id
        for track in all_track_infos
        if track.db_track_id and _is_podcast_track(track)
    ]
    targets = [
        playlist
        for playlist in [*playlists, *podcast_playlists]
        if playlist.podcast_flag
    ]

    if not targets and podcast_db_track_ids:
        podcast_playlist = PlaylistInfo(
            name="Podcasts",
            track_ids=[],
            podcast_flag=1,
        )
        podcast_playlists.append(podcast_playlist)
        targets.append(podcast_playlist)

    for playlist in targets:
        if playlist.track_ids != podcast_db_track_ids:
            logger.info(
                "Podcast playlist '%s': synced to %d podcast track(s)",
                playlist.name,
                len(podcast_db_track_ids),
            )
            playlist.track_ids = list(podcast_db_track_ids)
            playlist.item_metadata = None


def _playlist_lookup_from_rows(
    playlist_rows: list[dict],
    old_tid_to_db_track_id: dict[int, int],
    valid_db_track_ids: set[int],
    source_path_to_db_track_id: dict[str, int],
) -> dict[int, set[int]]:
    playlist_lookup: dict[int, set[int]] = {}
    for playlist in playlist_rows:
        playlist_id = playlist.get("playlist_id")
        if not playlist_id or playlist.get("master_flag"):
            continue
        try:
            lookup_id = int(playlist_id)
        except (TypeError, ValueError):
            continue
        track_ids, _item_meta = _playlist_track_ids_and_metadata(
            playlist.get("items", []),
            old_tid_to_db_track_id,
            valid_db_track_ids,
            source_path_to_db_track_id,
        )
        playlist_lookup.setdefault(lookup_id, set()).update(track_ids)
    return playlist_lookup


def _playlist_lookup_from_infos(
    playlist_groups: list[list[PlaylistInfo]],
) -> dict[int, set[int]]:
    playlist_lookup: dict[int, set[int]] = {}
    for playlists in playlist_groups:
        for playlist in playlists:
            if playlist.playlist_id is None or playlist.master:
                continue
            playlist_lookup.setdefault(int(playlist.playlist_id), set()).update(
                playlist.track_ids
            )
    return playlist_lookup


def _playlist_track_ids_and_metadata(
    items: list[dict],
    old_tid_to_db_track_id: dict[int, int],
    valid_db_track_ids: set[int],
    source_path_to_db_track_id: dict[str, int],
) -> tuple[list[int], list[PlaylistItemMeta] | None]:
    """Resolve parsed MHIP rows to db_track_ids while preserving item metadata."""

    track_ids: list[int] = []
    item_meta: list[PlaylistItemMeta] = []
    for item in items:
        tid = item.get("track_id", 0)
        db_track_id = old_tid_to_db_track_id.get(coerce_int(tid), 0)
        if not db_track_id:
            db_track_id = item.get("db_track_id", item.get("db_id", 0))
        if not db_track_id:
            source_path = item.get("source_path") or item.get("_source_path")
            if source_path:
                db_track_id = source_path_to_db_track_id.get(
                    _source_path_key(str(source_path)),
                    0,
                )
        db_track_id = coerce_int(db_track_id)
        if db_track_id in valid_db_track_ids:
            track_ids.append(db_track_id)
            item_meta.append(PlaylistItemMeta(
                podcast_group_flag=item.get("podcast_group_flag", 0),
                group_id=item.get("group_id", 0),
                podcast_group_ref=item.get("group_id_ref", 0),
                track_persistent_id=item.get("track_persistent_id", 0),
                mhip_persistent_id=item.get("mhip_persistent_id", 0),
            ))

    return track_ids, item_meta if item_meta else None


def _build_standard_dataset_playlists(
    selected_standard_playlist_rows: list[dict],
    old_tid_to_db_track_id: dict[int, int],
    valid_db_track_ids: set[int],
    eval_tracks: list[dict],
    spl_update,
    source_path_to_db_track_id: dict[str, int],
    source_dataset_name: str,
    playlist_lookup: dict[int, set[int]] | None,
) -> tuple[str, int | None, list[PlaylistInfo]]:
    """Build dataset-2/3 playlists, returning (master_name, master_id, rows).

    The generated writer always emits one master row first for dataset 2/3.
    Existing master rows therefore contribute their name and persistent ID; all
    non-master rows are passed through without relocating or reclassifying them.
    More than one master row is ambiguous and is treated as malformed input
    rather than being guessed into shape.
    """
    master_playlist_name = "iPod"
    master_playlist_id: int | None = None
    playlists: list[PlaylistInfo] = []
    master_rows = [pl for pl in selected_standard_playlist_rows if pl.get("master_flag")]
    if len(master_rows) > 1:
        raise ValueError(
            f"{source_dataset_name} contains {len(master_rows)} master_flag playlist rows"
        )

    for pl in selected_standard_playlist_rows:
        if pl.get("master_flag"):
            master_playlist_name = pl.get("Title", "iPod")
            master_playlist_id = pl.get("playlist_id")
            continue

        track_ids, item_meta = _playlist_track_ids_and_metadata(
            pl.get("items", []),
            old_tid_to_db_track_id,
            valid_db_track_ids,
            source_path_to_db_track_id,
        )

        info = PlaylistInfo(
            name=pl.get("Title", "Untitled"),
            track_ids=track_ids,
            playlist_id=pl.get("playlist_id"),
            master=False,
            sortorder=pl.get("sort_order", 0),
            podcast_flag=pl.get("podcast_flag", 0),
            mhsd5_type=_mhsd5_type_value(pl),
            raw_mhod100=decode_raw_blob(pl.get("playlist_prefs")),
            raw_mhod102=decode_raw_blob(pl.get("playlist_settings")),
            raw_mhod55=_playlist_property_plist_raw(pl),
            playlist_description=_playlist_description(pl),
            item_metadata=item_meta,
        )

        # Evaluate smart playlist rules (dataset 2 smart playlists)
        prefs_data = pl.get("smart_playlist_data")
        rules_data = pl.get("smart_playlist_rules")
        if prefs_data and rules_data:
            info.smart_prefs = prefs_from_parsed(prefs_data)
            info.smart_rules = rules_from_parsed(rules_data)
            matched_db_track_ids = spl_update(
                info.smart_prefs,
                info.smart_rules,
                eval_tracks,
                playlist_lookup,
            )
            info.track_ids = [d for d in matched_db_track_ids if d in valid_db_track_ids]
            info.item_metadata = None
            logger.debug("SPL (ds2) '%s': %d tracks matched",
                         info.name, len(info.track_ids))

        playlists.append(info)

    logger.info(
        "Prepared %d playlist row(s) from %s",
        len(playlists),
        source_dataset_name,
    )
    return master_playlist_name, master_playlist_id, playlists


def _build_smart_playlists(
    dataset5_smart_playlist_rows: list[dict],
    old_tid_to_db_track_id: dict[int, int],
    valid_db_track_ids: set[int],
    eval_tracks: list[dict],
    spl_update,
    source_path_to_db_track_id: dict[str, int],
    playlist_lookup: dict[int, set[int]] | None,
) -> list[PlaylistInfo]:
    """Build dataset-5 smart playlists."""
    smart_playlists: list[PlaylistInfo] = []
    for pl in dataset5_smart_playlist_rows:
        prefs_data = pl.get("smart_playlist_data")
        rules_data = pl.get("smart_playlist_rules")
        mhsd5_type = _mhsd5_type_value(pl)
        track_ids, item_meta = _playlist_track_ids_and_metadata(
            pl.get("items", []),
            old_tid_to_db_track_id,
            valid_db_track_ids,
            source_path_to_db_track_id,
        )

        info = PlaylistInfo(
            name=pl.get("Title", "Untitled"),
            playlist_id=pl.get("playlist_id"),
            # Preserve the dataset-5 type byte exactly as parsed. Older code
            # inferred master=True from mhsd5_type, but that silently repairs
            # missing category markers and loses evidence from device samples.
            master=bool(pl.get("master_flag", 0)),
            track_ids=track_ids,
            sortorder=pl.get("sort_order", 0),
            mhsd5_type=mhsd5_type,
            raw_mhod100=decode_raw_blob(pl.get("playlist_prefs")),
            raw_mhod102=decode_raw_blob(pl.get("playlist_settings")),
            raw_mhod55=_playlist_property_plist_raw(pl),
            playlist_description=_playlist_description(pl),
            item_metadata=item_meta,
        )

        if prefs_data and rules_data:
            info.smart_prefs = prefs_from_parsed(prefs_data)
            info.smart_rules = rules_from_parsed(rules_data)
            if not info.mhsd5_type and info.smart_prefs.live_update:
                matched_db_track_ids = spl_update(
                    info.smart_prefs,
                    info.smart_rules,
                    eval_tracks,
                    playlist_lookup,
                )
                info.track_ids = [d for d in matched_db_track_ids if d in valid_db_track_ids]
                info.item_metadata = None
                logger.debug("SPL (ds5) '%s': %d tracks matched (live_update)",
                             info.name, len(info.track_ids))
            else:
                logger.debug("SPL (ds5) '%s': keeping parsed membership "
                             "(mhsd5_type=%d, live_update=%s)",
                             info.name, info.mhsd5_type,
                             bool(info.smart_prefs.live_update))

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
            playlist_lookup = _playlist_lookup_from_infos([playlists, smart_playlists])
            matched_db_track_ids = spl_update(
                info.smart_prefs,
                info.smart_rules,
                eval_tracks,
                playlist_lookup,
            )
            new_ids = [d for d in matched_db_track_ids if d in valid_db_track_ids]
            if new_ids != info.track_ids:
                logger.info("SPL live-update '%s': %d → %d tracks after "
                            "final re-evaluation",
                            info.name, len(info.track_ids), len(new_ids))
                info.track_ids = new_ids
                info.item_metadata = None
