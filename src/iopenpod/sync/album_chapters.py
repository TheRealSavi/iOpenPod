"""Album-to-chaptered-track conversion helpers."""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iopenpod.infrastructure.media_folders import media_folder_paths
from iopenpod.itunesdb_shared.constants import (
    MEDIA_TYPE_AUDIO,
    MEDIA_TYPE_AUDIO_VIDEO,
    MEDIA_TYPE_AUDIOBOOK,
    MEDIA_TYPE_PODCAST,
)

from .ipod_track_paths import existing_ipod_track_file_path
from .mapping import MappingFile
from .pc_library import PCLibrary, PCTrack
from .transcoder import (
    TranscodeOptions,
    TranscodeTarget,
    _aac_quality_args,
    _mp3_quality_args,
    find_ffmpeg,
    resolve_effective_encoder,
)

logger = logging.getLogger(__name__)

CONVERSION_SOURCE_PREFIX = "__iopenpod_album_conversion__/"
CHAPTER_SPLIT_SOURCE_PREFIX = "__iopenpod_chapter_split__/"


@dataclass(frozen=True)
class ResolvedAlbumSource:
    """One album track paired with the audio file used for conversion."""

    track: dict
    source_path: Path
    source_kind: str
    fingerprint: str | None = None


@dataclass(frozen=True)
class AlbumConversionOutput:
    """Result of building a chaptered album file."""

    output_path: Path
    pc_track: PCTrack
    chapters: list[dict[str, Any]]
    lyrics: str
    warnings: tuple[str, ...] = ()
    source_fingerprints: tuple[str, ...] = ()
    source_path_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChapterSplitSegment:
    """One chapter slice to export as a standalone track."""

    index: int
    title: str
    start_ms: int
    end_ms: int | None = None

    @property
    def duration_ms(self) -> int | None:
        if self.end_ms is None:
            return None
        return max(0, self.end_ms - self.start_ms)


@dataclass(frozen=True)
class ChapterSplitOutput:
    """Result of splitting a chaptered track into standalone tracks."""

    output_paths: tuple[Path, ...]
    pc_tracks: tuple[PCTrack, ...]
    warnings: tuple[str, ...] = ()
    source_fingerprint: str | None = None
    source_path_hint: str | None = None


def is_music_track(track: dict) -> bool:
    """Return whether a parsed iPod track belongs to the music browser."""

    try:
        media_type = int(track.get("media_type", MEDIA_TYPE_AUDIO) or 0)
    except (TypeError, ValueError):
        media_type = MEDIA_TYPE_AUDIO
    return media_type == MEDIA_TYPE_AUDIO_VIDEO or bool(media_type & MEDIA_TYPE_AUDIO)


def resolve_album_tracks(album_item: dict, all_tracks: list[dict]) -> list[dict]:
    """Resolve an album grid payload to sorted music tracks."""

    filter_key = str(album_item.get("filter_key") or "").lower()
    filter_value = album_item.get("filter_value")
    album = album_item.get("album") or album_item.get("title") or ""
    artist = album_item.get("artist") or ""

    matches: list[dict] = []
    for track in all_tracks:
        if not is_music_track(track):
            continue

        if filter_key in {"album_id", "album id"} and filter_value is not None:
            if _coerce_int(track.get("album_id")) == _coerce_int(filter_value):
                matches.append(track)
            continue

        if filter_key in {"album", "albums"} and filter_value is not None:
            if track.get("Album") == filter_value and _artist_matches(track, artist):
                matches.append(track)
            continue

        if track.get("Album") == album and _artist_matches(track, artist):
            matches.append(track)

    if not matches and album:
        matches = [
            track for track in all_tracks
            if is_music_track(track) and track.get("Album") == album
        ]

    return sorted(matches, key=_album_sort_key)


def build_chapter_timeline(tracks: list[dict]) -> list[dict[str, Any]]:
    """Create chapter markers from parsed track dictionaries."""

    chapters: list[dict[str, Any]] = []
    cursor_ms = 0
    multi_disc = len({_coerce_int(t.get("disc_number")) or 1 for t in tracks}) > 1

    for index, track in enumerate(tracks, start=1):
        title = str(track.get("Title") or f"Track {index}").strip()
        track_no = _coerce_int(track.get("track_number")) or index
        disc_no = _coerce_int(track.get("disc_number")) or 1
        if multi_disc:
            label = f"Disc {disc_no}, Track {track_no}: {title}"
        elif track_no:
            label = f"{track_no:02d}. {title}"
        else:
            label = title
        start_ms = int(cursor_ms)
        cursor_ms += max(0, _coerce_int(track.get("length")) or 0)
        chapters.append({"startpos": start_ms, "endpos": int(cursor_ms), "title": label})

    return chapters


