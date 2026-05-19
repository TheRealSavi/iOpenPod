"""Public helpers for small iPod database rewrites without full sync."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from iTunesDB_Writer.mhit_writer import TrackInfo

if TYPE_CHECKING:
    from .contracts import SyncOutcome, SyncProgress

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlaylistWriteResult:
    """Outcome for a small playlist database rewrite."""

    success: bool
    playlist_name: str = ""
    matched_count: int = 0
    error: str = ""


def rename_master_playlist(ipod_path: str | Path, new_name: str) -> bool:
    """Rewrite the database with a new master playlist name."""

    state = _load_database_state(ipod_path)
    if state is None:
        return False

    tracks_data, playlists_raw, smart_raw, all_tracks = state
    return _write_tracks_and_playlists(
        ipod_path,
        tracks_data=tracks_data,
        playlists_raw=playlists_raw,
        smart_raw=smart_raw,
        all_tracks=all_tracks,
        user_playlists=[],
        master_playlist_name=new_name,
    )


def write_track_metadata_edits(
    ipod_path: str | Path,
    track_edits: dict[int, dict[str, tuple]],
) -> bool:
    """Apply pending track metadata/flag edits and rewrite the database."""

    state = _load_database_state(ipod_path)
    if state is None:
        return False

    tracks_data, playlists_raw, smart_raw, _all_tracks = state
    for track in tracks_data:
        db_track_id = track.get("db_track_id", track.get("db_id", 0))
        if db_track_id in track_edits:
            for field, (_, new_val) in track_edits[db_track_id].items():
                track[field] = new_val

    all_tracks = _tracks_to_infos(tracks_data, require_db_track_id=False)
    return _write_tracks_and_playlists(
        ipod_path,
        tracks_data=tracks_data,
        playlists_raw=playlists_raw,
        smart_raw=smart_raw,
        all_tracks=all_tracks,
        user_playlists=[],
    )


def quick_write_playlists(
    ipod_path: str | Path,
    user_playlists: list[dict],
    progress_callback: Callable[[SyncProgress], None] | None = None,
    on_complete: Callable[[], None] | None = None,
) -> SyncOutcome:
    """Rewrite the iPod database with only playlist changes."""

    from .contracts import SyncOutcome, SyncProgress

    result = SyncOutcome(success=True)

    def _progress(stage: str, cur: int, total: int, message: str = "") -> None:
        if progress_callback:
            progress_callback(SyncProgress(stage, cur, total, message=message))

    _progress("playlist_sync", 0, 3, "Reading iPod database...")
    state = _load_database_state(ipod_path, require_db_track_id=True)
    if state is None:
        result.success = False
        result.errors.append(("playlist_sync", "No existing database found on iPod"))
        return result

    tracks_data, playlists_raw, smart_raw, all_tracks = state

    _progress("playlist_sync", 1, 3, "Merging playlists...")
    _merge_user_playlists(playlists_raw, smart_raw, user_playlists)

    _progress("playlist_sync", 2, 3, "Writing database...")
    db_ok = _write_tracks_and_playlists(
        ipod_path,
        tracks_data=tracks_data,
        playlists_raw=playlists_raw,
        smart_raw=smart_raw,
        all_tracks=all_tracks,
        user_playlists=user_playlists,
    )
    if not db_ok:
        result.success = False
        result.errors.append(("playlist_sync", "Database write failed"))
        return result

    if on_complete:
        try:
            on_complete()
        except Exception as exc:
            logger.debug("Quick playlist completion callback failed: %s", exc)

    _progress("playlist_sync", 3, 3, "Playlists synced")
    return result


def write_user_playlist(
    ipod_path: str | Path,
    playlist: dict,
    user_playlists: list[dict],
) -> PlaylistWriteResult:
    """Write one edited/saved playlist plus any other pending playlist edits."""

    state = _load_database_state(ipod_path)
    if state is None:
        return PlaylistWriteResult(
            success=False,
            playlist_name=str(playlist.get("Title", "Untitled")),
            error="No existing database found on iPod.",
        )

    tracks_data, playlists_raw, smart_raw, all_tracks = state
    target_pid = playlist.get("playlist_id", 0)
    playlist_name = str(playlist.get("Title", "Untitled"))

    _merge_playlist(playlists_raw, smart_raw, playlist)
    pending = [
        pending_playlist
        for pending_playlist in user_playlists
        if pending_playlist.get("playlist_id", 0) != target_pid
    ]
    _merge_user_playlists(playlists_raw, smart_raw, pending)

    master_name, playlists, smart_playlists = _evaluate_tracks_and_playlists(
        tracks_data=tracks_data,
        playlists_raw=playlists_raw,
        smart_raw=smart_raw,
        all_tracks=all_tracks,
        user_playlists=[],
    )
    matched_count = _playlist_track_count(playlists, smart_playlists, target_pid)
    if not _write_evaluated_database(
        ipod_path,
        all_tracks=all_tracks,
        playlists=playlists,
        smart_playlists=smart_playlists,
        master_playlist_name=master_name,
    ):
        return PlaylistWriteResult(
            success=False,
            playlist_name=playlist_name,
            matched_count=matched_count,
            error="Database write returned False.",
        )

    return PlaylistWriteResult(
        success=True,
        playlist_name=playlist_name,
        matched_count=matched_count,
    )


def delete_playlist(
    ipod_path: str | Path,
    playlist: dict,
    user_playlists: list[dict],
) -> PlaylistWriteResult:
    """Remove one playlist and rewrite the database."""

    if playlist.get("master_flag"):
        return PlaylistWriteResult(
            success=False,
            playlist_name=str(playlist.get("Title", "Untitled")),
            error="The master playlist cannot be deleted.",
        )

    state = _load_database_state(ipod_path)
    if state is None:
        return PlaylistWriteResult(
            success=False,
            playlist_name=str(playlist.get("Title", "Untitled")),
            error="No existing database found on iPod.",
        )

    tracks_data, playlists_raw, smart_raw, all_tracks = state
    target_pid = playlist.get("playlist_id", 0)
    playlist_name = str(playlist.get("Title", "Untitled"))
    playlists_raw = [
        existing
        for existing in playlists_raw
        if existing.get("playlist_id") != target_pid
    ]
    smart_raw = [
        existing
        for existing in smart_raw
        if existing.get("playlist_id") != target_pid
    ]
    pending = [
        pending_playlist
        for pending_playlist in user_playlists
        if pending_playlist.get("playlist_id", 0) != target_pid
    ]
    _merge_user_playlists(playlists_raw, smart_raw, pending)

    master_name, playlists, smart_playlists = _evaluate_tracks_and_playlists(
        tracks_data=tracks_data,
        playlists_raw=playlists_raw,
        smart_raw=smart_raw,
        all_tracks=all_tracks,
        user_playlists=[],
    )
    if not _write_evaluated_database(
        ipod_path,
        all_tracks=all_tracks,
        playlists=playlists,
        smart_playlists=smart_playlists,
        master_playlist_name=master_name,
    ):
        return PlaylistWriteResult(
            success=False,
            playlist_name=playlist_name,
            error="Database write returned False.",
        )

    return PlaylistWriteResult(success=True, playlist_name=playlist_name)


def write_imported_playlist_from_db_track_ids(
    ipod_path: str | Path,
    playlist_name: str,
    db_track_ids: list[int],
    user_playlists: list[dict],
    playlist_id: int | None = None,
) -> PlaylistWriteResult:
    """Create a regular playlist from iPod database track IDs."""

    state = _load_database_state(ipod_path)
    if state is None:
        return PlaylistWriteResult(
            success=False,
            playlist_name=playlist_name,
            error="No existing database found on iPod.",
        )

    tracks_data, playlists_raw, smart_raw, all_tracks = state
    db_track_id_to_tid: dict[int, int] = {}
    for track in tracks_data:
        tid = track.get("track_id", 0)
        db_track_id = track.get("db_track_id", track.get("db_id", 0))
        if tid and db_track_id:
            db_track_id_to_tid[int(db_track_id)] = int(tid)

    playlist_items = []
    for db_track_id in db_track_ids:
        tid = db_track_id_to_tid.get(db_track_id)
        if tid:
            playlist_items.append({"track_id": tid})

    if not playlist_items:
        return PlaylistWriteResult(
            success=False,
            playlist_name=playlist_name,
            error="No tracks could be mapped to iPod database IDs.",
        )

    target_pid = playlist_id if playlist_id is not None else random.getrandbits(64)
    playlist = {
        "Title": playlist_name,
        "playlist_id": target_pid,
        "_isNew": True,
        "_source": "regular",
        "items": playlist_items,
    }
    playlists_raw.append(playlist)
    _merge_user_playlists(playlists_raw, smart_raw, user_playlists)

    master_name, playlists, smart_playlists = _evaluate_tracks_and_playlists(
        tracks_data=tracks_data,
        playlists_raw=playlists_raw,
        smart_raw=smart_raw,
        all_tracks=all_tracks,
        user_playlists=[],
    )
    matched_count = _playlist_track_count(playlists, smart_playlists, target_pid)
    if not _write_evaluated_database(
        ipod_path,
        all_tracks=all_tracks,
        playlists=playlists,
        smart_playlists=smart_playlists,
        master_playlist_name=master_name,
    ):
        return PlaylistWriteResult(
            success=False,
            playlist_name=playlist_name,
            matched_count=matched_count,
            error="Database write returned False.",
        )

    return PlaylistWriteResult(
        success=True,
        playlist_name=playlist_name,
        matched_count=matched_count,
    )


def _load_database_state(
    ipod_path: str | Path,
    *,
    require_db_track_id: bool = False,
) -> tuple[list[dict], list[dict], list[dict], list[TrackInfo]] | None:
    from ._db_io import read_existing_database

    existing_db = read_existing_database(Path(ipod_path))
    tracks_data = existing_db["tracks"]
    if not tracks_data:
        return None

    all_tracks = _tracks_to_infos(
        tracks_data,
        require_db_track_id=require_db_track_id,
    )
    return (
        tracks_data,
        list(existing_db["playlists"]),
        list(existing_db["smart_playlists"]),
        all_tracks,
    )


def _tracks_to_infos(
    tracks_data: list[dict],
    *,
    require_db_track_id: bool,
) -> list[TrackInfo]:
    from ._track_conversion import track_dict_to_info

    track_infos: list[TrackInfo] = []
    for track in tracks_data:
        track_info = track_dict_to_info(track)
        if require_db_track_id and not track_info.db_track_id:
            continue
        track_infos.append(track_info)
    return track_infos


def _merge_user_playlists(
    playlists_raw: list[dict],
    smart_raw: list[dict],
    user_playlists: list[dict],
) -> None:
    for user_playlist in user_playlists:
        if user_playlist.get("master_flag"):
            continue
        _merge_playlist(playlists_raw, smart_raw, user_playlist)


def _merge_playlist(
    playlists_raw: list[dict],
    smart_raw: list[dict],
    playlist: dict,
) -> None:
    playlist_id = playlist.get("playlist_id", 0)
    if playlist.get("_isNew", False):
        playlists_raw.append(playlist)
        return

    for idx, existing_playlist in enumerate(playlists_raw):
        if existing_playlist.get("playlist_id") == playlist_id:
            playlists_raw[idx] = playlist
            return

    for idx, existing_playlist in enumerate(smart_raw):
        if existing_playlist.get("playlist_id") == playlist_id:
            smart_raw[idx] = playlist
            return

    playlists_raw.append(playlist)


def _evaluate_tracks_and_playlists(
    *,
    tracks_data: list[dict],
    playlists_raw: list[dict],
    smart_raw: list[dict],
    all_tracks: list[TrackInfo],
    user_playlists: list[dict],
) -> tuple[str, list[Any], list[Any]]:
    from ._playlist_builder import build_and_evaluate_playlists

    return build_and_evaluate_playlists(
        tracks_data,
        playlists_raw,
        smart_raw,
        all_tracks,
        user_playlists,
    )


def _playlist_track_count(
    playlists: list[Any],
    smart_playlists: list[Any],
    playlist_id: int,
) -> int:
    for playlist in playlists:
        if playlist.playlist_id == playlist_id:
            return len(playlist.track_ids)
    for playlist in smart_playlists:
        if playlist.playlist_id == playlist_id:
            return len(playlist.track_ids)
    return 0


def _write_tracks_and_playlists(
    ipod_path: str | Path,
    *,
    tracks_data: list[dict],
    playlists_raw: list[dict],
    smart_raw: list[dict],
    all_tracks: list[TrackInfo],
    user_playlists: list[dict],
    master_playlist_name: str | None = None,
) -> bool:
    from .unknown_metadata import apply_unknown_placeholders

    apply_unknown_placeholders(all_tracks)
    current_master_name, playlists, smart_playlists = _evaluate_tracks_and_playlists(
        tracks_data=tracks_data,
        playlists_raw=playlists_raw,
        smart_raw=smart_raw,
        all_tracks=all_tracks,
        user_playlists=user_playlists,
    )
    return _write_evaluated_database(
        ipod_path,
        all_tracks=all_tracks,
        playlists=playlists,
        smart_playlists=smart_playlists,
        master_playlist_name=master_playlist_name or current_master_name,
    )


def _write_evaluated_database(
    ipod_path: str | Path,
    *,
    all_tracks: list[TrackInfo],
    playlists: list[Any],
    smart_playlists: list[Any],
    master_playlist_name: str,
) -> bool:
    from ._db_io import write_database

    db_ok = write_database(
        Path(ipod_path),
        all_tracks,
        playlists=playlists,
        smart_playlists=smart_playlists,
        master_playlist_name=master_playlist_name,
    )
    if not db_ok:
        return False

    try:
        apply_itunes_protections_from_tracks(ipod_path, all_tracks)
    except Exception as exc:
        logger.warning("iTunesPrefs protection failed (non-fatal): %s", exc)
    return True


def apply_itunes_protections_from_tracks(
    ipod_path: str | Path,
    all_tracks: list[TrackInfo],
) -> None:
    """Update iTunesPrefs from a track list after a quick database rewrite."""

    from .itunes_prefs import protect_from_itunes

    media_buckets = [
        (0x04, "podcast"),
        (0x08, "audiobook"),
        (0x40, "tv"),
        (0x20, "mv"),
        (0x02, "video"),
    ]
    totals: dict[str, list[int]] = {
        key: [0, 0, 0]
        for key in ("music", "video", "podcast", "audiobook", "tv", "mv")
    }
    for track in all_tracks:
        media_type = track.media_type
        bucket = "music"
        for mask, label in media_buckets:
            if media_type & mask:
                bucket = label
                break
        totals[bucket][0] += track.size
        totals[bucket][1] += track.length // 1000
        totals[bucket][2] += 1

    protect_from_itunes(
        Path(ipod_path),
        track_count=totals["music"][2],
        total_music_bytes=totals["music"][0],
        total_music_seconds=totals["music"][1],
        video_tracks=totals["video"][2],
        video_bytes=totals["video"][0],
        video_seconds=totals["video"][1],
        podcast_tracks=totals["podcast"][2],
        podcast_bytes=totals["podcast"][0],
        podcast_seconds=totals["podcast"][1],
        audiobook_tracks=totals["audiobook"][2],
        audiobook_bytes=totals["audiobook"][0],
        audiobook_seconds=totals["audiobook"][1],
        tv_show_tracks=totals["tv"][2],
        tv_show_bytes=totals["tv"][0],
        tv_show_seconds=totals["tv"][1],
        music_video_tracks=totals["mv"][2],
        music_video_bytes=totals["mv"][0],
        music_video_seconds=totals["mv"][1],
    )
