"""Materialize iTunesDB metadata in on-device media files for Rockbox.

The stock iPod firmware reads metadata from iTunesDB, while Rockbox reads the
media files.  This module keeps that compatibility pass behind one boundary:
it resolves guarded iPod paths, writes the native tag structure for each
supported container, embeds a Rockbox-compatible baseline JPEG, and updates
``TrackInfo.size`` so the subsequent iTunesDB commit remains accurate.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any

from PIL import Image, ImageOps

from iopenpod.artworkdb_writer.art_extractor import extract_art_with_folder
from iopenpod.artworkdb_writer.artworkdb_chunks import read_existing_artwork
from iopenpod.artworkdb_writer.ithmb_codecs import decode_pixels_for_format
from iopenpod.device.durability import flush_written_file
from iopenpod.device.write_guard import DeviceWriteSafetyError
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo

from .ipod_track_paths import CachedIpodMusicPathResolver, expected_ipod_track_file_path

logger = logging.getLogger(__name__)

_ID3_EXTENSIONS = frozenset({".mp3", ".aac"})
_MP4_EXTENSIONS = frozenset({".m4a", ".m4b", ".m4p", ".m4v", ".mp4", ".mov"})
_ROCKBOX_ART_MAX_DIMENSION = 500
_ROCKBOX_ART_QUALITY = 88
_ESTIMATED_TAG_OVERHEAD = 64 * 1024
_DATABASE_WRITE_RESERVE = 1024 * 1024
_NORMALIZED_ART_CACHE_SIZE = 64
_ARTWORK_PREFETCH_MAX_WORKERS = 4
_ARTWORK_PREFETCH_AHEAD_PER_WORKER = 2


class UnsupportedRockboxTagFormat(ValueError):
    """Raised when a device media file has no supported writable tag format."""


class RockboxMetadataWriteError(RuntimeError):
    """Raised when a media file cannot safely receive its Rockbox tags."""


@dataclass(frozen=True, slots=True)
class RockboxArtwork:
    """Raw artwork input before Rockbox compatibility normalization."""

    data: bytes
    mime: str = "image/jpeg"
    normalized: bool = False


@dataclass(frozen=True, slots=True)
class RockboxTrackWriteResult:
    """Outcome of writing one file's tags."""

    file_size: int
    bytes_delta: int
    written: bool = True


@dataclass(frozen=True, slots=True)
class RockboxMetadataFailure:
    """One track that the library-wide pass could not update."""

    location: str
    message: str


@dataclass(frozen=True, slots=True)
class RockboxArtworkDatabaseState:
    """Cheap invalidation state for the device artwork database."""

    exists: bool
    file_size: int = 0
    mtime_ns: int = 0


@dataclass(frozen=True, slots=True)
class RockboxMetadataValidationMarker:
    """Persisted proof that one media file passed Rockbox tag validation."""

    db_track_id: int
    file_size: int
    mtime_ns: int
    metadata_signature: str


@dataclass(frozen=True, slots=True)
class RockboxMetadataPassResult:
    """Aggregate result from a complete iPod library pass."""

    updated: int = 0
    unsupported: int = 0
    bytes_delta: int = 0
    failures: tuple[RockboxMetadataFailure, ...] = ()
    cancelled: bool = False
    validated_from_marker: int = 0
    validation_markers: Mapping[int, RockboxMetadataValidationMarker] = field(default_factory=dict)
    validation_artwork_state: RockboxArtworkDatabaseState | None = None


ProgressCallback = Callable[[int, int, str], None]