def build_chapter_lyrics(chapters: list[dict[str, Any]]) -> str:
    """Build a simple timestamped chapter index for the iPod lyrics pane."""

    lines = []
    for chapter in chapters:
        ms = _coerce_int(chapter.get("startpos")) or 0
        lines.append(f"[{_format_timestamp(ms)}] {chapter.get('title') or 'Chapter'}")
    return "\n".join(lines)


def build_chapter_split_segments(track: dict) -> list[ChapterSplitSegment]:
    """Build ordered chapter slices from one parsed iPod track."""

    chapters = _chapter_entries(track)
    if len(chapters) < 2:
        raise ValueError("Choose a track with at least two chapters.")

    track_length = _coerce_int(track.get("length"))
    segments: list[ChapterSplitSegment] = []
    for index, chapter in enumerate(chapters):
        start_ms = max(0, _coerce_int(chapter.get("startpos")))
        if index + 1 < len(chapters):
            end_ms = max(0, _coerce_int(chapters[index + 1].get("startpos")))
        else:
            end_ms = _coerce_int(chapter.get("endpos")) or track_length or 0

        title = str(chapter.get("title") or "").strip() or f"Chapter {index + 1}"
        if end_ms <= start_ms:
            if index + 1 == len(chapters) and not track_length:
                segments.append(ChapterSplitSegment(index + 1, title, start_ms, None))
            continue
        segments.append(ChapterSplitSegment(index + 1, title, start_ms, end_ms))

    if len(segments) < 2:
        raise ValueError("Could not find at least two valid chapter ranges.")
    return [
        ChapterSplitSegment(index + 1, segment.title, segment.start_ms, segment.end_ms)
        for index, segment in enumerate(segments)
    ]


def resolve_album_sources(
    tracks: list[dict],
    *,
    pc_folders: tuple[Any, ...],
    ipod_path: str,
    mapping: MappingFile | None = None,
    fpcalc_path: str = "",
) -> tuple[list[ResolvedAlbumSource], tuple[str, ...]]:
    """Resolve conversion input files, preferring PC originals then iPod files."""

    roots = [Path(path) for path in media_folder_paths(pc_folders)]
    warnings: list[str] = []
    resolved: list[ResolvedAlbumSource] = []
    missing: list[dict[str, str]] = []

    for track in tracks:
        db_track_id = _coerce_int(track.get("db_track_id", track.get("db_id")))
        fingerprint = None
        source = None
        source_kind = "pc"

        source_hint = ""
        if mapping is not None and db_track_id:
            mapped = mapping.get_by_db_track_id(db_track_id)
            if mapped is not None:
                fingerprint, entry = mapped
                source_hint = str(entry.source_path_hint or "")
                source = _resolve_hint(entry.source_path_hint, roots)

        if source is None:
            for key in ("source_path", "Source Path"):
                raw = track.get(key)
                if raw:
                    candidate = Path(str(raw)).expanduser()
                    if candidate.exists() and candidate.is_file():
                        source = candidate
                        break

        if source is None:
            source = existing_ipod_track_file_path(
                ipod_path,
                track,
                allow_music_filename_fallback=True,
            )
            source_kind = "ipod"
            title = track.get("Title") or track.get("Location") or "track"
            warnings.append(f"Used iPod copy for {title}; original PC file was not found.")

        if source is None:
            title = track.get("Title") or "Unknown"
            missing.append(
                {
                    "title": str(title),
                    "db_track_id": str(db_track_id or ""),
                    "source_hint": source_hint,
                    "location": str(track.get("Location") or track.get("location") or ""),
                }
            )
            continue

        if fingerprint is None and fpcalc_path:
            try:
                from .audio_fingerprint import get_or_compute_fingerprint_with_status

                fingerprint, _fingerprint_status = (
                    get_or_compute_fingerprint_with_status(
                        source,
                        fpcalc_path=fpcalc_path,
                        write_to_file=False,
                    )
                )
            except Exception:
                logger.debug("Could not fingerprint conversion source %s", source, exc_info=True)

        resolved.append(
            ResolvedAlbumSource(
                track=track,
                source_path=source,
                source_kind=source_kind,
                fingerprint=fingerprint,
            )
        )

    if missing:
        raise FileNotFoundError(_format_missing_sources(missing))

    return resolved, tuple(warnings)


