"""Shared database commit flow for full sync and quick writes."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from iopenpod.device.durability import flush_filesystem
from iopenpod.device.filesystem_profile import FilesystemProfile
from iopenpod.device.write_guard import DeviceWriteGuard
from iopenpod.device.write_readiness import (
    inspect_device_write_readiness,
    revalidate_device_write_readiness,
    volume_lock_key,
)
from iopenpod.itunesdb_shared.constants import (
    MEDIA_TYPE_AUDIOBOOK,
    MEDIA_TYPE_MUSIC_VIDEO,
    MEDIA_TYPE_PODCAST,
    MEDIA_TYPE_TV_SHOW,
    MEDIA_TYPE_VIDEO,
)
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo

from . import _db_io, itunes_prefs

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DatabaseCommitPayload:
    """Resolved payload for one iPod database rewrite."""

    all_tracks: list[TrackInfo]
    pc_file_paths: Mapping[int, str] | None = None
    playlists: list[PlaylistInfo] = field(default_factory=list)
    podcast_playlists: list[PlaylistInfo] = field(default_factory=list)
    smart_playlists: list[PlaylistInfo] = field(default_factory=list)
    master_playlist_name: str = "iPod"
    master_playlist_id: int | None = None
    podcast_master_playlist_name: str | None = None
    podcast_master_playlist_id: int | None = None


def write_database_commit(
    ipod_path: str | Path,
    payload: DatabaseCommitPayload,
    *,
    progress_callback: Callable[[str], None] | None = None,
    raise_on_error: bool = False,
    protect_itunes: bool = False,
    include_photo_totals: bool = False,
    photo_db: Any | None = None,
    flush_after_write: bool = True,
    write_guard: Any | None = None,
    filesystem_profile: FilesystemProfile | None = None,
) -> bool:
    """Write one resolved iPod database payload and optional iTunesPrefs protection."""

    if filesystem_profile is None:
        filesystem_profile = inspect_device_write_readiness(ipod_path)
    assert filesystem_profile is not None

    if write_guard is None:
        with DeviceWriteGuard(
            ipod_path,
            volume_key=volume_lock_key(filesystem_profile),
        ) as owned_guard:
            return write_database_commit(
                ipod_path,
                payload,
                progress_callback=progress_callback,
                raise_on_error=raise_on_error,
                protect_itunes=protect_itunes,
                include_photo_totals=include_photo_totals,
                photo_db=photo_db,
                flush_after_write=flush_after_write,
                write_guard=owned_guard,
                filesystem_profile=filesystem_profile,
            )

    filesystem_profile = revalidate_device_write_readiness(
        filesystem_profile,
        probe_case_sensitivity=filesystem_profile.case_sensitive is None,
    )
    write_guard.assert_database_unchanged()

    def _before_device_mutation() -> None:
        nonlocal filesystem_profile
        assert filesystem_profile is not None
        filesystem_profile = revalidate_device_write_readiness(
            filesystem_profile
        )

    db_ok = _db_io.write_database(
        Path(ipod_path),
        payload.all_tracks,
        pc_file_paths=dict(payload.pc_file_paths) if payload.pc_file_paths else None,
        playlists=payload.playlists,
        podcast_playlists=payload.podcast_playlists,
        smart_playlists=payload.smart_playlists,
        master_playlist_name=payload.master_playlist_name,
        master_playlist_id=payload.master_playlist_id,
        podcast_master_playlist_name=payload.podcast_master_playlist_name,
        podcast_master_playlist_id=payload.podcast_master_playlist_id,
        progress_callback=progress_callback,
        raise_on_error=raise_on_error,
        case_sensitive_paths=getattr(
            filesystem_profile,
            "case_sensitive",
            None,
        ),
        before_database_replace=write_guard.assert_database_unchanged,
        before_device_mutation=_before_device_mutation,
    )
    if not db_ok:
        return False
    write_guard.refresh_database_generation()

    if protect_itunes:
        filesystem_profile = revalidate_device_write_readiness(
            filesystem_profile
        )
        apply_itunes_protections_from_tracks(
            ipod_path,
            payload.all_tracks,
            photo_db=photo_db,
            include_photo_totals=include_photo_totals,
            before_device_mutation=_before_device_mutation,
        )

    if flush_after_write:
        try:
            filesystem_profile = revalidate_device_write_readiness(
                filesystem_profile
            )
            flush_ok, flush_message = flush_filesystem(ipod_path)
        except Exception as exc:
            flush_ok = False
            flush_message = f"filesystem flush failed: {exc}"
        if not flush_ok:
            logger.error(
                "Database commit durability barrier failed: mount=%s result=%s",
                ipod_path,
                flush_message,
            )
            if raise_on_error:
                raise RuntimeError(flush_message)
            return False
        logger.info(
            "Database commit durability barrier completed: mount=%s result=%s",
            ipod_path,
            flush_message,
        )
    return True


def apply_itunes_protections_from_tracks(
    ipod_path: str | Path,
    all_tracks: list[TrackInfo],
    *,
    photo_db: Any | None = None,
    include_photo_totals: bool = False,
    before_device_mutation: Callable[[], None] | None = None,
) -> None:
    """Update iTunesPrefs protection from the committed track/photo totals."""

    totals = _media_totals(all_tracks)
    total_photos = 0
    total_photo_bytes = 0
    supports_photos = False
    supports_videos = True
    if include_photo_totals:
        if photo_db is not None:
            total_photos = len(getattr(photo_db, "photos", {}) or {})
            total_photo_bytes = sum(
                int(value or 0)
                for value in (getattr(photo_db, "file_sizes", {}) or {}).values()
            )
        supports_photos, supports_videos = _current_device_supports(ipod_path)
        supports_photos = supports_photos or total_photos > 0

    itunes_prefs.protect_from_itunes(
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
        total_photos=total_photos,
        total_photo_bytes=total_photo_bytes,
        supports_photos=supports_photos,
        supports_videos=supports_videos,
        before_device_mutation=before_device_mutation,
    )


def _media_totals(all_tracks: list[TrackInfo]) -> dict[str, list[int]]:
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
    return totals


def _current_device_supports(ipod_path: str | Path) -> tuple[bool, bool]:
    try:
        from iopenpod.device import get_current_device_for_path

        device = get_current_device_for_path(ipod_path)
        capabilities = device.capabilities if device else None
        return (
            bool(capabilities and capabilities.supports_photo),
            bool(capabilities and capabilities.supports_video),
        )
    except Exception:
        return (False, True)