def write_rockbox_track_metadata(
    file_path: str | Path,
    track: TrackInfo,
    *,
    artwork: RockboxArtwork | None = None,
    max_file_size_bytes: int | None = None,
    flush_after_write: bool = True,
    force_write: bool = False,
    preserve_embedded_artwork: bool = False,
) -> RockboxTrackWriteResult:
    """Write final iTunesDB values to one media file using its native tags.

    Set ``flush_after_write`` to ``False`` only when the caller establishes a
    filesystem-wide durability barrier after the complete batch.
    """

    path = Path(file_path)
    suffix = path.suffix.casefold()
    if suffix not in _ID3_EXTENSIONS and suffix not in _MP4_EXTENSIONS:
        raise UnsupportedRockboxTagFormat(f"Rockbox metadata writing is not supported for {suffix or 'this file type'}")

    before_size = path.stat().st_size
    normalized_artwork = None if preserve_embedded_artwork else _normalize_rockbox_artwork(artwork)
    if not force_write and _rockbox_metadata_is_current(path, track, normalized_artwork):
        return RockboxTrackWriteResult(
            file_size=before_size,
            bytes_delta=0,
            written=False,
        )

    estimated_growth = _ESTIMATED_TAG_OVERHEAD + (len(normalized_artwork.data) if normalized_artwork else 0)
    if max_file_size_bytes is not None and before_size + estimated_growth > max_file_size_bytes:
        raise RockboxMetadataWriteError(f"Adding Rockbox metadata could exceed this filesystem's {max_file_size_bytes:,}-byte file-size limit")

    if suffix in _ID3_EXTENSIONS:
        _write_id3_metadata(
            path,
            track,
            normalized_artwork,
            preserve_embedded_artwork=preserve_embedded_artwork,
        )
    else:
        _write_mp4_metadata(
            path,
            track,
            normalized_artwork,
            preserve_embedded_artwork=preserve_embedded_artwork,
        )

    after_size = path.stat().st_size
    if max_file_size_bytes is not None and after_size > max_file_size_bytes:
        raise RockboxMetadataWriteError(f"Tagged file exceeds this filesystem's {max_file_size_bytes:,}-byte file-size limit")

    if flush_after_write:
        with path.open("rb+") as media_file:
            flush_written_file(media_file)

    return RockboxTrackWriteResult(
        file_size=after_size,
        bytes_delta=after_size - before_size,
    )