def resolve_track_source(
    track: dict,
    *,
    pc_folders: tuple[Any, ...],
    ipod_path: str,
    mapping: MappingFile | None = None,
    fpcalc_path: str = "",
) -> tuple[ResolvedAlbumSource, tuple[str, ...]]:
    """Resolve one track source, preferring the PC original then the iPod file."""

    sources, warnings = resolve_album_sources(
        [track],
        pc_folders=pc_folders,
        ipod_path=ipod_path,
        mapping=mapping,
        fpcalc_path=fpcalc_path,
    )
    if not sources:
        title = track.get("Title") or "Unknown"
        raise FileNotFoundError(f"Could not resolve audio source for {title}")
    return sources[0], warnings


def convert_album_to_chaptered_track(
    *,
    album_item: dict,
    tracks: list[dict],
    sources: list[ResolvedAlbumSource],
    output_dir: Path,
    settings: Any,
    artwork_bytes: bytes | None = None,
) -> AlbumConversionOutput:
    """Build one iPod-native album file plus DB-side chapter markers."""

    if len(tracks) < 2:
        raise ValueError("Album conversion requires at least two tracks.")
    if len(sources) != len(tracks):
        raise ValueError("Source count does not match track count.")

    options = TranscodeOptions.from_settings(settings).normalized()
    ffmpeg = find_ffmpeg(options.ffmpeg_path)
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to convert an album.")

    output_dir.mkdir(parents=True, exist_ok=True)

    album_title = str(album_item.get("album") or album_item.get("title") or "Album").strip()
    album_artist = str(album_item.get("artist") or _first_text(tracks, "Album Artist") or _first_text(tracks, "Artist") or "Unknown Artist").strip()
    target, encoder = resolve_effective_encoder(options)
    output_suffix = ".mp3" if target == TranscodeTarget.MP3 else ".m4a"
    output_path = _unique_output_path(output_dir, f"{album_artist} - {album_title}", output_suffix)
    chapters = build_chapter_timeline(tracks)
    lyrics = build_chapter_lyrics(chapters)

    with tempfile.TemporaryDirectory(prefix="iopenpod_album_chapters_") as tmp:
        metadata_path = Path(tmp) / "chapters.ffmetadata"
        metadata_path.write_text(
            _build_ffmetadata(
                chapters,
                title=album_title,
                artist=album_artist,
                album=album_title,
                album_artist=album_artist,
                year=_first_int(tracks, "year"),
                genre=_first_text(tracks, "Genre"),
            ),
            encoding="utf-8",
        )

        cmd = _build_ffmpeg_concat_command(
            ffmpeg=ffmpeg,
            sources=[source.source_path for source in sources],
            metadata_path=metadata_path,
            output_path=output_path,
            options=options,
            target=target,
            encoder=encoder,
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_conversion_timeout_seconds(tracks),
        )
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()[-1:] or ["FFmpeg failed"]
            raise RuntimeError(detail[0])

    _tag_generated_file(
        output_path,
        album_title=album_title,
        album_artist=album_artist,
        tracks=tracks,
        lyrics=lyrics,
        artwork_bytes=artwork_bytes,
    )

    pc_track = _read_generated_pc_track(output_path)
    pc_track.title = album_title
    pc_track.artist = album_artist
    pc_track.album = album_title
    pc_track.album_artist = album_artist
    pc_track.genre = _first_text(tracks, "Genre")
    pc_track.year = _first_int(tracks, "year")
    pc_track.track_number = 1
    pc_track.track_total = 1
    pc_track.disc_number = 1
    pc_track.disc_total = 1
    pc_track.comment = "iOpenPod chaptered album conversion"
    pc_track.has_lyrics = True
    pc_track.lyrics = lyrics
    # iTunesDB chapter data is independent of the generated file container.
    # Embedded file chapters are only a best-effort convenience from FFmpeg.
    pc_track.chapters = chapters
    pc_track.relative_path = CONVERSION_SOURCE_PREFIX + output_path.name
    pc_track.needs_transcoding = False
    pc_track.is_podcast = False
    pc_track.is_audiobook = False

    warnings = [warning for warning in (source.source_kind for source in sources) if warning == "ipod"]
    source_fps = tuple(
        source.fingerprint for source in sources if source.fingerprint
    )
    return AlbumConversionOutput(
        output_path=output_path,
        pc_track=pc_track,
        chapters=chapters,
        lyrics=lyrics,
        warnings=tuple(warnings),
        source_fingerprints=source_fps,
        source_path_hints=tuple(str(source.source_path) for source in sources),
    )


