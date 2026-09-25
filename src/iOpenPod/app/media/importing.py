"""Inspect selected music into immutable, content-bound Library draft inputs."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol, cast

import mutagen
from mutagen.mp3 import BitrateMode
from PIL import Image, ImageOps

from iOpenPod.app.media.inspection import MediaInspectionError, MediaInspector
from iOpenPod.app.media.lyrics import embedded_lyrics
from iOpenPod.app.media.models import StreamKind
from iOpenPod.app.media.music_paths import MusicPathAllocator
from iPodDB.library import (
    ArtworkPixels,
    AudioEncoding,
    FileDependency,
    PreparedMedia,
    Track,
    TrackChapter,
    TrackMetadata,
    prepared_audio,
)
from storage import FileFingerprint, HostPath, capture_host_file
from storage.host_input import LocalHostFile

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import BinaryIO

    from device_registry import DeviceProfile
    from iOpenPod.app.media.models import MediaInspection


class _MutagenReader(Protocol):
    """The stream read operation used from Mutagen's untyped API."""

    def File(self, fileobj: BinaryIO) -> Any: ...


class _EmbeddedPicture(Protocol):
    """ID3 APIC fields needed to select an embedded front cover."""

    type: int
    mime: str
    data: bytes


@dataclass(frozen=True, slots=True)
class LibraryMediaSource:
    """A selected Host source and the exact facts required by its draft Track."""

    source: HostPath
    fingerprint: FileFingerprint
    media: PreparedMedia


@dataclass(frozen=True, slots=True)
class ImportedSong:
    track: Track
    source: LibraryMediaSource
    artwork: ArtworkPixels | None = None


def relocate_song(song: ImportedSong, location: str) -> ImportedSong:
    """Bind the Track and its verified media facts to one allocated destination."""
    return replace(
        song,
        track=replace(
            song.track,
            metadata=replace(song.track.metadata, location=location),
        ),
        source=replace(
            song.source,
            media=replace(
                song.source.media,
                file=replace(song.source.media.file, relative_path=location),
            ),
        ),
    )


class MusicImporter:
    """Prepare compatible music for review; perform no device writes or conversion."""

    def __init__(self, inspector: MediaInspector | None = None) -> None:
        self._inspector = inspector or MediaInspector()

    def inspect(
        self,
        source: HostPath,
        profile: DeviceProfile,
        *,
        checkpoint: Callable[[], None],
    ) -> ImportedSong:
        with capture_host_file(source, checkpoint=checkpoint) as captured:
            observed = self._inspector.inspect_captured(captured, checkpoint=checkpoint)
            encoding = _encoding(observed, profile)
            checkpoint()
            # All tag/artwork reads observe the same private snapshot as FFprobe.
            with LocalHostFile.observe(captured.snapshot).open_read(
                checkpoint=checkpoint
            ) as stream:
                parsed = cast("_MutagenReader", mutagen).File(stream)
                cover = (
                    _cover(parsed)
                    if profile.capabilities.artwork.supports_cover_art
                    else None
                )
            checkpoint()
        audio = observed.audio_streams[0]
        duration = audio.duration_seconds or observed.duration_seconds
        assert duration is not None and audio.sample_rate_hz is not None
        tags = {t.name.casefold(): t.value for t in (*observed.tags, *audio.tags)}
        number, total = _pair(tags.get("track", ""))
        disc, discs = _pair(tags.get("disc", ""))
        extension, description = {
            AudioEncoding.MP3: ("mp3", "MPEG audio file"),
            AudioEncoding.AAC: ("m4a", "AAC audio file"),
            AudioEncoding.ALAC: ("m4a", "Apple Lossless audio file"),
            AudioEncoding.WAV: ("wav", "WAV audio file"),
            AudioEncoding.AIFF: ("aiff", "AIFF audio file"),
        }[encoding]
        location = MusicPathAllocator(
            profile.capabilities.database.music_directory_count
        ).allocate(extension)
        track = Track(
            0,
            tags.get("title") or source.path.stem,
            tags.get("artist", ""),
            tags.get("album", ""),
            max(1, round(duration * 1000)),
            genre=tags.get("genre", ""),
            year=_number(tags.get("date", tags.get("year", ""))[:4]),
            track_number=number,
            size_bytes=observed.fingerprint.size,
            bitrate_kbps=round((audio.bitrate_bps or observed.bitrate_bps or 0) / 1000),
            album_artist=tags.get("album_artist", tags.get("albumartist", "")),
            metadata=TrackMetadata(
                file_format=description,
                sample_rate_hz=audio.sample_rate_hz,
                variable_bitrate=(
                    encoding is AudioEncoding.MP3
                    and getattr(getattr(parsed, "info", None), "bitrate_mode", None)
                    in (BitrateMode.VBR, BitrateMode.ABR)
                ),
                total_tracks=total,
                disc_number=disc,
                total_discs=discs,
                compilation=tags.get("compilation", "0") == "1",
                composer=tags.get("composer", ""),
                comment=tags.get("comment", ""),
                lyrics=embedded_lyrics(parsed),
                date_added=int(time.time()),
                last_modified=observed.fingerprint.modified_ns // 1_000_000_000,
                location=location,
                chapters=tuple(
                    TrackChapter(
                        next(
                            (t.value for t in c.tags if t.name.casefold() == "title"),
                            "",
                        ),
                        round(c.start_seconds * 1000),
                    )
                    for c in observed.chapters
                ),
            ),
        )
        media = prepared_audio(
            0,
            FileDependency(location, track.size_bytes, observed.fingerprint.sha256),
            encoding,
        )
        return ImportedSong(
            track, LibraryMediaSource(source, observed.fingerprint, media), cover
        )


