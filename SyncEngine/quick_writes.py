"""Public helpers for dumping cached iTunesDB state without a full sync."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from iTunesDB_Shared.constants import (
    MEDIA_TYPE_AUDIOBOOK,
    MEDIA_TYPE_MUSIC_VIDEO,
    MEDIA_TYPE_PODCAST,
    MEDIA_TYPE_TV_SHOW,
    MEDIA_TYPE_VIDEO,
)
from iTunesDB_Writer.mhit_writer import TrackInfo

if TYPE_CHECKING:
    from .contracts import SyncProgress

logger = logging.getLogger(__name__)


@dataclass
class QuickWriteResult:
    """Outcome from writing a cached iTunesDB snapshot."""

    success: bool
    error: str = ""
    errors: list[tuple[str, str]] = field(default_factory=list)
    playlist_counts: dict[int, int] = field(default_factory=dict)
    master_playlist_name: str = ""
    track_count: int = 0

    @classmethod
    def failed(cls, stage: str, message: str) -> QuickWriteResult:
        return cls(success=False, error=message, errors=[(stage, message)])


def write_cached_itunesdb(
    ipod_path: str | Path,
    *,
    tracks_data: list[dict[str, Any]],
    playlists_data: list[dict[str, Any]],
    artwork_sources: Mapping[int, str] | None = None,
    progress_callback: Callable[[SyncProgress], None] | None = None,
) -> QuickWriteResult:
    """Write the supplied cached tracks/playlists as the device iTunesDB.

    Callers own cache mutation. This function does not know why the cache
    changed; it converts the current cache snapshot, evaluates playlists, and
    writes the final iTunesDB/SQLite/iTunesPrefs state. If artwork_sources
    are provided, the ArtworkDB and ithmb outputs are updated alongside
    the iTunesDB write.
    """

    from .contracts import SyncProgress
    from .unknown_metadata import apply_unknown_placeholders

    def _progress(current: int, total: int, message: str) -> None:
        if progress_callback is not None:
            progress_callback(
                SyncProgress("quick_write", current, total, message=message)
            )

    if not tracks_data and not playlists_data:
        return QuickWriteResult.failed(
            "quick_write",
            "No cached tracks available to write.",
        )

    total_steps = 3
    _progress(0, total_steps, "Preparing cached database...")
    all_tracks = _tracks_to_infos(tracks_data)
    apply_unknown_placeholders(all_tracks)
    playlists_raw, smart_raw = _split_cached_playlists(playlists_data)

    _progress(1, total_steps, "Building playlists...")
    master_name, playlists, smart_playlists = _evaluate_tracks_and_playlists(
        tracks_data=tracks_data,
        playlists_raw=playlists_raw,
        smart_raw=smart_raw,
        all_tracks=all_tracks,
    )
    playlist_counts = _playlist_counts(playlists, smart_playlists)

    _progress(2, total_steps, "Writing database...")
    if not _write_evaluated_database(
        ipod_path,
        all_tracks=all_tracks,
        playlists=playlists,
        smart_playlists=smart_playlists,
        master_playlist_name=master_name,
        pc_file_paths=dict(artwork_sources) if artwork_sources else None,
    ):
        return QuickWriteResult.failed(
            "quick_write",
            "Database write returned False.",
        )

    _progress(3, total_steps, "Quick write complete")
    return QuickWriteResult(
        success=True,
        playlist_counts=playlist_counts,
        master_playlist_name=master_name,
        track_count=len(all_tracks),
    )


def _tracks_to_infos(tracks_data: list[dict[str, Any]]) -> list[TrackInfo]:
    from ._track_conversion import track_dict_to_info

    track_infos: list[TrackInfo] = []
    for track in tracks_data:
        track_info = track_dict_to_info(track)
        track_infos.append(track_info)
    return track_infos


def _split_cached_playlists(
    playlists_data: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    playlists_raw: list[dict[str, Any]] = []
    smart_raw: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for playlist in playlists_data:
        playlist_id = int(playlist.get("playlist_id", 0) or 0)
        if playlist_id and playlist_id in seen_ids:
            continue
        if playlist_id:
            seen_ids.add(playlist_id)

        row = dict(playlist)
        items = row.get("items")
        if isinstance(items, list):
            row["mhip_child_count"] = len(items)

        if _is_ipod_category_playlist(row):
            smart_raw.append(row)
        else:
            playlists_raw.append(row)

    return playlists_raw, smart_raw


def _mhsd5_type_value(playlist: dict[str, Any]) -> int:
    try:
        return int(playlist.get("mhsd5_type", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _is_ipod_category_playlist(playlist: dict[str, Any]) -> bool:
    """Return whether a playlist belongs in MHSD type 5.

    User-created smart playlists must remain in the normal playlist dataset so
    the iPod firmware shows them under Playlists.  Dataset 5 is reserved here
    for built-in browse categories such as Music, Movies, and Audiobooks.
    """

    return playlist.get("_source") == "category" or bool(_mhsd5_type_value(playlist))


def _evaluate_tracks_and_playlists(
    *,
    tracks_data: list[dict[str, Any]],
    playlists_raw: list[dict[str, Any]],
    smart_raw: list[dict[str, Any]],
    all_tracks: list[TrackInfo],
) -> tuple[str, list[Any], list[Any]]:
    from ._playlist_builder import build_and_evaluate_playlists

    return build_and_evaluate_playlists(
        tracks_data,
        playlists_raw,
        smart_raw,
        all_tracks,
        [],
    )


def _playlist_counts(
    playlists: list[Any],
    smart_playlists: list[Any],
) -> dict[int, int]:
    counts: dict[int, int] = {}
    for playlist in [*playlists, *smart_playlists]:
        playlist_id = int(getattr(playlist, "playlist_id", 0) or 0)
        if playlist_id:
            counts[playlist_id] = len(getattr(playlist, "track_ids", []) or [])
    return counts


def _write_evaluated_database(
    ipod_path: str | Path,
    *,
    all_tracks: list[TrackInfo],
    playlists: list[Any],
    smart_playlists: list[Any],
    master_playlist_name: str,
    pc_file_paths: Mapping[int, str] | None = None,
) -> bool:
    from ._db_io import write_database

    db_ok = write_database(
        Path(ipod_path),
        all_tracks,
        pc_file_paths=dict(pc_file_paths) if pc_file_paths else None,
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
        (MEDIA_TYPE_PODCAST, "podcast"),
        (MEDIA_TYPE_AUDIOBOOK, "audiobook"),
        (MEDIA_TYPE_TV_SHOW, "tv"),
        (MEDIA_TYPE_MUSIC_VIDEO, "mv"),
        (MEDIA_TYPE_VIDEO, "video"),
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
