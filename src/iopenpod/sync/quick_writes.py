"""Public helpers for dumping cached iTunesDB state without a full sync."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from iopenpod.device.filesystem_profile import FilesystemProfile
from iopenpod.device.write_guard import (
    DatabaseGeneration,
    DeviceWriteGuard,
    DeviceWriteSafetyError,
)
from iopenpod.device.write_readiness import (
    inspect_device_write_readiness,
    revalidate_device_write_readiness,
    volume_lock_key,
)
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo

from .database_commit import DatabaseCommitPayload, write_database_commit

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
    newer_changes_pending: bool = False
    database_generation: DatabaseGeneration | None = None

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
    expected_database_generation: DatabaseGeneration | None = None,
    reported_volume_format: str = "",
    expected_volume_identity_key: str = "",
) -> QuickWriteResult:
    """Write the supplied cached tracks/playlists as the device iTunesDB.

    Callers own cache mutation. This function does not know why the cache
    changed; it converts the current cache snapshot, evaluates playlists, and
    writes the final iTunesDB/SQLite/iTunesPrefs state. If artwork_sources
    are provided, the ArtworkDB and ithmb outputs are updated alongside
    the iTunesDB write.
    """

    if not tracks_data and not playlists_data:
        return QuickWriteResult.failed(
            "quick_write",
            "No cached tracks available to write.",
        )

    try:
        filesystem_profile = inspect_device_write_readiness(
            ipod_path,
            reported_volume_format=reported_volume_format,
        )
        current_volume_key = volume_lock_key(filesystem_profile)
        if (
            expected_volume_identity_key
            and current_volume_key != expected_volume_identity_key
        ):
            raise DeviceWriteSafetyError(
                "A different volume is mounted at the selected iPod path. "
                "iOpenPod stopped before the quick write. Reconnect and reload "
                "the iPod."
            )
        with DeviceWriteGuard(
            ipod_path,
            volume_key=current_volume_key,
            expected_database_generation=expected_database_generation,
        ) as write_guard:
            filesystem_profile = revalidate_device_write_readiness(
                filesystem_profile,
                probe_case_sensitivity=True,
            )
            return _write_cached_itunesdb_guarded(
                ipod_path,
                tracks_data=tracks_data,
                playlists_data=playlists_data,
                artwork_sources=artwork_sources,
                progress_callback=progress_callback,
                write_guard=write_guard,
                filesystem_profile=filesystem_profile,
            )
    except DeviceWriteSafetyError as exc:
        logger.error("Quick write stopped by device safety guard: %s", exc)
        return QuickWriteResult.failed("filesystem_safety", str(exc))


def _write_cached_itunesdb_guarded(
    ipod_path: str | Path,
    *,
    tracks_data: list[dict[str, Any]],
    playlists_data: list[dict[str, Any]],
    artwork_sources: Mapping[int, str] | None,
    progress_callback: Callable[[SyncProgress], None] | None,
    write_guard: DeviceWriteGuard,
    filesystem_profile: FilesystemProfile,
) -> QuickWriteResult:
    """Build and commit one cached snapshot while holding its device guard."""

    from .contracts import SyncProgress
    from .unknown_metadata import apply_unknown_placeholders

    def _progress(current: int, total: int, message: str) -> None:
        if progress_callback is not None:
            progress_callback(
                SyncProgress("quick_write", current, total, message=message)
            )

    total_steps = 3
    _progress(0, total_steps, "Preparing cached database...")
    all_tracks = _tracks_to_infos(tracks_data)
    apply_unknown_placeholders(all_tracks)
    (
        dataset2_playlist_rows,
        dataset3_playlist_rows,
        dataset5_playlist_rows,
    ) = _split_cached_playlists(playlists_data)

    _progress(1, total_steps, "Building playlists...")
    (
        master_name,
        master_playlist_id,
        playlists,
        podcast_master_name,
        podcast_master_playlist_id,
        podcast_playlists,
        smart_playlists,
    ) = _evaluate_tracks_and_playlists(
        tracks_data=tracks_data,
        dataset2_playlist_rows=dataset2_playlist_rows,
        dataset3_playlist_rows=dataset3_playlist_rows,
        dataset5_playlist_rows=dataset5_playlist_rows,
        all_tracks=all_tracks,
    )
    playlist_counts = _playlist_counts(playlists, podcast_playlists, smart_playlists)

    _progress(2, total_steps, "Writing database...")
    if not _write_evaluated_database(
        ipod_path,
        all_tracks=all_tracks,
        playlists=playlists,
        podcast_playlists=podcast_playlists,
        smart_playlists=smart_playlists,
        master_playlist_name=master_name,
        master_playlist_id=master_playlist_id,
        podcast_master_playlist_name=podcast_master_name,
        podcast_master_playlist_id=podcast_master_playlist_id,
        pc_file_paths=dict(artwork_sources) if artwork_sources else None,
        write_guard=write_guard,
        filesystem_profile=filesystem_profile,
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
        database_generation=getattr(
            write_guard,
            "starting_database_generation",
            None,
        ),
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    dataset2_playlist_rows: list[dict[str, Any]] = []
    dataset3_playlist_rows: list[dict[str, Any]] = []
    dataset5_playlist_rows: list[dict[str, Any]] = []

    def _playlist_id(playlist: dict[str, Any]) -> int:
        try:
            return int(playlist.get("playlist_id", 0) or 0)
        except (TypeError, ValueError):
            return 0

    dataset3_source_ids = {
        playlist_id
        for playlist in playlists_data
        if (
            not playlist.get("master_flag")
            and (playlist_id := _playlist_id(playlist))
            and _playlist_dataset_type(playlist) == 3
        )
    }
    uses_dataset3 = any(
        _playlist_dataset_type(playlist) == 3
        or playlist.get("_mhsd_result_key") == "mhlp_podcast"
        for playlist in playlists_data
    )

    def _dataset_row(playlist: dict[str, Any], dataset_type: int) -> dict[str, Any]:
        row = dict(playlist)
        row["_mhsd_dataset_type"] = dataset_type
        row["_mhsd_result_key"] = {2: "mhlp", 3: "mhlp_podcast", 5: "mhlp_smart"}[
            dataset_type
        ]
        if dataset_type in (2, 3):
            row.setdefault("_source", "regular")
        items = row.get("items")
        if isinstance(items, list):
            row["mhip_child_count"] = len(items)
        return row

    for playlist in playlists_data:
        row = dict(playlist)
        items = row.get("items")
        if isinstance(items, list):
            row["mhip_child_count"] = len(items)

        dataset_type = _playlist_dataset_type(row)
        if dataset_type == 3:
            dataset3_playlist_rows.append(row)
        elif dataset_type == 5 or _is_ipod_category_playlist(row):
            dataset5_playlist_rows.append(row)
        elif row.get("_source") == "podcast":
            row.setdefault("_mhsd_dataset_type", 3)
            row.setdefault("_mhsd_result_key", "mhlp_podcast")
            dataset3_playlist_rows.append(row)
        else:
            row.setdefault("_mhsd_dataset_type", 2)
            row.setdefault("_mhsd_result_key", "mhlp")
            dataset2_playlist_rows.append(row)
            playlist_id = _playlist_id(row)
            if (
                uses_dataset3
                and playlist_id
                and playlist_id not in dataset3_source_ids
                and not row.get("master_flag")
                and _is_regular_playlist_mirror_candidate(row)
            ):
                dataset3_playlist_rows.append(_dataset_row(row, 3))

    return dataset2_playlist_rows, dataset3_playlist_rows, dataset5_playlist_rows


def _mhsd5_type_value(playlist: dict[str, Any]) -> int:
    try:
        return int(playlist.get("mhsd5_type", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _is_ipod_category_playlist(playlist: dict[str, Any]) -> bool:
    """Return whether an origin-less pending playlist should be written to MHSD 5.

    Parsed cache rows should already carry ``_mhsd_dataset_type`` and are routed
    by that origin before this predicate runs. This helper only handles new UI
    rows/imports that have not yet lived in an on-disk MHSD bucket.
    """

    dataset_type = _playlist_dataset_type(playlist)
    if dataset_type:
        return dataset_type == 5
    return playlist.get("_source") == "category" or bool(_mhsd5_type_value(playlist))


def _is_regular_playlist_mirror_candidate(playlist: dict[str, Any]) -> bool:
    dataset_type = _playlist_dataset_type(playlist)
    if dataset_type not in (0, 2):
        return False
    if _is_ipod_category_playlist(playlist):
        return False
    if playlist.get("podcast_flag", 0) == 1 or playlist.get("_source") == "podcast":
        return False
    return True


def _playlist_dataset_type(playlist: dict[str, Any]) -> int:
    try:
        return int(playlist.get("_mhsd_dataset_type", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _evaluate_tracks_and_playlists(
    *,
    tracks_data: list[dict[str, Any]],
    dataset2_playlist_rows: list[dict[str, Any]],
    dataset3_playlist_rows: list[dict[str, Any]],
    dataset5_playlist_rows: list[dict[str, Any]],
    all_tracks: list[TrackInfo],
) -> tuple[str, int | None, list[Any], str, int | None, list[Any], list[Any]]:
    from ._playlist_builder import build_and_evaluate_playlists

    return build_and_evaluate_playlists(
        tracks_data,
        dataset2_playlist_rows,
        dataset3_playlist_rows,
        dataset5_playlist_rows,
        all_tracks,
    )


def _playlist_counts(
    playlists: list[Any],
    podcast_playlists: list[Any],
    smart_playlists: list[Any],
) -> dict[int, int]:
    counts: dict[int, int] = {}
    for playlist in [*playlists, *podcast_playlists, *smart_playlists]:
        playlist_id = int(getattr(playlist, "playlist_id", 0) or 0)
        if playlist_id:
            counts[playlist_id] = len(getattr(playlist, "track_ids", []) or [])
    return counts


def _write_evaluated_database(
    ipod_path: str | Path,
    *,
    all_tracks: list[TrackInfo],
    playlists: list[Any],
    podcast_playlists: list[Any],
    smart_playlists: list[Any],
    master_playlist_name: str,
    master_playlist_id: int | None,
    podcast_master_playlist_name: str,
    podcast_master_playlist_id: int | None,
    pc_file_paths: Mapping[int, str] | None = None,
    write_guard: DeviceWriteGuard | None = None,
    filesystem_profile: FilesystemProfile | None = None,
) -> bool:
    return write_database_commit(
        ipod_path,
        DatabaseCommitPayload(
            all_tracks=all_tracks,
            pc_file_paths=dict(pc_file_paths) if pc_file_paths else None,
            playlists=playlists,
            podcast_playlists=podcast_playlists,
            smart_playlists=smart_playlists,
            master_playlist_name=master_playlist_name,
            master_playlist_id=master_playlist_id,
            podcast_master_playlist_name=podcast_master_playlist_name,
            podcast_master_playlist_id=podcast_master_playlist_id,
        ),
        protect_itunes=True,
        include_photo_totals=False,
        write_guard=write_guard,
        filesystem_profile=filesystem_profile,
    )