def split_track_into_chapter_tracks(
    *,
    track: dict,
    source: ResolvedAlbumSource,
    output_dir: Path,
    settings: Any,
    artwork_bytes: bytes | None = None,
) -> ChapterSplitOutput:
    """Split one chaptered track into standalone iPod-native tracks."""

    segments = build_chapter_split_segments(track)
    options = TranscodeOptions.from_settings(settings).normalized()
    ffmpeg = find_ffmpeg(options.ffmpeg_path)
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to split a chaptered track.")

    output_dir.mkdir(parents=True, exist_ok=True)
    target, encoder = resolve_effective_encoder(options)
    output_suffix = ".mp3" if target == TranscodeTarget.MP3 else ".m4a"
    album_title = _original_album_title(track)
    artist = _track_text(track, "Artist") or "Unknown Artist"
    base_stem = f"{artist} - {album_title}"

    output_paths: list[Path] = []
    pc_tracks: list[PCTrack] = []
    for segment in segments:
        output_path = _unique_output_path(
            output_dir,
            f"{base_stem} - {segment.index:02d} {segment.title}",
            output_suffix,
        )
        cmd = _build_ffmpeg_split_command(
            ffmpeg=ffmpeg,
            source=source.source_path,
            output_path=output_path,
            segment=segment,
            options=options,
            target=target,
            encoder=encoder,
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_split_timeout_seconds(segment),
        )
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()[-1:] or ["FFmpeg failed"]
            raise RuntimeError(detail[0])

        _tag_split_file(
            output_path,
            source_track=track,
            segment=segment,
            total_segments=len(segments),
            artwork_bytes=artwork_bytes,
        )
        pc_track = _read_generated_pc_track(output_path)
        _apply_split_metadata(
            pc_track,
            source_track=track,
            segment=segment,
            total_segments=len(segments),
        )
        output_paths.append(output_path)
        pc_tracks.append(pc_track)

    return ChapterSplitOutput(
        output_paths=tuple(output_paths),
        pc_tracks=tuple(pc_tracks),
        source_fingerprint=source.fingerprint,
        source_path_hint=str(source.source_path),
    )


def _artist_matches(track: dict, artist: str) -> bool:
    if not artist:
        return True
    return artist in {
        str(track.get("Album Artist") or ""),
        str(track.get("Artist") or ""),
    }


def _album_sort_key(track: dict) -> tuple[int, int, str, int]:
    return (
        _coerce_int(track.get("disc_number")) or 1,
        _coerce_int(track.get("track_number")) or 0,
        str(track.get("Title") or "").lower(),
        _coerce_int(track.get("db_track_id", track.get("db_id"))) or 0,
    )


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _first_text(tracks: list[dict], key: str) -> str | None:
    for track in tracks:
        value = str(track.get(key) or "").strip()
        if value:
            return value
    return None


def _first_int(tracks: list[dict], key: str) -> int | None:
    for track in tracks:
        value = _coerce_int(track.get(key))
        if value:
            return value
    return None


def _track_text(track: dict, *keys: str) -> str | None:
    for key in keys:
        value = str(track.get(key) or "").strip()
        if value:
            return value
    return None


def _track_int(track: dict, *keys: str) -> int:
    for key in keys:
        value = _coerce_int(track.get(key))
        if value:
            return value
    return 0


def _chapter_entries(track: dict) -> list[dict[str, Any]]:
    chapter_data = track.get("chapter_data")
    if not isinstance(chapter_data, dict):
        return []
    raw_chapters = chapter_data.get("chapters")
    if not isinstance(raw_chapters, list):
        return []

    chapters: list[dict[str, Any]] = []
    for chapter in raw_chapters:
        if not isinstance(chapter, dict):
            continue
        startpos = _coerce_int(chapter.get("startpos"))
        title = str(chapter.get("title") or "").strip()
        entry = dict(chapter)
        entry["startpos"] = max(0, startpos)
        entry["title"] = title
        chapters.append(entry)
    chapters.sort(key=lambda chapter: _coerce_int(chapter.get("startpos")))
    return chapters


def _original_album_title(track: dict) -> str:
    return (
        _track_text(track, "Album")
        or _track_text(track, "Title")
        or "Unknown Album"
    )