def write_rockbox_metadata_library(
    ipod_root: str | Path,
    tracks: Sequence[TrackInfo],
    *,
    pc_file_paths: Mapping[int, str] | None = None,
    progress_callback: ProgressCallback | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    before_device_mutation: Callable[[], None] | None = None,
    max_file_size_bytes: int | None = None,
    device_artwork_formats: Mapping[int, Any] | None = None,
    defer_durability: bool = False,
    revalidate_interval_seconds: float | None = None,
    validation_markers: Mapping[int, RockboxMetadataValidationMarker] | None = None,
    validation_artwork_state: RockboxArtworkDatabaseState | None = None,
    force_write_track_ids: set[int] | None = None,
    preserve_embedded_artwork_track_ids: set[int] | None = None,
) -> RockboxMetadataPassResult:
    """Write tags for every track in the final library.

    Paths are accepted only when they resolve beneath ``iPod_Control/Music``.
    Artwork follows the same final-state policy as the ArtworkDB writer:
    unchanged tracks use current device artwork, changed/new tracks use their
    PC source, and an explicit clear removes embedded art.

    When ``defer_durability`` is true, the caller must establish a
    filesystem-wide durability barrier after the full library write. A
    revalidation interval may be supplied by that caller to avoid repeating
    an expensive device-readiness check for every track in a large library.

    Callers may pass validation markers created by a prior successful pass.
    If the file, its expected database metadata, and ArtworkDB state are all
    unchanged, the pass safely avoids opening the media tag or ArtworkDB.

    ``force_write_track_ids`` contains tracks the sync plan already knows have
    changed, so they skip the redundant read-before-write tag comparison.
    """

    if revalidate_interval_seconds is not None and revalidate_interval_seconds <= 0:
        raise ValueError("revalidate_interval_seconds must be positive")

    root = Path(ipod_root)
    source_paths = {int(db_track_id): str(path) for db_track_id, path in (pc_file_paths or {}).items() if path}
    current_artwork_state = rockbox_artwork_database_state(root)
    known_markers = {int(db_track_id): marker for db_track_id, marker in (validation_markers or {}).items()}
    forced_track_ids = {int(db_track_id) for db_track_id in (force_write_track_ids or set())}
    preserve_embedded_artwork_ids = {
        int(db_track_id)
        for db_track_id in (preserve_embedded_artwork_track_ids or set())
    }
    can_use_validation_markers = validation_artwork_state is not None and validation_artwork_state == current_artwork_state
    cached_path_resolver = CachedIpodMusicPathResolver(root)
    artwork_resolver = _ArtworkResolver(
        root,
        source_paths,
        device_artwork_formats=device_artwork_formats or {},
    )
    artwork_resolver.prefetch_source_artwork(tracks)

    failures: list[RockboxMetadataFailure] = []
    markers: list[RockboxMetadataValidationMarker] = []
    updated = 0
    unsupported = 0
    bytes_delta = 0
    validated_from_marker = 0
    total = len(tracks)
    cancelled = False
    last_revalidation_at: float | None = None
    available_free_bytes: int | None = None

    for index, track in enumerate(tracks):
        if is_cancelled is not None and is_cancelled():
            cancelled = True
            break

        location = str(track.location or "")
        try:
            db_track_id = int(track.db_track_id or 0)
        except (TypeError, ValueError):
            db_track_id = 0
        marker = known_markers.get(db_track_id)
        cached_file = cached_path_resolver.existing_regular_file(location)
        if cached_file is not None:
            path, file_stat = cached_file
            if (
                db_track_id not in forced_track_ids
                and can_use_validation_markers
                and marker is not None
                and _validation_marker_matches(marker, path, track, file_stat)
            ):
                track.size = file_stat.st_size
                track.last_modified = int(file_stat.st_mtime)
                markers.append(_validation_marker(track, path, file_stat))
                validated_from_marker += 1
                _emit_progress(progress_callback, index + 1, total, path.name)
                continue
        else:
            path = expected_ipod_track_file_path(root, location)
            if path is None:
                failures.append(
                    RockboxMetadataFailure(
                        location,
                        "Unsafe iPod media path; the file was not modified",
                    )
                )
                _emit_progress(progress_callback, index + 1, total, location)
                continue
            if not path.is_file():
                failures.append(RockboxMetadataFailure(location, "Referenced media file is missing"))
                _emit_progress(progress_callback, index + 1, total, path.name)
                continue
            file_stat = path.stat()

        try:
            preserve_embedded_artwork = (
                db_track_id in preserve_embedded_artwork_ids
                and can_use_validation_markers
                and marker is not None
                and _validation_marker_file_matches(marker, track, file_stat)
            )
            artwork = None if preserve_embedded_artwork else artwork_resolver.for_track(track)
            required_growth = _ESTIMATED_TAG_OVERHEAD + (len(artwork.data) if artwork else 0)
            if available_free_bytes is None:
                available_free_bytes = shutil.disk_usage(root).free
            if available_free_bytes < required_growth + _DATABASE_WRITE_RESERVE:
                raise RockboxMetadataWriteError("Not enough free space to add tags while preserving the database-write reserve")
            should_revalidate = (
                revalidate_interval_seconds is None
                or last_revalidation_at is None
                or monotonic() - last_revalidation_at >= revalidate_interval_seconds
            )
            if before_device_mutation is not None and should_revalidate:
                before_device_mutation()
                last_revalidation_at = monotonic()
            write_result = write_rockbox_track_metadata(
                path,
                track,
                artwork=artwork,
                max_file_size_bytes=max_file_size_bytes,
                flush_after_write=not defer_durability,
                force_write=db_track_id in forced_track_ids,
                preserve_embedded_artwork=preserve_embedded_artwork,
            )
            final_stat = path.stat()
            track.size = final_stat.st_size
            track.last_modified = int(final_stat.st_mtime)
            if db_track_id:
                markers.append(_validation_marker(track, path, final_stat))
            available_free_bytes -= max(write_result.bytes_delta, 0)
            updated += int(write_result.written)
            bytes_delta += write_result.bytes_delta
        except DeviceWriteSafetyError:
            # A disconnected or replaced device is a sync-wide safety failure,
            # not an individual bad media file.
            artwork_resolver.close()
            raise
        except UnsupportedRockboxTagFormat as exc:
            unsupported += 1
            failures.append(RockboxMetadataFailure(location, str(exc)))
        except Exception as exc:
            if available_free_bytes is not None:
                try:
                    available_free_bytes = shutil.disk_usage(root).free
                except OSError:
                    pass
            logger.warning(
                "Could not write Rockbox metadata to %s: %s",
                path,
                exc,
            )
            failures.append(RockboxMetadataFailure(location, str(exc)))

        _emit_progress(progress_callback, index + 1, total, path.name)

    artwork_resolver.close()
    return RockboxMetadataPassResult(
        updated=updated,
        unsupported=unsupported,
        bytes_delta=bytes_delta,
        failures=tuple(failures),
        cancelled=cancelled,
        validated_from_marker=validated_from_marker,
        validation_markers={marker.db_track_id: marker for marker in markers},
        validation_artwork_state=current_artwork_state,
    )


def rockbox_artwork_database_state(ipod_root: str | Path) -> RockboxArtworkDatabaseState | None:
    """Return a cheap state token for invalidating cached ArtworkDB validation."""

    root = Path(ipod_root)
    artwork_db = root / "iPod_Control" / "Artwork" / "ArtworkDB"
    try:
        file_stat = artwork_db.stat()
    except FileNotFoundError:
        return RockboxArtworkDatabaseState(exists=False)
    except OSError:
        return None
    return RockboxArtworkDatabaseState(
        exists=True,
        file_size=file_stat.st_size,
        mtime_ns=file_stat.st_mtime_ns,
    )


