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
import logging
import os
import shutil
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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

from .ipod_track_paths import expected_ipod_track_file_path

logger = logging.getLogger(__name__)

_ID3_EXTENSIONS = frozenset({".mp3", ".aac"})
_MP4_EXTENSIONS = frozenset({".m4a", ".m4b", ".m4p", ".m4v", ".mp4"})
_ROCKBOX_ART_MAX_DIMENSION = 500
_ROCKBOX_ART_QUALITY = 88
_ESTIMATED_TAG_OVERHEAD = 64 * 1024
_DATABASE_WRITE_RESERVE = 1024 * 1024
_NORMALIZED_ART_CACHE_SIZE = 64


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


@dataclass(frozen=True, slots=True)
class RockboxMetadataFailure:
    """One track that the library-wide pass could not update."""

    location: str
    message: str


@dataclass(frozen=True, slots=True)
class RockboxMetadataPassResult:
    """Aggregate result from a complete iPod library pass."""

    updated: int = 0
    unsupported: int = 0
    bytes_delta: int = 0
    failures: tuple[RockboxMetadataFailure, ...] = ()
    cancelled: bool = False


ProgressCallback = Callable[[int, int, str], None]


def write_rockbox_track_metadata(
    file_path: str | Path,
    track: TrackInfo,
    *,
    artwork: RockboxArtwork | None = None,
    max_file_size_bytes: int | None = None,
    flush_after_write: bool = True,
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
    normalized_artwork = _normalize_rockbox_artwork(artwork)
    estimated_growth = _ESTIMATED_TAG_OVERHEAD + (len(normalized_artwork.data) if normalized_artwork else 0)
    if max_file_size_bytes is not None and before_size + estimated_growth > max_file_size_bytes:
        raise RockboxMetadataWriteError(f"Adding Rockbox metadata could exceed this filesystem's {max_file_size_bytes:,}-byte file-size limit")

    if suffix in _ID3_EXTENSIONS:
        _write_id3_metadata(path, track, normalized_artwork)
    else:
        _write_mp4_metadata(path, track, normalized_artwork)

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
    """

    if revalidate_interval_seconds is not None and revalidate_interval_seconds <= 0:
        raise ValueError("revalidate_interval_seconds must be positive")

    root = Path(ipod_root)
    source_paths = {int(db_track_id): str(path) for db_track_id, path in (pc_file_paths or {}).items() if path}
    artwork_resolver = _ArtworkResolver(
        root,
        source_paths,
        device_artwork_formats=device_artwork_formats or {},
    )

    failures: list[RockboxMetadataFailure] = []
    updated = 0
    unsupported = 0
    bytes_delta = 0
    total = len(tracks)
    cancelled = False
    last_revalidation_at: float | None = None
    available_free_bytes = shutil.disk_usage(root).free

    for index, track in enumerate(tracks):
        if is_cancelled is not None and is_cancelled():
            cancelled = True
            break

        location = str(track.location or "")
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

        try:
            artwork = artwork_resolver.for_track(track)
            required_growth = _ESTIMATED_TAG_OVERHEAD + (len(artwork.data) if artwork else 0)
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
            )
            track.size = write_result.file_size
            track.last_modified = int(path.stat().st_mtime)
            available_free_bytes -= max(write_result.bytes_delta, 0)
            updated += 1
            bytes_delta += write_result.bytes_delta
        except DeviceWriteSafetyError:
            # A disconnected or replaced device is a sync-wide safety failure,
            # not an individual bad media file.
            raise
        except UnsupportedRockboxTagFormat as exc:
            unsupported += 1
            failures.append(RockboxMetadataFailure(location, str(exc)))
        except Exception as exc:
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

    return RockboxMetadataPassResult(
        updated=updated,
        unsupported=unsupported,
        bytes_delta=bytes_delta,
        failures=tuple(failures),
        cancelled=cancelled,
    )


def _write_id3_metadata(
    path: Path,
    track: TrackInfo,
    artwork: RockboxArtwork | None,
) -> None:
    from mutagen.id3 import ID3
    from mutagen.id3._frames import APIC, COMM, TALB, TBPM, TCMP, TCOM, TCON, TDRC, TIT1, TIT2, TPE1, TPE2, TPOS, TRCK, TSO2, TSOA, TSOC, TSOP, TSOT, USLT
    from mutagen.id3._specs import PictureType
    from mutagen.id3._util import ID3NoHeaderError

    try:
        tags = ID3(path, v2_version=3)
    except ID3NoHeaderError:
        tags = ID3()

    text_frames: tuple[tuple[str, type, str], ...] = (
        ("TIT2", TIT2, _text(track.title)),
        ("TPE1", TPE1, _text(track.artist)),
        ("TALB", TALB, _text(track.album)),
        ("TPE2", TPE2, _text(track.album_artist)),
        ("TCON", TCON, _text(track.genre)),
        ("TCOM", TCOM, _text(track.composer)),
        ("TIT1", TIT1, _text(track.grouping)),
        ("TDRC", TDRC, str(track.year) if track.year else ""),
        ("TRCK", TRCK, _number_with_total(track.track_number, track.total_tracks)),
        ("TPOS", TPOS, _number_with_total(track.disc_number, track.total_discs)),
        ("TBPM", TBPM, str(track.bpm) if track.bpm else ""),
        ("TCMP", TCMP, "1" if track.compilation_flag else ""),
        ("TSOT", TSOT, _text(track.sort_name)),
        ("TSOP", TSOP, _text(track.sort_artist)),
        ("TSOA", TSOA, _text(track.sort_album)),
        ("TSO2", TSO2, _text(track.sort_album_artist)),
        ("TSOC", TSOC, _text(track.sort_composer)),
    )
    for frame_id, frame_type, value in text_frames:
        tags.delall(frame_id)
        if value:
            tags.add(frame_type(encoding=3, text=[value]))

    tags.delall("COMM")
    if comment := _text(track.comment):
        tags.add(COMM(encoding=3, lang="eng", desc="", text=[comment]))

    tags.delall("USLT")
    if lyrics := _text(track.lyrics):
        tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))

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
) -> None:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(path)
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    if tags is None:
        raise RockboxMetadataWriteError("Could not create MP4 metadata atoms")

    text_atoms = {
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
    for atom, value in text_atoms.items():
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

    if artwork is None:
        tags.pop("covr", None)
    else:
        tags["covr"] = [MP4Cover(artwork.data, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def _set_mp4_tuple(tags: Any, atom: str, number: int, total: int) -> None:
    if number or total:
        tags[atom] = [(max(0, int(number or 0)), max(0, int(total or 0)))]
    else:
        tags.pop(atom, None)


def _set_mp4_integer(tags: Any, atom: str, value: int) -> None:
    if value:
        tags[atom] = [max(0, int(value))]
    else:
        tags.pop(atom, None)


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
        self._existing_art = self._read_existing_art(ipod_root)
        self._existing_by_song_id = {int(entry.get("song_id", 0) or 0): entry for entry in self._existing_art.values() if int(entry.get("song_id", 0) or 0)}

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

    def _from_source(self, source_path: str) -> RockboxArtwork | None:
        key = os.path.normcase(os.path.abspath(source_path))
        if key not in self._source_cache:
            art_bytes = extract_art_with_folder(source_path)
            self._source_cache[key] = self._normalize_cached(art_bytes) if art_bytes else None
        return self._source_cache[key]

    def _from_existing(self, track: TrackInfo) -> RockboxArtwork | None:
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
                with open(ref.path, "rb") as artwork_file:
                    artwork_file.seek(int(ref.ithmb_offset))
                    pixels = artwork_file.read(int(ref.size))
                if len(pixels) != int(ref.size):
                    continue
                format_id = int(raw_format_id)
                digest = hashlib.sha256(pixels).digest()
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

    def _normalize_cached(self, art_bytes: bytes) -> RockboxArtwork:
        digest = hashlib.sha256(art_bytes).digest()
        cached = self._normalized_cache.get(digest)
        if cached is not None:
            self._normalized_cache.move_to_end(digest)
            return cached
        normalized = _normalize_rockbox_artwork(RockboxArtwork(art_bytes, "application/octet-stream"))
        if normalized is None:
            raise RockboxMetadataWriteError("Artwork payload is empty")
        self._remember_normalized(digest, normalized)
        return normalized

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
    "RockboxMetadataFailure",
    "RockboxMetadataPassResult",
    "RockboxMetadataWriteError",
    "RockboxTrackWriteResult",
    "UnsupportedRockboxTagFormat",
    "write_rockbox_metadata_library",
    "write_rockbox_track_metadata",
]