def _format_timestamp(ms: int) -> str:
    total = max(0, int(ms)) // 1000
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _resolve_hint(hint: str | None, roots: list[Path]) -> Path | None:
    if not hint:
        return None
    normalized = str(hint).replace("\\", "/")
    if len(normalized) >= 2 and normalized[1] == ":" and normalized[0].isalpha():
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    raw = Path(normalized).expanduser()
    if raw.is_absolute() and raw.exists() and raw.is_file():
        return raw
    for root in roots:
        candidate = root / raw
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _format_missing_sources(missing: list[dict[str, str]]) -> str:
    titles = ", ".join(entry.get("title") or "Unknown" for entry in missing)
    details = []
    for entry in missing:
        detail = entry.get("title") or "Unknown"
        parts = []
        if entry.get("db_track_id"):
            parts.append(f"db_track_id={entry['db_track_id']}")
        if entry.get("source_hint"):
            parts.append(f"hint={entry['source_hint']}")
        if entry.get("location"):
            parts.append(f"location={entry['location']}")
        if parts:
            detail = f"{detail} ({'; '.join(parts)})"
        details.append(detail)
    detail_text = "\n".join(details)
    return (
        "Could not resolve audio source for one or more tracks: "
        f"{titles}\n{detail_text}"
    )


def _safe_filename(value: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value).strip(" .")
    return (text or "Chaptered Album")[:160]


def _unique_output_path(output_dir: Path, stem: str, suffix: str) -> Path:
    base = _safe_filename(stem)
    candidate = output_dir / f"{base}{suffix}"
    if not candidate.exists():
        return candidate
    for index in range(2, 10_000):
        candidate = output_dir / f"{base} {index}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not choose a unique output path in {output_dir}")


def _escape_ffmetadata(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace(";", "\\;")
        .replace("#", "\\#")
        .replace("\n", "\\n")
    )


def _build_ffmetadata(
    chapters: list[dict[str, Any]],
    *,
    title: str,
    artist: str,
    album: str,
    album_artist: str,
    year: int | None,
    genre: str | None,
) -> str:
    lines = [
        ";FFMETADATA1",
        f"title={_escape_ffmetadata(title)}",
        f"artist={_escape_ffmetadata(artist)}",
        f"album={_escape_ffmetadata(album)}",
        f"album_artist={_escape_ffmetadata(album_artist)}",
    ]
    if year:
        lines.append(f"date={year}")
    if genre:
        lines.append(f"genre={_escape_ffmetadata(genre)}")

    for index, chapter in enumerate(chapters):
        start = _coerce_int(chapter.get("startpos"))
        if index + 1 < len(chapters):
            end = _coerce_int(chapters[index + 1].get("startpos"))
        else:
            end = _coerce_int(chapter.get("endpos")) or start + 1
            end = max(start + 1, end)
        lines.extend([
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start}",
            f"END={end}",
            f"title={_escape_ffmetadata(chapter.get('title') or f'Chapter {index + 1}')}",
        ])
    return "\n".join(lines) + "\n"


def _build_ffmpeg_concat_command(
    *,
    ffmpeg: str,
    sources: list[Path],
    metadata_path: Path,
    output_path: Path,
    options: TranscodeOptions,
    target: TranscodeTarget,
    encoder: str,
) -> list[str]:
    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    for index, source in enumerate(sources):
        inputs.extend(["-i", str(source)])
        label = f"a{index}"
        labels.append(f"[{label}]")
        filters.append(
            f"[{index}:a:0]aresample=44100,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo[{label}]"
        )
    metadata_index = len(sources)
    inputs.extend(["-i", str(metadata_path)])
    filters.append(f"{''.join(labels)}concat=n={len(sources)}:v=0:a=1[aout]")

    quality = str(options.lossy_quality or "balanced")
    codec_args = _encoding_args(target, options=options, encoder=encoder, quality=quality)
    return [
        ffmpeg,
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[aout]",
        "-map_metadata",
        str(metadata_index),
        "-map_chapters",
        str(metadata_index),
        "-vn",
        *codec_args,
        "-y",
        str(output_path),
    ]


def _format_ffmpeg_time(ms: int) -> str:
    return f"{max(0, int(ms)) / 1000:.3f}"


def _build_ffmpeg_split_command(
    *,
    ffmpeg: str,
    source: Path,
    output_path: Path,
    segment: ChapterSplitSegment,
    options: TranscodeOptions,
    target: TranscodeTarget,
    encoder: str,
) -> list[str]:
    quality = str(options.lossy_quality or "balanced")
    duration_args: list[str] = []
    if segment.duration_ms is not None:
        duration_args = ["-t", _format_ffmpeg_time(segment.duration_ms)]

    return [
        ffmpeg,
        "-i",
        str(source),
        "-ss",
        _format_ffmpeg_time(segment.start_ms),
        *duration_args,
        "-map",
        "0:a:0",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-vn",
        "-ar",
        "44100",
        "-ac",
        "2",
        *_encoding_args(target, options=options, encoder=encoder, quality=quality),
        "-y",
        str(output_path),
    ]


