"""Export iPod Tracks, Photos, and interoperable collections to the Host."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote

from iPodDB.library import PhotoRepresentationKind
from storage import AtomicHostFile, HostPath

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.models.artwork import ArtworkImage
    from iOpenPod.app.models.photos import PhotoImage
    from iPodDB.library import Photo, Track
    from storage import CopyResult

_XSPF_NAMESPACE = "http://xspf.org/ns/0/"
_WPL_NAMESPACE = "http://schemas.microsoft.com/windows/MediaPlayer/Playlist/Format"
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_INVALID_TEXT_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class PlaylistFileType(StrEnum):
    """Supported interoperable Playlist document types."""

    M3U8 = "m3u8"
    M3U = "m3u"
    PLS = "pls"
    XSPF = "xspf"
    WPL = "wpl"

    @property
    def extension(self) -> str:
        return f".{self.value}"

    @property
    def label(self) -> str:
        return {
            PlaylistFileType.M3U8: "M3U8 — UTF-8 Extended M3U",
            PlaylistFileType.M3U: "M3U — Extended M3U",
            PlaylistFileType.PLS: "PLS",
            PlaylistFileType.XSPF: "XSPF",
            PlaylistFileType.WPL: "WPL — Windows Media Player",
        }[self]


class PlaylistExportMode(StrEnum):
    """Whether a Playlist targets the mounted iPod or exported media copies."""

    DEVICE_REFERENCES = "device_references"
    COPY_TRACKS = "copy_tracks"


class ExportCancelledError(Exception):
    """The user cancelled an export between safe file operations."""


@dataclass(frozen=True, slots=True)
class ExportProgress:
    completed: int
    total: int
    message: str


@dataclass(frozen=True, slots=True)
class ExportResult:
    playlist_file: HostPath | None
    track_files: tuple[HostPath, ...]


@dataclass(frozen=True, slots=True)
class PhotoExportResult:
    album_directory: HostPath | None
    photo_directories: tuple[HostPath, ...] = ()
    photo_files: tuple[HostPath, ...] = ()


class TrackExportSource(Protocol):
    """Narrow device-source contract consumed by the export workflow."""

    def reference_for_track(self, track: Track) -> HostPath: ...

    def copy_track_to_host(
        self,
        track: Track,
        destination: HostPath,
        *,
        prepare_staged: Callable[[HostPath], None] | None = None,
    ) -> CopyResult: ...

    def artwork_for_track(self, track: Track) -> ArtworkImage | None: ...


class ExportTagger(Protocol):
    """Prepare one private staged media file before Storage publishes it."""

    def require_supported(self, destination: HostPath) -> None: ...

    def prepare(
        self,
        destination: HostPath,
        track: Track,
        artwork: ArtworkImage | None,
    ) -> None: ...


class PhotoExportSource(Protocol):
    """Narrow device-source contract consumed by Photo Host export."""

    def require_photo_export_directory(self, directory: HostPath) -> None: ...

    def reference_for_photo(self, photo: Photo) -> HostPath | None: ...

    def copy_photo_to_host(
        self,
        photo: Photo,
        destination: HostPath,
        *,
        source: HostPath,
    ) -> CopyResult: ...

    def image_for_photo_export(
        self,
        photo: Photo,
        *,
        format_id: int,
    ) -> PhotoImage | None: ...


class PhotoExportEncoder(Protocol):
    """Encode decoded device pixels into one interoperable Host image."""

    def encode_jpeg(self, image: PhotoImage) -> bytes: ...


@dataclass(frozen=True, slots=True)
class _PlaylistEntry:
    track: Track
    location: str


class LibraryExporter:
    """Plan names, copy media through Storage, and publish Playlist files last."""

    def __init__(
        self,
        source: TrackExportSource,
        tagger: ExportTagger | None = None,
    ) -> None:
        from iOpenPod.app.export_tagging import ExportMediaTagger

        self._source = source
        self._tagger = tagger or ExportMediaTagger()

    def export_tracks(
        self,
        tracks: tuple[Track, ...],
        directory: HostPath,
        *,
        checkpoint: Callable[[], None] | None = None,
        progress: Callable[[ExportProgress], None] | None = None,
    ) -> ExportResult:
        unique = _unique_tracks(tracks)
        if not unique:
            raise ValueError("Select at least one Track to export.")
        references = self._references(unique, checkpoint)
        destinations = _media_destinations(directory, unique, references, set())
        self._require_taggable(destinations)
        self._copy_tracks(unique, destinations, checkpoint, progress)
        return ExportResult(None, tuple(destinations))

    def export_playlist(
        self,
        name: str,
        tracks: tuple[Track, ...],
        directory: HostPath,
        file_type: PlaylistFileType,
        mode: PlaylistExportMode,
        *,
        checkpoint: Callable[[], None] | None = None,
        progress: Callable[[ExportProgress], None] | None = None,
    ) -> ExportResult:
        title = name.strip() or "Playlist"
        unique = _unique_tracks(tracks)
        references = self._references(unique, checkpoint)
        reserved_names: set[str] = set()
        media_paths = (
            _media_destinations(directory, unique, references, reserved_names)
            if mode is PlaylistExportMode.COPY_TRACKS
            else ()
        )
        playlist_path = _available_child(
            directory,
            _safe_stem(title, "Playlist"),
            file_type.extension,
            reserved_names,
        )
        self._require_taggable(media_paths)

        if mode is PlaylistExportMode.COPY_TRACKS:
            by_id = {
                track.track_id: os.fspath(path.path.name)
                for track, path in zip(unique, media_paths, strict=True)
            }
            self._copy_tracks(unique, media_paths, checkpoint, progress)
        else:
            by_id = {
                track.track_id: os.fspath(reference.path)
                for track, reference in zip(unique, references, strict=True)
            }

        _checkpoint(checkpoint)
        entries = tuple(
            _PlaylistEntry(track, by_id[track.track_id]) for track in tracks
        )
        content = serialize_playlist(title, entries, file_type)
        AtomicHostFile(Path(os.fspath(playlist_path))).create_bytes(content)
        if progress is not None:
            progress(
                ExportProgress(
                    len(unique) + 1,
                    len(unique) + 1,
                    f"Created {playlist_path.path.name}",
                )
            )
        return ExportResult(playlist_path, tuple(media_paths))

    def _references(
        self,
        tracks: tuple[Track, ...],
        checkpoint: Callable[[], None] | None,
    ) -> tuple[HostPath, ...]:
        references: list[HostPath] = []
        for track in tracks:
            _checkpoint(checkpoint)
            references.append(self._source.reference_for_track(track))
        return tuple(references)

    def _copy_tracks(
        self,
        tracks: tuple[Track, ...],
        destinations: tuple[HostPath, ...],
        checkpoint: Callable[[], None] | None,
        progress: Callable[[ExportProgress], None] | None,
    ) -> None:
        total = len(tracks)
        for index, (track, destination) in enumerate(
            zip(tracks, destinations, strict=True), 1
        ):
            _checkpoint(checkpoint)
            if progress is not None:
                progress(
                    ExportProgress(
                        index - 1,
                        total,
                        f"Exporting {destination.path.name}",
                    )
                )
            artwork = self._source.artwork_for_track(track)
            self._source.copy_track_to_host(
                track,
                destination,
                prepare_staged=partial(
                    self._tagger.prepare,
                    track=track,
                    artwork=artwork,
                ),
            )

    def _require_taggable(self, destinations: tuple[HostPath, ...]) -> None:
        for destination in destinations:
            self._tagger.require_supported(destination)


class PillowPhotoExportEncoder:
    """Encode one decoded iTHMB rendition as ordinary high-quality JPEG data."""

    def encode_jpeg(self, image: PhotoImage) -> bytes:
        from PIL import Image

        output = BytesIO()
        decoded = Image.frombytes(
            "RGB",
            (image.width, image.height),
            image.rgb888,
        )
        decoded.save(output, format="JPEG", quality=95, optimize=True)
        return output.getvalue()


class PhotoExporter:
    """Export every retained Photo rendition into one folder per Photo."""

    def __init__(
        self,
        source: PhotoExportSource,
        encoder: PhotoExportEncoder | None = None,
    ) -> None:
        self._source = source
        self._encoder = encoder or PillowPhotoExportEncoder()

    def export_photos(
        self,
        photos: tuple[Photo, ...],
        directory: HostPath,
        *,
        checkpoint: Callable[[], None] | None = None,
        progress: Callable[[ExportProgress], None] | None = None,
    ) -> PhotoExportResult:
        unique = _unique_photos(photos)
        if not unique:
            raise ValueError("Select at least one Photo to export.")
        self._source.require_photo_export_directory(directory)
        references = self._references(unique, checkpoint)
        photo_directories, photo_files = self._copy_photos(
            unique,
            references,
            directory,
            checkpoint,
            progress,
        )
        return PhotoExportResult(
            album_directory=None,
            photo_directories=photo_directories,
            photo_files=photo_files,
        )

    def export_photo_album(
        self,
        name: str,
        photos: tuple[Photo, ...],
        directory: HostPath,
        *,
        checkpoint: Callable[[], None] | None = None,
        progress: Callable[[ExportProgress], None] | None = None,
    ) -> PhotoExportResult:
        unique = _unique_photos(photos)
        if not unique:
            raise ValueError("The Photo Album has no Photos to export.")
        self._source.require_photo_export_directory(directory)
        references = self._references(unique, checkpoint)
        album_directory = _create_available_directory(
            directory,
            _safe_stem(name, "Photo Album"),
        )
        photo_directories, photo_files = self._copy_photos(
            unique,
            references,
            album_directory,
            checkpoint,
            progress,
        )
        return PhotoExportResult(
            album_directory=album_directory,
            photo_directories=photo_directories,
            photo_files=photo_files,
        )

    def _references(
        self,
        photos: tuple[Photo, ...],
        checkpoint: Callable[[], None] | None,
    ) -> tuple[HostPath | None, ...]:
        references: list[HostPath | None] = []
        for photo in photos:
            _checkpoint(checkpoint)
            references.append(self._source.reference_for_photo(photo))
        return tuple(references)

    def _copy_photos(
        self,
        photos: tuple[Photo, ...],
        references: tuple[HostPath | None, ...],
        directory: HostPath,
        checkpoint: Callable[[], None] | None,
        progress: Callable[[ExportProgress], None] | None,
    ) -> tuple[tuple[HostPath, ...], tuple[HostPath, ...]]:
        format_ids = tuple(_photo_format_ids(photo) for photo in photos)
        for photo, reference, photo_format_ids in zip(
            photos,
            references,
            format_ids,
            strict=True,
        ):
            if reference is None and not photo_format_ids:
                raise ValueError(
                    f"Photo {photo.photo_id} has no readable full-resolution "
                    "file or iTHMB rendition."
                )

        total = sum(
            (1 if reference is not None else 0) + len(photo_format_ids)
            for reference, photo_format_ids in zip(
                references,
                format_ids,
                strict=True,
            )
        )
        completed = 0
        photo_directories: list[HostPath] = []
        photo_files: list[HostPath] = []
        for photo, reference, photo_format_ids in zip(
            photos,
            references,
            format_ids,
            strict=True,
        ):
            _checkpoint(checkpoint)
            photo_directory = _create_available_directory(
                directory,
                _photo_directory_stem(photo, reference),
            )
            photo_directories.append(photo_directory)
            reserved_names: set[str] = set()

            if reference is not None:
                source_path = Path(os.fspath(reference.path))
                destination = _available_child(
                    photo_directory,
                    _safe_stem(source_path.stem, f"Photo {photo.photo_id}"),
                    source_path.suffix,
                    reserved_names,
                )
                _checkpoint(checkpoint)
                _report_photo_progress(progress, completed, total, destination)
                self._source.copy_photo_to_host(
                    photo,
                    destination,
                    source=reference,
                )
                photo_files.append(destination)
                completed += 1

            for format_id in photo_format_ids:
                _checkpoint(checkpoint)
                image = self._source.image_for_photo_export(
                    photo,
                    format_id=format_id,
                )
                if image is None:
                    raise ValueError(
                        f"Photo {photo.photo_id} iTHMB format {format_id} "
                        "could not be decoded for export."
                    )
                destination = _available_child(
                    photo_directory,
                    f"iTHMB {format_id} - {image.width}x{image.height}",
                    ".jpg",
                    reserved_names,
                )
                _report_photo_progress(progress, completed, total, destination)
                AtomicHostFile(Path(os.fspath(destination))).create_bytes(
                    self._encoder.encode_jpeg(image)
                )
                photo_files.append(destination)
                completed += 1
        return tuple(photo_directories), tuple(photo_files)


def serialize_playlist(
    title: str,
    entries: tuple[_PlaylistEntry, ...],
    file_type: PlaylistFileType,
) -> bytes:
    """Serialize one complete Playlist document as UTF-8."""

    if file_type in (PlaylistFileType.M3U8, PlaylistFileType.M3U):
        text = _serialize_m3u(entries)
    elif file_type is PlaylistFileType.PLS:
        text = _serialize_pls(entries)
    elif file_type is PlaylistFileType.XSPF:
        text = _serialize_xspf(title, entries)
    else:
        text = _serialize_wpl(title, entries)
    return text.encode("utf-8")


def _serialize_m3u(entries: tuple[_PlaylistEntry, ...]) -> str:
    lines = ["#EXTM3U"]
    for entry in entries:
        lines.extend(
            (
                f"#EXTINF:{max(0, entry.track.length_ms) // 1000},{_display_name(entry.track)}",
                entry.location,
            )
        )
    return "\n".join(lines) + "\n"


def _serialize_pls(entries: tuple[_PlaylistEntry, ...]) -> str:
    lines = ["[playlist]"]
    for index, entry in enumerate(entries, 1):
        duration = max(0, entry.track.length_ms) // 1000
        lines.extend(
            (
                f"File{index}={entry.location}",
                f"Title{index}={_display_name(entry.track)}",
                f"Length{index}={duration if duration else -1}",
            )
        )
    lines.extend((f"NumberOfEntries={len(entries)}", "Version=2"))
    return "\n".join(lines) + "\n"


def _serialize_xspf(title: str, entries: tuple[_PlaylistEntry, ...]) -> str:
    root = ET.Element("playlist", version="1", xmlns=_XSPF_NAMESPACE)
    ET.SubElement(root, "title").text = _single_line(title)
    track_list = ET.SubElement(root, "trackList")
    for entry in entries:
        item = ET.SubElement(track_list, "track")
        ET.SubElement(item, "location").text = _location_uri(entry.location)
        if entry.track.title:
            ET.SubElement(item, "title").text = entry.track.title
        artist = entry.track.artist or entry.track.album_artist
        if artist:
            ET.SubElement(item, "creator").text = artist
        if entry.track.album:
            ET.SubElement(item, "album").text = entry.track.album
        if entry.track.length_ms > 0:
            ET.SubElement(item, "duration").text = str(entry.track.length_ms)
        if entry.track.track_number > 0:
            ET.SubElement(item, "trackNum").text = str(entry.track.track_number)
    ET.indent(root, space="  ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(root, encoding="unicode")
        + "\n"
    )


def _serialize_wpl(title: str, entries: tuple[_PlaylistEntry, ...]) -> str:
    root = ET.Element("smil", xmlns=_WPL_NAMESPACE)
    head = ET.SubElement(root, "head")
    ET.SubElement(head, "meta", name="Generator", content="iOpenPod 2.0")
    ET.SubElement(head, "meta", name="ItemCount", content=str(len(entries)))
    ET.SubElement(head, "title").text = _single_line(title)
    sequence = ET.SubElement(ET.SubElement(root, "body"), "seq")
    for entry in entries:
        ET.SubElement(sequence, "media", src=_location_uri(entry.location))
    ET.indent(root, space="  ")
    return '<?wpl version="1.0"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _unique_tracks(tracks: tuple[Track, ...]) -> tuple[Track, ...]:
    return tuple({track.track_id: track for track in tracks}.values())


def _media_destinations(
    directory: HostPath,
    tracks: tuple[Track, ...],
    references: tuple[HostPath, ...],
    reserved_names: set[str],
) -> tuple[HostPath, ...]:
    destinations: list[HostPath] = []
    for track, reference in zip(tracks, references, strict=True):
        suffix = Path(os.fspath(reference.path)).suffix
        fallback = Path(os.fspath(reference.path)).stem or f"Track {track.track_id}"
        stem = _safe_stem(
            " - ".join(value for value in (track.artist, track.title) if value),
            fallback,
        )
        destinations.append(_available_child(directory, stem, suffix, reserved_names))
    return tuple(destinations)


def _unique_photos(photos: tuple[Photo, ...]) -> tuple[Photo, ...]:
    return tuple({photo.photo_id: photo for photo in photos}.values())


def _photo_format_ids(photo: Photo) -> tuple[int, ...]:
    return tuple(
        dict.fromkeys(
            representation.format_id
            for representation in photo.representations
            if representation.kind is PhotoRepresentationKind.THUMBNAIL
            and representation.format_id > 0
        )
    )


def _photo_directory_stem(photo: Photo, reference: HostPath | None) -> str:
    source_stem = Path(os.fspath(reference.path)).stem if reference is not None else ""
    return _safe_stem(source_stem, f"Photo {photo.photo_id}")


def _report_photo_progress(
    progress: Callable[[ExportProgress], None] | None,
    completed: int,
    total: int,
    destination: HostPath,
) -> None:
    if progress is not None:
        progress(
            ExportProgress(
                completed,
                total,
                f"Exporting {destination.path.name}",
            )
        )


def _create_available_directory(parent: HostPath, name: str) -> HostPath:
    parent_path = Path(os.fspath(parent))
    if not parent_path.is_dir():
        raise ValueError(
            f"The Host destination directory does not exist: {parent_path}"
        )
    number = 0
    while True:
        numbered = name if number == 0 else f"{name} ({number})"
        candidate = parent_path / numbered
        try:
            candidate.mkdir()
        except FileExistsError:
            number += 1
            continue
        return HostPath(candidate)


def _available_child(
    directory: HostPath,
    stem: str,
    suffix: str,
    reserved_names: set[str],
) -> HostPath:
    parent = Path(os.fspath(directory))
    number = 0
    while True:
        numbered = stem if number == 0 else f"{stem} ({number})"
        candidate = parent / f"{numbered}{suffix}"
        key = candidate.name.casefold()
        if key not in reserved_names and not AtomicHostFile(candidate).exists():
            reserved_names.add(key)
            return HostPath(candidate)
        number += 1


def _safe_stem(value: str, fallback: str) -> str:
    stem = _INVALID_FILENAME.sub("_", _single_line(value)).strip(" .")
    stem = stem or _INVALID_FILENAME.sub("_", fallback).strip(" .") or "Track"
    if stem.casefold() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return stem[:160].rstrip(" .") or "Track"


def _display_name(track: Track) -> str:
    title = _single_line(track.title) or "Unknown Title"
    artist = _single_line(track.artist or track.album_artist)
    return f"{artist} - {title}" if artist else title


def _single_line(value: str) -> str:
    return " ".join(_INVALID_TEXT_CONTROL.sub(" ", value).splitlines()).strip()


def _location_uri(location: str) -> str:
    path = Path(location)
    if path.is_absolute():
        return path.as_uri()
    portable = PurePosixPath(*path.parts).as_posix()
    return quote(portable, safe="/")


def _checkpoint(checkpoint: Callable[[], None] | None) -> None:
    if checkpoint is not None:
        checkpoint()


__all__ = [
    "ExportCancelledError",
    "ExportProgress",
    "ExportResult",
    "ExportTagger",
    "LibraryExporter",
    "PhotoExportEncoder",
    "PhotoExportResult",
    "PhotoExportSource",
    "PhotoExporter",
    "PillowPhotoExportEncoder",
    "PlaylistExportMode",
    "PlaylistFileType",
    "TrackExportSource",
    "serialize_playlist",
]
