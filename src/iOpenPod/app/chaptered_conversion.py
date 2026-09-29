"""Prepare one chaptered Album on the Host for a reversible Library Draft."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from iOpenPod.app.display_text import source_text
from iOpenPod.app.media.importing import ImportedSong, MusicImporter, relocate_song
from iOpenPod.app.media.inspection import MediaInspector
from iOpenPod.app.media.models import StreamKind
from iOpenPod.app.media.music_paths import MusicPathAllocator
from iPodDB.library import MediaKind, Track, TrackChapter
from storage import HostPath
from storage.media_processing import discover_media_tools, run_media_tool

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator


def can_convert_album(selected: tuple[Track, ...], library: tuple[Track, ...]) -> bool:
    """Only a complete, saved, unchaptered Music Album can be replaced."""
    if len(selected) < 2 or len({t.track_id for t in selected}) != len(selected):
        return False
    first = selected[0]
    return (
        bool(first.album.strip())
        and all(
            track.track_id > 0
            and track.media_kind is MediaKind.MUSIC
            and track.album_key == first.album_key
            and track.length_ms > 0
            and track.metadata.location
            and not track.metadata.chapters
            for track in selected
        )
        and {t.track_id for t in selected}
        == {t.track_id for t in library if t.album_key == first.album_key}
    )


@dataclass(frozen=True, slots=True)
class ChapteredPreparation:
    song: ImportedSong
    directory: TemporaryDirectory[str]


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace(";", "\\;")
        .replace("#", "\\#")
        .replace("\n", "\\n")
    )


def chapter_timeline(
    tracks: tuple[Track, ...], durations_ms: tuple[int, ...]
) -> tuple[TrackChapter, ...]:
    if len(tracks) != len(durations_ms) or any(ms <= 0 for ms in durations_ms):
        raise ValueError("Every source Track needs a verified positive duration.")
    multi_disc = len({t.metadata.disc_number or 1 for t in tracks}) > 1
    chapters: list[TrackChapter] = []
    cursor = 0
    for index, (track, duration) in enumerate(
        zip(tracks, durations_ms, strict=True), 1
    ):
        title = track.title.strip() or f"Track {index}"
        number = track.track_number or index
        label = (
            f"Disc {track.metadata.disc_number or 1}, Track {number}: {title}"
            if multi_disc
            else f"{number:02d}. {title}"
        )
        chapters.append(TrackChapter(label, cursor))
        cursor += duration
    return tuple(chapters)


def _metadata(
    tracks: tuple[Track, ...], chapters: tuple[TrackChapter, ...], total: int
) -> str:
    first = tracks[0]
    values = (
        ("title", first.album),
        ("artist", first.effective_album_artist),
        ("album", first.album),
        ("album_artist", first.effective_album_artist),
        ("genre", first.genre),
        ("date", str(first.year) if first.year else ""),
    )
    lines = [
        ";FFMETADATA1",
        *(f"{key}={_escape(value)}" for key, value in values if value),
    ]
    for index, chapter in enumerate(chapters):
        end = chapters[index + 1].start_ms if index + 1 < len(chapters) else total
        lines.extend(
            (
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={chapter.start_ms}",
                f"END={end}",
                f"title={_escape(chapter.title)}",
            )
        )
    return "\n".join(lines) + "\n"


def prepare_chaptered_album(
    tracks: tuple[Track, ...],
    active: ActiveIPod,
    coordinator: DeviceCoordinator,
    occupied_paths: tuple[str, ...],
    *,
    checkpoint: Callable[[], None],
    report: Callable[[str], None] = lambda _message: None,
) -> ChapteredPreparation:
    """Copy through Storage, encode, inspect, and retain the Host output."""
    if not can_convert_album(tracks, active.library.tracks):
        raise ValueError(
            "Select a complete saved Music Album with at least two Tracks."
        )
    tools = discover_media_tools(checkpoint=checkpoint)
    if "aac" in tools.encoders:
        extension, codec = "m4a", "aac"
    elif "libmp3lame" in tools.encoders:
        extension, codec = "mp3", "libmp3lame"
    else:
        raise ValueError("FFmpeg needs an AAC or MP3 encoder for this iPod.")
    directory = TemporaryDirectory(prefix="iopenpod-chaptered-")
    try:
        root = Path(directory.name)
        inspector = MediaInspector(tools.ffprobe)
        sources: list[HostPath] = []
        durations: list[int] = []
        for index, track in enumerate(tracks):
            checkpoint()
            report(source_text("Copying and checking Album Tracks…"))
            if coordinator.active_ipod is not active:
                raise ValueError("The Active iPod changed during Album conversion.")
            suffix = Path(track.metadata.location).suffix or ".media"
            target = HostPath(root / f"source-{index}{suffix}")
            coordinator.copy_track_to_host(track, target)
            observed = inspector.inspect(target, checkpoint=checkpoint)
            if len(observed.audio_streams) != 1 or any(
                stream.kind is StreamKind.VIDEO and stream.attached_picture is not True
                for stream in observed.streams
            ):
                raise ValueError(
                    f"{track.title} does not contain one playable audio stream."
                )
            duration = (
                observed.audio_streams[0].duration_seconds or observed.duration_seconds
            )
            if duration is None:
                raise ValueError(f"{track.title} has no measurable duration.")
            duration_ms = round(float(duration) * 1000)
            if abs(duration_ms - track.length_ms) > max(500, track.length_ms // 100):
                raise ValueError(f"{track.title} changed since the Library was loaded.")
            sources.append(target)
            durations.append(duration_ms)
        chapters = chapter_timeline(tracks, tuple(durations))
        total = sum(durations)
        metadata = root / "chapters.ffmetadata"
        metadata.write_text(_metadata(tracks, chapters, total), encoding="utf-8")
        output = HostPath(root / f"chaptered.{extension}")
        filters: list[str] = []
        labels: list[str] = []
        arguments: list[str] = ["-hide_banner", "-nostdin", "-y"]
        for index, source in enumerate(sources):
            arguments.extend(("-i", str(source)))
            filters.append(
                f"[{index}:a:0]aresample=44100,"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
            )
            labels.append(f"[a{index}]")
        arguments.extend(("-i", str(metadata)))
        filters.append(f"{''.join(labels)}concat=n={len(sources)}:v=0:a=1[aout]")
        arguments.extend(
            (
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[aout]",
                "-map_metadata",
                str(len(sources)),
                "-map_chapters",
                str(len(sources)),
                "-c:a",
                codec,
                "-b:a",
                "192k",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-progress",
                "pipe:1",
                str(output),
            )
        )
        report(source_text("Encoding the chaptered Album…"))
        run_media_tool(
            tools.ffmpeg,
            tuple(arguments),
            checkpoint=checkpoint,
            timeout_seconds=max(120, total / 1000 * 4),
            progress=lambda _sample: checkpoint(),
        )
        checkpoint()
        if coordinator.active_ipod is not active:
            raise ValueError("The Active iPod changed during Album conversion.")
        report(source_text("Checking the chaptered output…"))
        imported = MusicImporter(inspector).inspect(
            output, active.profile, checkpoint=checkpoint
        )
        if abs(imported.track.length_ms - total) > max(500, total // 100):
            raise ValueError(
                "The chaptered output duration does not match its source Tracks."
            )
        if chapters[-1].start_ms >= imported.track.length_ms:
            raise ValueError("The final chapter falls outside the encoded Track.")
        first = tracks[0]
        imported = replace(
            imported,
            track=replace(
                imported.track,
                title=first.album,
                artist=first.effective_album_artist,
                album=first.album,
                album_artist=first.effective_album_artist,
                genre=first.genre,
                year=first.year,
                track_number=1,
                metadata=replace(
                    imported.track.metadata,
                    total_tracks=1,
                    disc_number=1,
                    total_discs=1,
                    chapters=chapters,
                ),
            ),
        )
        path = MusicPathAllocator(
            active.profile.capabilities.database.music_directory_count,
            occupied_paths,
        ).allocate(extension, checkpoint=checkpoint)
        return ChapteredPreparation(relocate_song(imported, path), directory)
    except BaseException:
        directory.cleanup()
        raise