def _encoding_args(
    target: TranscodeTarget,
    *,
    options: TranscodeOptions,
    encoder: str,
    quality: str,
) -> list[str]:
    if target == TranscodeTarget.MP3:
        return [
            "-c:a",
            encoder,
            *_mp3_quality_args(quality, options, encoder=encoder),
            "-id3v2_version",
            "3",
        ]
    return [
        "-c:a",
        encoder,
        *_aac_quality_args(quality, options, encoder=encoder),
        "-movflags",
        "+faststart",
    ]


def _conversion_timeout_seconds(tracks: list[dict]) -> int:
    duration_ms = sum(max(0, _coerce_int(track.get("length"))) for track in tracks)
    duration_s = duration_ms // 1000
    return max(300, min(24 * 60 * 60, duration_s + 600))


def _split_timeout_seconds(segment: ChapterSplitSegment) -> int:
    duration_ms = segment.duration_ms or 0
    duration_s = duration_ms // 1000
    return max(120, min(24 * 60 * 60, duration_s + 300))


def _apply_split_metadata(
    pc_track: PCTrack,
    *,
    source_track: dict,
    segment: ChapterSplitSegment,
    total_segments: int,
) -> None:
    media_type = _track_int(source_track, "media_type")
    artist = _track_text(source_track, "Artist") or "Unknown Artist"
    album_artist = _track_text(source_track, "Album Artist") or artist

    pc_track.title = segment.title
    pc_track.artist = artist
    pc_track.album = _original_album_title(source_track)
    pc_track.album_artist = album_artist
    pc_track.genre = _track_text(source_track, "Genre")
    pc_track.year = _track_int(source_track, "year") or None
    pc_track.track_number = segment.index
    pc_track.track_total = total_segments
    pc_track.disc_number = _track_int(source_track, "disc_number") or 1
    pc_track.disc_total = _track_int(source_track, "total_discs", "disc_total") or 1
    pc_track.comment = _split_comment(source_track)
    pc_track.composer = _track_text(source_track, "Composer")
    pc_track.grouping = _track_text(source_track, "Grouping")
    pc_track.bpm = _track_int(source_track, "bpm") or None
    pc_track.rating = _track_int(source_track, "rating") or None
    pc_track.sort_artist = _track_text(source_track, "Sort Artist")
    pc_track.sort_album = _track_text(source_track, "Sort Album")
    pc_track.sort_album_artist = _track_text(source_track, "Sort Album Artist")
    pc_track.sort_composer = _track_text(source_track, "Sort Composer")
    pc_track.compilation = bool(_track_int(source_track, "compilation_flag", "compilation"))
    pc_track.explicit_flag = _track_int(source_track, "explicit_flag")
    pc_track.date_released = _track_int(source_track, "date_released")
    if segment.duration_ms is not None:
        pc_track.duration_ms = segment.duration_ms
    pc_track.has_lyrics = False
    pc_track.lyrics = None
    pc_track.chapters = None
    pc_track.relative_path = CHAPTER_SPLIT_SOURCE_PREFIX + pc_track.filename
    pc_track.needs_transcoding = False
    pc_track.is_podcast = bool(media_type & MEDIA_TYPE_PODCAST)
    pc_track.is_audiobook = bool(media_type & MEDIA_TYPE_AUDIOBOOK)


def _split_comment(source_track: dict) -> str:
    original_title = _track_text(source_track, "Title")
    if original_title:
        return f"Split from chaptered track: {original_title}"
    return "iOpenPod chapter split"


def _tag_split_file(
    output_path: Path,
    *,
    source_track: dict,
    segment: ChapterSplitSegment,
    total_segments: int,
    artwork_bytes: bytes | None,
) -> None:
    if output_path.suffix.lower() == ".mp3":
        _tag_split_mp3_file(
            output_path,
            source_track=source_track,
            segment=segment,
            total_segments=total_segments,
            artwork_bytes=artwork_bytes,
        )
        return
    _tag_split_mp4_file(
        output_path,
        source_track=source_track,
        segment=segment,
        total_segments=total_segments,
        artwork_bytes=artwork_bytes,
    )