def _validation_marker(
    track: TrackInfo,
    path: Path,
    file_stat: Any,
) -> RockboxMetadataValidationMarker:
    return RockboxMetadataValidationMarker(
        db_track_id=int(track.db_track_id),
        file_size=file_stat.st_size,
        mtime_ns=file_stat.st_mtime_ns,
        metadata_signature=_metadata_signature(path, track),
    )


def _validation_marker_matches(
    marker: RockboxMetadataValidationMarker,
    path: Path,
    track: TrackInfo,
    file_stat: Any,
) -> bool:
    return (
        _validation_marker_file_matches(marker, track, file_stat)
        and marker.metadata_signature == _metadata_signature(path, track)
    )


def _validation_marker_file_matches(
    marker: RockboxMetadataValidationMarker,
    track: TrackInfo,
    file_stat: Any,
) -> bool:
    return (
        marker.db_track_id == int(track.db_track_id or 0)
        and marker.file_size == file_stat.st_size
        and marker.mtime_ns == file_stat.st_mtime_ns
    )


def _metadata_signature(path: Path, track: TrackInfo) -> str:
    """Hash the database fields this module materializes in one media tag."""

    suffix = path.suffix.casefold()
    if suffix in _ID3_EXTENSIONS:
        values: dict[str, Any] = {
            "container": "id3v2.3",
            "location": str(track.location or ""),
            "text": _id3_persisted_text_values(track),
            "comment": _text(track.comment),
            "lyrics": _text(track.lyrics),
        }
    else:
        values = {
            "container": "mp4",
            "location": str(track.location or ""),
            "text": _mp4_text_values(track),
            "track": _mp4_tuple_value(track.track_number, track.total_tracks),
            "disc": _mp4_tuple_value(track.disc_number, track.total_discs),
            "bpm": _mp4_integer_value(track.bpm),
            "season": _mp4_integer_value(track.season_number),
            "episode": _mp4_integer_value(track.episode_number),
            "compilation": bool(track.compilation_flag),
            "explicit": int(track.explicit_flag or 0),
        }
    serialized = json.dumps(values, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _write_id3_metadata(
    path: Path,
    track: TrackInfo,
    artwork: RockboxArtwork | None,
    *,
    preserve_embedded_artwork: bool = False,
) -> None:
    from mutagen.id3 import ID3
    from mutagen.id3._frames import APIC, COMM, TALB, TBPM, TCMP, TCOM, TCON, TDRC, TIT1, TIT2, TPE1, TPE2, TPOS, TRCK, TSO2, TSOA, TSOC, TSOP, TSOT, USLT
    from mutagen.id3._specs import PictureType
    from mutagen.id3._util import ID3NoHeaderError

    try:
        tags = ID3(path, v2_version=3)
    except ID3NoHeaderError:
        tags = ID3()

    text_frame_types = {
        "TIT2": TIT2,
        "TPE1": TPE1,
        "TALB": TALB,
        "TPE2": TPE2,
        "TCON": TCON,
        "TCOM": TCOM,
        "TIT1": TIT1,
        "TDRC": TDRC,
        "TRCK": TRCK,
        "TPOS": TPOS,
        "TBPM": TBPM,
        "TCMP": TCMP,
        "TSOT": TSOT,
        "TSOP": TSOP,
        "TSOA": TSOA,
        "TSO2": TSO2,
        "TSOC": TSOC,
    }
    for frame_id, value in _id3_text_values(track):
        tags.delall(frame_id)
        if value:
            tags.add(text_frame_types[frame_id](encoding=3, text=[value]))

    tags.delall("COMM")
    if comment := _text(track.comment):
        tags.add(COMM(encoding=3, lang="eng", desc="", text=[comment]))

    tags.delall("USLT")
    if lyrics := _text(track.lyrics):
        tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))

    if not preserve_embedded_artwork:
        tags.delall("APIC")
        if artwork is not None:
            tags.add(
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=PictureType.COVER_FRONT,
                    desc="Cover",
                    data=artwork.data,
                )
            )

    # ID3v2.3 is widely understood by Rockbox-era tooling. Mutagen converts
    # UTF-8 text to valid UTF-16 and joins multi-values for this version.
    tags.update_to_v23()
    tags.save(path, v1=0, v2_version=3)