def _encoding(observed: MediaInspection, profile: DeviceProfile) -> AudioEncoding:
    def reject(detail: str) -> None:
        raise MediaInspectionError("media.incompatible", detail)

    if len(observed.audio_streams) != 1 or any(
        s.kind is StreamKind.VIDEO and s.attached_picture is not True
        for s in observed.streams
    ):
        reject(
            "Add Music requires one audio stream and no motion video; select a prepared music file."
        )
    audio = observed.audio_streams[0]
    if (
        audio.channels not in (1, 2)
        or not audio.sample_rate_hz
        or audio.sample_rate_hz > 48000
    ):
        reject(
            "Prepare mono or stereo music at a sample rate of at most 48 kHz for this iPod."
        )
    duration = audio.duration_seconds or observed.duration_seconds
    if duration is None or duration <= 0:
        reject("The music file does not have a verified positive duration.")
    containers = set(observed.containers)
    if audio.codec == "mp3" and "mp3" in containers:
        return AudioEncoding.MP3
    if "mov" in containers and audio.codec_tag in ("mp4a", "alac"):
        if audio.codec == "aac" and audio.profile == "LC":
            if audio.bitrate_bps is None or not 0 < audio.bitrate_bps <= 320000:
                reject("Prepare AAC LC at no more than 320 kb/s for this iPod.")
            return AudioEncoding.AAC
        if audio.codec == "alac" and profile.capabilities.audio.supports_alac:
            if (audio.bits_per_raw_sample or audio.bits_per_sample) != 16:
                reject("Prepare 16-bit Apple Lossless audio for this iPod.")
            return AudioEncoding.ALAC
    if audio.codec == "pcm_s16le" and "wav" in containers:
        return AudioEncoding.WAV
    if audio.codec == "pcm_s16be" and "aiff" in containers:
        return AudioEncoding.AIFF
    reject(
        "This music needs preparation before import. Supported inputs are MP3, AAC LC, Apple Lossless, and 16-bit WAV/AIFF."
    )
    raise AssertionError("unreachable")


def _cover(parsed: Any) -> ArtworkPixels | None:
    if parsed is None:
        return None
    tags = getattr(parsed, "tags", None)
    data: bytes | None = None
    if tags is not None:
        if hasattr(tags, "getall"):
            pictures = cast("list[_EmbeddedPicture]", tags.getall("APIC"))
            pictures.sort(key=lambda p: p.type != 3)
            data = next((p.data for p in pictures if p.mime != "-->"), None)
        else:
            covers = tags.get("covr", ())
            if covers:
                data = bytes(covers[0])
    if data is None:
        return None
    if len(data) > 32 * 1024 * 1024:
        raise ValueError("Embedded cover exceeds 32 MiB.")
    with Image.open(io.BytesIO(data)) as image:
        if max(image.size) > 8192 or image.width * image.height > 32 * 1024 * 1024:
            raise ValueError("Embedded cover dimensions exceed the artwork limit.")
        rgb = ImageOps.exif_transpose(image).convert("RGB")
        return ArtworkPixels(rgb.width, rgb.height, rgb.tobytes())


def _number(value: str) -> int:
    return int(value) if value.isascii() and value.isdigit() and len(value) <= 4 else 0


def _pair(value: str) -> tuple[int, int]:
    parts = value.split("/", 1)
    return _number(parts[0]), _number(parts[1]) if len(parts) > 1 else 0