def _tag_split_mp4_file(
    output_path: Path,
    *,
    source_track: dict,
    segment: ChapterSplitSegment,
    total_segments: int,
    artwork_bytes: bytes | None,
) -> None:
    try:
        from mutagen.mp4 import MP4, MP4Cover

        artist = _track_text(source_track, "Artist") or "Unknown Artist"
        album_artist = _track_text(source_track, "Album Artist") or artist
        audio = MP4(str(output_path))
        if audio.tags is None:
            audio.add_tags()
        assert audio.tags is not None
        audio.tags["\xa9nam"] = [segment.title]
        audio.tags["\xa9ART"] = [artist]
        audio.tags["\xa9alb"] = [_original_album_title(source_track)]
        audio.tags["aART"] = [album_artist]
        genre = _track_text(source_track, "Genre")
        year = _track_int(source_track, "year")
        composer = _track_text(source_track, "Composer")
        grouping = _track_text(source_track, "Grouping")
        bpm = _track_int(source_track, "bpm")
        if genre:
            audio.tags["\xa9gen"] = [genre]
        if year:
            audio.tags["\xa9day"] = [str(year)]
        if composer:
            audio.tags["\xa9wrt"] = [composer]
        if grouping:
            audio.tags["\xa9grp"] = [grouping]
        if bpm:
            audio.tags["tmpo"] = [bpm]
        audio.tags["trkn"] = [(segment.index, total_segments)]
        audio.tags["disk"] = [(
            _track_int(source_track, "disc_number") or 1,
            _track_int(source_track, "total_discs", "disc_total") or 1,
        )]
        audio.tags["\xa9cmt"] = [_split_comment(source_track)]
        if artwork_bytes:
            image_format = (
                MP4Cover.FORMAT_PNG
                if artwork_bytes.startswith(b"\x89PNG")
                else MP4Cover.FORMAT_JPEG
            )
            audio.tags["covr"] = [MP4Cover(artwork_bytes, imageformat=image_format)]
        audio.save()
    except Exception:
        logger.debug("Could not tag split chapter file %s", output_path, exc_info=True)


def _tag_split_mp3_file(
    output_path: Path,
    *,
    source_track: dict,
    segment: ChapterSplitSegment,
    total_segments: int,
    artwork_bytes: bytes | None,
) -> None:
    try:
        from mutagen.id3 import ID3
        from mutagen.id3._frames import (
            APIC,
            COMM,
            TALB,
            TBPM,
            TCOM,
            TCON,
            TDRC,
            TIT2,
            TPE1,
            TPE2,
            TPOS,
            TRCK,
        )
        from mutagen.id3._util import ID3NoHeaderError

        try:
            audio = ID3(str(output_path))
        except ID3NoHeaderError:
            audio = ID3()

        artist = _track_text(source_track, "Artist") or "Unknown Artist"
        album_artist = _track_text(source_track, "Album Artist") or artist
        audio.setall("TIT2", [TIT2(encoding=3, text=[segment.title])])
        audio.setall("TPE1", [TPE1(encoding=3, text=[artist])])
        audio.setall("TALB", [TALB(encoding=3, text=[_original_album_title(source_track)])])
        audio.setall("TPE2", [TPE2(encoding=3, text=[album_artist])])
        audio.setall("TRCK", [TRCK(encoding=3, text=[f"{segment.index}/{total_segments}"])])
        audio.setall(
            "TPOS",
            [
                TPOS(
                    encoding=3,
                    text=[
                        f"{_track_int(source_track, 'disc_number') or 1}/"
                        f"{_track_int(source_track, 'total_discs', 'disc_total') or 1}"
                    ],
                )
            ],
        )
        genre = _track_text(source_track, "Genre")
        year = _track_int(source_track, "year")
        composer = _track_text(source_track, "Composer")
        bpm = _track_int(source_track, "bpm")
        if genre:
            audio.setall("TCON", [TCON(encoding=3, text=[genre])])
        if year:
            audio.setall("TDRC", [TDRC(encoding=3, text=[str(year)])])
        if composer:
            audio.setall("TCOM", [TCOM(encoding=3, text=[composer])])
        if bpm:
            audio.setall("TBPM", [TBPM(encoding=3, text=[str(bpm)])])
        audio.setall(
            "COMM:iOpenPod:eng",
            [COMM(encoding=3, lang="eng", desc="iOpenPod", text=_split_comment(source_track))],
        )
        if artwork_bytes:
            mime = "image/png" if artwork_bytes.startswith(b"\x89PNG") else "image/jpeg"
            audio.delall("APIC")
            audio.add(APIC(
                encoding=3,
                mime=mime,
                type=3,
                desc="Cover",
                data=artwork_bytes,
            ))
        audio.save(str(output_path), v2_version=3)
    except Exception:
        logger.debug("Could not tag split chapter file %s", output_path, exc_info=True)