def _write_mp4_metadata(
    path: Path,
    track: TrackInfo,
    artwork: RockboxArtwork | None,
    *,
    preserve_embedded_artwork: bool = False,
) -> None:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(path)
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    if tags is None:
        raise RockboxMetadataWriteError("Could not create MP4 metadata atoms")

    for atom, value in _mp4_text_values(track).items():
        if value:
            tags[atom] = [value]
        else:
            tags.pop(atom, None)

    _set_mp4_tuple(tags, "trkn", track.track_number, track.total_tracks)
    _set_mp4_tuple(tags, "disk", track.disc_number, track.total_discs)
    _set_mp4_integer(tags, "tmpo", track.bpm)
    _set_mp4_integer(tags, "tvsn", track.season_number)
    _set_mp4_integer(tags, "tves", track.episode_number)
    if track.compilation_flag:
        tags["cpil"] = True
    else:
        tags.pop("cpil", None)
    if track.explicit_flag:
        tags["rtng"] = [int(track.explicit_flag)]
    else:
        tags.pop("rtng", None)

    if not preserve_embedded_artwork:
        if artwork is None:
            tags.pop("covr", None)
        else:
            tags["covr"] = [MP4Cover(artwork.data, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def _rockbox_metadata_is_current(
    path: Path,
    track: TrackInfo,
    artwork: RockboxArtwork | None,
) -> bool:
    """Return whether the managed Rockbox tags already match ``track``."""

    if path.suffix.casefold() in _ID3_EXTENSIONS:
        return _id3_metadata_is_current(path, track, artwork)
    return _mp4_metadata_is_current(path, track, artwork)


def _id3_metadata_is_current(
    path: Path,
    track: TrackInfo,
    artwork: RockboxArtwork | None,
) -> bool:
    from mutagen.id3 import ID3
    from mutagen.id3._specs import PictureType
    from mutagen.id3._util import ID3NoHeaderError

    try:
        tags = ID3(path, v2_version=3)
    except ID3NoHeaderError:
        return False

    # A v2.4 tag can contain equivalent text but still needs the compatibility
    # rewrite: Rockbox-era tools are more reliable with v2.3.
    if tags.version[:2] != (2, 3):
        return False

    for frame_id, expected in _id3_persisted_text_values(track):
        # Mutagen serializes the writer's TDRC year as the v2.3 TYER frame.
        stored_frame_id = "TYER" if frame_id == "TDRC" else frame_id
        if not _id3_text_matches(tags, stored_frame_id, expected):
            return False
    if not _id3_text_matches(tags, "COMM", _text(track.comment)):
        return False
    if not _id3_text_matches(tags, "USLT", _text(track.lyrics)):
        return False

    covers = tags.getall("APIC")
    if artwork is None:
        return not covers
    if len(covers) != 1:
        return False
    cover = covers[0]
    return (
        cover.mime == "image/jpeg"
        and cover.type == PictureType.COVER_FRONT
        and cover.desc == "Cover"
        and cover.data == artwork.data
    )


def _id3_text_matches(tags: Any, frame_id: str, expected: str) -> bool:
    frames = tags.getall(frame_id)
    if not expected:
        return not frames
    return len(frames) == 1 and str(frames[0]) == expected


def _mp4_metadata_is_current(
    path: Path,
    track: TrackInfo,
    artwork: RockboxArtwork | None,
) -> bool:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(path)
    tags = audio.tags
    if tags is None:
        return False

    for atom, value in _mp4_text_values(track).items():
        if not _mp4_value_matches(tags, atom, [value] if value else None):
            return False
    if not _mp4_value_matches(tags, "trkn", _mp4_tuple_value(track.track_number, track.total_tracks)):
        return False
    if not _mp4_value_matches(tags, "disk", _mp4_tuple_value(track.disc_number, track.total_discs)):
        return False
    if not _mp4_value_matches(tags, "tmpo", _mp4_integer_value(track.bpm)):
        return False
    if not _mp4_value_matches(tags, "tvsn", _mp4_integer_value(track.season_number)):
        return False
    if not _mp4_value_matches(tags, "tves", _mp4_integer_value(track.episode_number)):
        return False
    if not _mp4_value_matches(tags, "cpil", True if track.compilation_flag else None):
        return False
    if not _mp4_value_matches(tags, "rtng", [int(track.explicit_flag)] if track.explicit_flag else None):
        return False

    covers = tags.get("covr")
    if artwork is None:
        return not covers
    if not isinstance(covers, list) or len(covers) != 1:
        return False
    cover = covers[0]
    return (
        isinstance(cover, MP4Cover)
        and bytes(cover) == artwork.data
        and cover.imageformat == MP4Cover.FORMAT_JPEG
    )


def _mp4_value_matches(tags: Any, atom: str, expected: Any | None) -> bool:
    if expected is None:
        return atom not in tags
    return tags.get(atom) == expected


def _id3_text_values(track: TrackInfo) -> tuple[tuple[str, str], ...]:
    return (
        ("TIT2", _text(track.title)),
        ("TPE1", _text(track.artist)),
        ("TALB", _text(track.album)),
        ("TPE2", _text(track.album_artist)),
        ("TCON", _text(track.genre)),
        ("TCOM", _text(track.composer)),
        ("TIT1", _text(track.grouping)),
        ("TDRC", str(track.year) if track.year else ""),
        ("TRCK", _number_with_total(track.track_number, track.total_tracks)),
        ("TPOS", _number_with_total(track.disc_number, track.total_discs)),
        ("TBPM", str(track.bpm) if track.bpm else ""),
        ("TCMP", "1" if track.compilation_flag else ""),
        ("TSOT", _text(track.sort_name)),
        ("TSOP", _text(track.sort_artist)),
        ("TSOA", _text(track.sort_album)),
        ("TSO2", _text(track.sort_album_artist)),
        ("TSOC", _text(track.sort_composer)),
    )


def _id3_persisted_text_values(track: TrackInfo) -> tuple[tuple[str, str], ...]:
    """Return ID3v2.3 fields that survive Mutagen's compatibility conversion."""

    return _id3_text_values(track)[:12]


def _mp4_text_values(track: TrackInfo) -> dict[str, str]:
    return {
        "\xa9nam": _text(track.title),
        "\xa9ART": _text(track.artist),
        "\xa9alb": _text(track.album),
        "aART": _text(track.album_artist),
        "\xa9gen": _text(track.genre),
        "\xa9wrt": _text(track.composer),
        "\xa9cmt": _text(track.comment),
        "\xa9grp": _text(track.grouping),
        "\xa9day": str(track.year) if track.year else "",
        "\xa9lyr": _text(track.lyrics),
        "sonm": _text(track.sort_name),
        "soar": _text(track.sort_artist),
        "soal": _text(track.sort_album),
        "soaa": _text(track.sort_album_artist),
        "soco": _text(track.sort_composer),
        "desc": _text(track.description),
        "tvsh": _text(track.show_name),
        "tven": _text(track.episode_id),
        "tvnn": _text(track.network_name),
        "catg": _text(track.category),
        "purl": _text(track.podcast_rss_url),
    }


def _set_mp4_tuple(tags: Any, atom: str, number: int, total: int) -> None:
    value = _mp4_tuple_value(number, total)
    if value is None:
        tags.pop(atom, None)
    else:
        tags[atom] = value


def _set_mp4_integer(tags: Any, atom: str, value: int) -> None:
    normalized = _mp4_integer_value(value)
    if normalized is None:
        tags.pop(atom, None)
    else:
        tags[atom] = normalized


def _mp4_tuple_value(number: int, total: int) -> list[tuple[int, int]] | None:
    if not number and not total:
        return None
    return [(max(0, int(number or 0)), max(0, int(total or 0)))]


def _mp4_integer_value(value: int) -> list[int] | None:
    if not value:
        return None
    return [max(0, int(value))]


def _number_with_total(number: int, total: int) -> str:
    number_value = max(0, int(number or 0))
    total_value = max(0, int(total or 0))
    if not number_value and not total_value:
        return ""
    if total_value:
        return f"{number_value}/{total_value}"
    return str(number_value)


def _text(value: object | None) -> str:
    return str(value or "").strip()


def _normalize_rockbox_artwork(
    artwork: RockboxArtwork | None,
) -> RockboxArtwork | None:
    if artwork is None or not artwork.data:
        return None
    if artwork.normalized:
        return artwork
    try:
        with Image.open(io.BytesIO(artwork.data)) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            image.thumbnail(
                (_ROCKBOX_ART_MAX_DIMENSION, _ROCKBOX_ART_MAX_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            if image.mode != "RGB":
                if "A" in image.getbands():
                    background = Image.new("RGB", image.size, "white")
                    alpha = image.getchannel("A")
                    background.paste(image.convert("RGB"), mask=alpha)
                    image = background
                else:
                    image = image.convert("RGB")
            output = io.BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=_ROCKBOX_ART_QUALITY,
                optimize=False,
                progressive=False,
                subsampling=2,
            )
    except Exception as exc:
        raise RockboxMetadataWriteError(f"Artwork could not be converted to a Rockbox-compatible JPEG: {exc}") from exc
    return RockboxArtwork(output.getvalue(), "image/jpeg", normalized=True)


def _extract_and_normalize_source_artwork(source_path: str) -> RockboxArtwork | None:
    """Extract and normalize one PC cover without sharing resolver state."""

    art_bytes = extract_art_with_folder(source_path)
    if not art_bytes:
        return None
    return _normalize_rockbox_artwork(RockboxArtwork(art_bytes, "application/octet-stream"))


def _emit_progress(
    callback: ProgressCallback | None,
    current: int,
    total: int,
    label: str,
) -> None:
    if callback is not None:
        callback(current, total, label)


class _ArtworkResolver:
    """Resolve the final artwork policy without importing GUI image helpers."""

    def __init__(
        self,
        ipod_root: Path,
        pc_file_paths: Mapping[int, str],
        *,
        device_artwork_formats: Mapping[int, Any],
    ) -> None:
        self._pc_file_paths = pc_file_paths
        self._device_artwork_formats = device_artwork_formats
        self._source_cache: dict[str, RockboxArtwork | None] = {}
        self._normalized_cache: OrderedDict[bytes, RockboxArtwork] = OrderedDict()
        self._existing_ref_digests: dict[tuple[str, int, int, int, int, int, int, int], bytes] = {}
        self._ipod_root = ipod_root
        self._existing_art: dict[int, dict] | None = None
        self._existing_by_song_id: dict[int, dict] | None = None
        self._source_executor: ThreadPoolExecutor | None = None
        self._source_futures: dict[str, Future[RockboxArtwork | None]] = {}
        self._source_prefetch_queue: deque[tuple[str, str]] = deque()
        self._source_prefetch_limit = 0

    @staticmethod
    def _read_existing_art(ipod_root: Path) -> dict[int, dict]:
        artwork_dir = ipod_root / "iPod_Control" / "Artwork"
        artworkdb_path = artwork_dir / "ArtworkDB"
        try:
            return read_existing_artwork(
                str(artworkdb_path),
                str(artwork_dir),
            )
        except Exception as exc:
            logger.warning(
                "Could not load existing artwork for Rockbox metadata fallback: %s",
                exc,
            )
            return {}

    def for_track(self, track: TrackInfo) -> RockboxArtwork | None:
        hint = str(getattr(track, "_iop_artwork_sync_hint", "") or "")
        if hint == "clear_art":
            return None
        if hint == "preserve_existing":
            return self._from_existing(track)

        source_path = self._pc_file_paths.get(int(track.db_track_id or 0))
        if source_path:
            source_art = self._from_source(source_path)
            if source_art is not None:
                return source_art
            # This mirrors the ArtworkDB writer: a present PC source with no
            # usable art means the final artwork state is clear.
            return None
        return self._from_existing(track)

    def prefetch_source_artwork(self, tracks: Sequence[TrackInfo]) -> None:
        """Begin bounded host-side cover extraction before device tag writes."""

        if self._source_executor is not None:
            return
        source_paths: list[tuple[str, str]] = []
        seen_keys: set[str] = set()
        for track in tracks:
            hint = str(getattr(track, "_iop_artwork_sync_hint", "") or "")
            if hint in {"clear_art", "preserve_existing"}:
                continue
            source_path = self._pc_file_paths.get(int(track.db_track_id or 0))
            if not source_path:
                continue
            key = self._source_cache_key(source_path)
            if key in seen_keys or key in self._source_cache:
                continue
            seen_keys.add(key)
            source_paths.append((key, source_path))
        if len(source_paths) < 2:
            return

        workers = min(_ARTWORK_PREFETCH_MAX_WORKERS, len(source_paths))
        self._source_executor = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="rockbox-art",
        )
        self._source_prefetch_limit = workers * _ARTWORK_PREFETCH_AHEAD_PER_WORKER
        self._source_prefetch_queue.extend(source_paths)
        self._fill_source_prefetch_queue()

    def close(self) -> None:
        """Stop source-art workers after the metadata batch is complete."""

        if self._source_executor is not None:
            self._source_executor.shutdown(cancel_futures=True)
            self._source_executor = None
        self._source_futures.clear()
        self._source_prefetch_queue.clear()
        self._source_prefetch_limit = 0

    def _from_source(self, source_path: str) -> RockboxArtwork | None:
        key = self._source_cache_key(source_path)
        if key not in self._source_cache:
            future = self._source_futures.pop(key, None)
            if future is not None:
                artwork = future.result()
            else:
                self._discard_queued_source(key)
                artwork = _extract_and_normalize_source_artwork(source_path)
            self._source_cache[key] = self._remember_prefetched_artwork(artwork)
            self._fill_source_prefetch_queue()
        return self._source_cache[key]

    @staticmethod
    def _source_cache_key(source_path: str) -> str:
        return os.path.normcase(os.path.abspath(source_path))

    def _fill_source_prefetch_queue(self) -> None:
        if self._source_executor is None:
            return
        while (
            self._source_prefetch_queue
            and len(self._source_futures) < self._source_prefetch_limit
        ):
            key, source_path = self._source_prefetch_queue.popleft()
            self._source_futures[key] = self._source_executor.submit(
                _extract_and_normalize_source_artwork,
                source_path,
            )

    def _discard_queued_source(self, key: str) -> None:
        if not self._source_prefetch_queue:
            return
        self._source_prefetch_queue = deque(
            queued for queued in self._source_prefetch_queue if queued[0] != key
        )

    def _remember_prefetched_artwork(
        self,
        artwork: RockboxArtwork | None,
    ) -> RockboxArtwork | None:
        if artwork is None:
            return None
        digest = hashlib.sha256(artwork.data).digest()
        cached = self._normalized_cache.get(digest)
        if cached is not None:
            self._normalized_cache.move_to_end(digest)
            return cached
        self._remember_normalized(digest, artwork)
        return artwork

    def _from_existing(self, track: TrackInfo) -> RockboxArtwork | None:
        self._ensure_existing_artwork_loaded()
        assert self._existing_art is not None
        assert self._existing_by_song_id is not None
        entry = self._existing_by_song_id.get(int(track.db_track_id or 0))
        if entry is None and track.mhii_link:
            entry = self._existing_art.get(int(track.mhii_link))
        if entry is None:
            return None

        formats = entry.get("formats", {})
        ranked = sorted(
            formats.items(),
            key=lambda item: (
                int(getattr(item[1], "width", 0)) * int(getattr(item[1], "height", 0)),
                int(item[0]),
            ),
            reverse=True,
        )
        for raw_format_id, ref in ranked:
            try:
                format_id = int(raw_format_id)
                ref_key = self._existing_ref_key(format_id, ref)
                known_digest = self._existing_ref_digests.get(ref_key)
                if known_digest is not None:
                    cached = self._normalized_cache.get(known_digest)
                    if cached is not None:
                        self._normalized_cache.move_to_end(known_digest)
                        return cached
                with open(ref.path, "rb") as artwork_file:
                    artwork_file.seek(int(ref.ithmb_offset))
                    pixels = artwork_file.read(int(ref.size))
                if len(pixels) != int(ref.size):
                    continue
                digest = hashlib.sha256(pixels).digest()
                self._existing_ref_digests[ref_key] = digest
                cached = self._normalized_cache.get(digest)
                if cached is not None:
                    self._normalized_cache.move_to_end(digest)
                    return cached
                image = decode_pixels_for_format(
                    format_id,
                    pixels,
                    int(ref.width),
                    int(ref.height),
                    int(ref.hpad),
                    int(ref.vpad),
                    fmt_override=self._device_artwork_formats.get(format_id),
                )
                if image is None:
                    continue
                output = io.BytesIO()
                image.convert("RGB").save(
                    output,
                    format="JPEG",
                    quality=_ROCKBOX_ART_QUALITY,
                    optimize=False,
                    progressive=False,
                    subsampling=2,
                )
                artwork = RockboxArtwork(
                    output.getvalue(),
                    "image/jpeg",
                    normalized=True,
                )
                self._remember_normalized(digest, artwork)
                return artwork
            except (OSError, TypeError, ValueError):
                continue
        return None

    def _ensure_existing_artwork_loaded(self) -> None:
        if self._existing_art is not None:
            return
        self._existing_art = self._read_existing_art(self._ipod_root)
        self._existing_by_song_id = {
            int(entry.get("song_id", 0) or 0): entry
            for entry in self._existing_art.values()
            if int(entry.get("song_id", 0) or 0)
        }

    @staticmethod
    def _existing_ref_key(format_id: int, ref: Any) -> tuple[str, int, int, int, int, int, int, int]:
        return (
            os.path.normcase(os.path.abspath(str(ref.path))),
            int(ref.ithmb_offset),
            int(ref.size),
            format_id,
            int(ref.width),
            int(ref.height),
            int(ref.hpad),
            int(ref.vpad),
        )

    def _remember_normalized(
        self,
        digest: bytes,
        artwork: RockboxArtwork,
    ) -> None:
        self._normalized_cache[digest] = artwork
        self._normalized_cache.move_to_end(digest)
        while len(self._normalized_cache) > _NORMALIZED_ART_CACHE_SIZE:
            self._normalized_cache.popitem(last=False)


__all__ = [
    "RockboxArtwork",
    "RockboxArtworkDatabaseState",
    "RockboxMetadataFailure",
    "RockboxMetadataPassResult",
    "RockboxMetadataValidationMarker",
    "RockboxMetadataWriteError",
    "RockboxTrackWriteResult",
    "UnsupportedRockboxTagFormat",
    "rockbox_artwork_database_state",
    "write_rockbox_metadata_library",
    "write_rockbox_track_metadata",
]