def _tag_generated_file(
    output_path: Path,
    *,
    album_title: str,
    album_artist: str,
    tracks: list[dict],
    lyrics: str,
    artwork_bytes: bytes | None,
) -> None:
    if output_path.suffix.lower() == ".mp3":
        _tag_generated_mp3_file(
            output_path,
            album_title=album_title,
            album_artist=album_artist,
            tracks=tracks,
            lyrics=lyrics,
            artwork_bytes=artwork_bytes,
        )
        return
    _tag_generated_mp4_file(
        output_path,
        album_title=album_title,
        album_artist=album_artist,
        tracks=tracks,
        lyrics=lyrics,
        artwork_bytes=artwork_bytes,
    )


def _tag_generated_mp4_file(
    output_path: Path,
    *,
    album_title: str,
    album_artist: str,
    tracks: list[dict],
    lyrics: str,
    artwork_bytes: bytes | None,
) -> None:
    try:
        from mutagen.mp4 import MP4, MP4Cover

        audio = MP4(str(output_path))
        if audio.tags is None:
            audio.add_tags()
        assert audio.tags is not None
        audio.tags["\xa9nam"] = [album_title]
        audio.tags["\xa9ART"] = [album_artist]
        audio.tags["\xa9alb"] = [album_title]
        audio.tags["aART"] = [album_artist]
        genre = _first_text(tracks, "Genre")
        year = _first_int(tracks, "year")
        if genre:
            audio.tags["\xa9gen"] = [genre]
        if year:
            audio.tags["\xa9day"] = [str(year)]
        audio.tags["trkn"] = [(1, 1)]
        audio.tags["disk"] = [(1, 1)]
        audio.tags["\xa9cmt"] = ["iOpenPod chaptered album conversion"]
        audio.tags["\xa9lyr"] = [lyrics]
        if artwork_bytes:
            image_format = (
                MP4Cover.FORMAT_PNG
                if artwork_bytes.startswith(b"\x89PNG")
                else MP4Cover.FORMAT_JPEG
            )
            audio.tags["covr"] = [MP4Cover(artwork_bytes, imageformat=image_format)]
        audio.save()
    except Exception:
        logger.debug("Could not tag generated album file %s", output_path, exc_info=True)


def _tag_generated_mp3_file(
    output_path: Path,
    *,
    album_title: str,
    album_artist: str,
    tracks: list[dict],
    lyrics: str,
    artwork_bytes: bytes | None,
) -> None:
    try:
        from mutagen.id3 import ID3
        from mutagen.id3._frames import (
            APIC,
            COMM,
            TALB,
            TCON,
            TDRC,
            TIT2,
            TPE1,
            TPE2,
            TPOS,
            TRCK,
            USLT,
        )
        from mutagen.id3._util import ID3NoHeaderError

        try:
            audio = ID3(str(output_path))
        except ID3NoHeaderError:
            audio = ID3()

        genre = _first_text(tracks, "Genre")
        year = _first_int(tracks, "year")
        audio.setall("TIT2", [TIT2(encoding=3, text=[album_title])])
        audio.setall("TPE1", [TPE1(encoding=3, text=[album_artist])])
        audio.setall("TALB", [TALB(encoding=3, text=[album_title])])
        audio.setall("TPE2", [TPE2(encoding=3, text=[album_artist])])
        audio.setall("TRCK", [TRCK(encoding=3, text=["1/1"])])
        audio.setall("TPOS", [TPOS(encoding=3, text=["1/1"])])
        audio.setall(
            "COMM:iOpenPod:eng",
            [
                COMM(
                    encoding=3,
                    lang="eng",
                    desc="iOpenPod",
                    text="iOpenPod chaptered album conversion",
                )
            ],
        )
        audio.setall("USLT::eng", [USLT(encoding=3, lang="eng", desc="", text=lyrics)])
        if genre:
            audio.setall("TCON", [TCON(encoding=3, text=[genre])])
        if year:
            audio.setall("TDRC", [TDRC(encoding=3, text=[str(year)])])
        if artwork_bytes:
            mime = "image/png" if artwork_bytes.startswith(b"\x89PNG") else "image/jpeg"
            audio.delall("APIC")
            audio.add(APIC(
                encoding=3,
                mime=mime,
                type=3,
                desc="Cover",
                data=artwork_bytes,
            ))
        audio.save(str(output_path), v2_version=3)
    except Exception:
        logger.debug("Could not tag generated album file %s", output_path, exc_info=True)


def _read_generated_pc_track(output_path: Path) -> PCTrack:
    library = PCLibrary(str(output_path.parent))
    track = library._read_track(output_path)
    if track is None:
        raise RuntimeError(f"Could not read generated file: {output_path}")
    return track
