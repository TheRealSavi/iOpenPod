"""Playlist formats and create-only Host media exports."""

import os
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from iOpenPod.app.display_text import SourceText
from iOpenPod.app.library_export import (
    ExportProgress,
    LibraryExporter,
    PhotoExporter,
    PlaylistExportMode,
    PlaylistFileType,
)
from iOpenPod.app.models.photos import PhotoImage
from iPodDB.library import (
    Photo,
    PhotoRepresentation,
    PhotoRepresentationKind,
    Track,
)
from storage import CopyResult, FileFingerprint, HostPath


class _Source:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.copied: list[tuple[int, Path]] = []

    def reference_for_track(self, track: Track) -> HostPath:
        return HostPath(self.root / f"F00/T{track.track_id}.mp3")

    def copy_track_to_host(
        self,
        track: Track,
        destination: HostPath,
        *,
        prepare_staged: Callable[[HostPath], None] | None = None,
    ) -> CopyResult:
        path = Path(os.fspath(destination))
        path.write_bytes(f"audio-{track.track_id}".encode())
        if prepare_staged is not None:
            prepare_staged(destination)
        self.copied.append((track.track_id, path))
        content_hash = str(track.track_id).zfill(64)
        return CopyResult(
            path.stat().st_size,
            content_hash,
            FileFingerprint(path.stat().st_size, 0, 0, 0, content_hash),
        )

    def artwork_for_track(self, track: Track) -> None:
        del track


class _Tagger:
    def __init__(self) -> None:
        self.prepared: list[tuple[Path, int, Any]] = []

    def require_supported(self, destination: HostPath) -> None:
        del destination
        return

    def prepare(self, destination: HostPath, track: Track, artwork: Any) -> None:
        self.prepared.append((Path(os.fspath(destination)), track.track_id, artwork))


def _exporter(source: _Source) -> LibraryExporter:
    return LibraryExporter(source, _Tagger())


_ONE = Track(1, "First / Song", "An Artist", "Album", 61_500, track_number=1)
_TWO = Track(2, "First / Song", "An Artist", "Album", 122_000, track_number=2)


@pytest.mark.parametrize("file_type", tuple(PlaylistFileType))
def test_reference_playlist_formats_preserve_occurrences_and_device_paths(
    tmp_path: Path, file_type: PlaylistFileType
) -> None:
    source = _Source(tmp_path / "iPod")
    output = tmp_path / file_type.value
    output.mkdir()

    result = _exporter(source).export_playlist(
        "Road Trip",
        (_ONE, _TWO, _ONE),
        HostPath(output),
        file_type,
        PlaylistExportMode.DEVICE_REFERENCES,
    )

    assert result.track_files == ()
    playlist_file = result.playlist_file
    if playlist_file is None:
        raise AssertionError("A Playlist export must return its output path")
    assert playlist_file == HostPath(output / f"Road Trip.{file_type.value}")
    assert source.copied == []
    content = Path(os.fspath(playlist_file)).read_text(encoding="utf-8")
    first_path = os.fspath(source.reference_for_track(_ONE).path)
    if file_type in (PlaylistFileType.M3U, PlaylistFileType.M3U8):
        assert content.startswith("#EXTM3U\n")
        assert content.count(first_path) == 2
        assert "#EXTINF:61,An Artist - First / Song" in content
    elif file_type is PlaylistFileType.PLS:
        assert "NumberOfEntries=3" in content
        assert f"File1={first_path}" in content
        assert f"File3={first_path}" in content
    else:
        root = ET.fromstring(content)
        elements = (
            root.findall(".//{*}track")
            if file_type is PlaylistFileType.XSPF
            else root.findall(".//{*}media")
        )
        assert len(elements) == 3


def test_copying_a_playlist_exports_each_track_once_and_uses_relative_paths(
    tmp_path: Path,
) -> None:
    source = _Source(tmp_path / "iPod")
    progress: list[ExportProgress] = []

    result = _exporter(source).export_playlist(
        "Road: Trip",
        (_ONE, _TWO, _ONE),
        HostPath(tmp_path),
        PlaylistFileType.M3U8,
        PlaylistExportMode.COPY_TRACKS,
        progress=progress.append,
    )

    playlist_file = result.playlist_file
    if playlist_file is None:
        raise AssertionError("A Playlist export must return its output path")
    assert playlist_file == HostPath(tmp_path / "Road_ Trip.m3u8")
    assert [path.path.name for path in result.track_files] == [
        "An Artist - First _ Song.mp3",
        "An Artist - First _ Song (1).mp3",
    ]
    assert [track_id for track_id, _path in source.copied] == [1, 2]
    content = Path(os.fspath(playlist_file)).read_text(encoding="utf-8")
    assert content.count("An Artist - First _ Song.mp3") == 2
    assert content.count("An Artist - First _ Song (1).mp3") == 1
    assert str(tmp_path) not in content
    message = progress[0].message
    assert isinstance(message, SourceText)
    assert message.source == "Exporting {name}"
    assert dict(message.parameters) == {"name": "An Artist - First _ Song.mp3"}
    assert isinstance(progress[-1].message, SourceText)
    assert progress[-1].message.source == "Created {name}"


def test_existing_playlist_gets_the_next_number_without_replacing_the_original(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "Road Trip.m3u8"
    existing.write_text("keep me", encoding="utf-8")
    source = _Source(tmp_path / "iPod")

    result = _exporter(source).export_playlist(
        "Road Trip",
        (_ONE,),
        HostPath(tmp_path),
        PlaylistFileType.M3U8,
        PlaylistExportMode.COPY_TRACKS,
    )

    assert existing.read_text(encoding="utf-8") == "keep me"
    assert result.playlist_file == HostPath(tmp_path / "Road Trip (1).m3u8")
    assert [track_id for track_id, _path in source.copied] == [1]


def test_track_export_copies_selected_tracks_without_creating_a_playlist(
    tmp_path: Path,
) -> None:
    source = _Source(tmp_path / "iPod")

    result = _exporter(source).export_tracks((_TWO, _ONE, _TWO), HostPath(tmp_path))

    assert result.playlist_file is None
    assert [track_id for track_id, _path in source.copied] == [2, 1]
    assert len(result.track_files) == 2
    assert all(Path(os.fspath(path)).is_file() for path in result.track_files)


def test_track_export_uses_the_next_number_without_replacing_existing_files(
    tmp_path: Path,
) -> None:
    original = tmp_path / "An Artist - First _ Song.mp3"
    numbered = tmp_path / "An Artist - First _ Song (1).mp3"
    original.write_bytes(b"keep original")
    numbered.write_bytes(b"keep numbered")

    result = _exporter(_Source(tmp_path / "iPod")).export_tracks(
        (_ONE,), HostPath(tmp_path)
    )

    assert result.track_files == (
        HostPath(tmp_path / "An Artist - First _ Song (2).mp3"),
    )
    assert original.read_bytes() == b"keep original"
    assert numbered.read_bytes() == b"keep numbered"


class _PhotoSource:
    def __init__(
        self,
        references: dict[int, Path | None],
        images: dict[tuple[int, int], PhotoImage] | None = None,
    ) -> None:
        self.references = references
        self.images = images or {}
        self.copied: list[tuple[int, Path]] = []
        self.requested_formats: list[tuple[int, int]] = []

    def require_photo_export_directory(self, directory: HostPath) -> None:
        assert Path(os.fspath(directory)).is_dir()

    def reference_for_photo(self, photo: Photo) -> HostPath | None:
        reference = self.references[photo.photo_id]
        return HostPath(reference) if reference is not None else None

    def copy_photo_to_host(
        self,
        photo: Photo,
        destination: HostPath,
        *,
        source: HostPath,
    ) -> CopyResult:
        reference = self.references[photo.photo_id]
        if reference is None:
            raise AssertionError("A fallback Photo must not request a file copy")
        assert source == HostPath(reference)
        path = Path(os.fspath(destination))
        shutil.copyfile(reference, path)
        self.copied.append((photo.photo_id, path))
        content_hash = str(photo.photo_id).zfill(64)
        return CopyResult(
            path.stat().st_size,
            content_hash,
            FileFingerprint(path.stat().st_size, 0, 0, 0, content_hash),
        )

    def image_for_photo_export(
        self,
        photo: Photo,
        *,
        format_id: int,
    ) -> PhotoImage | None:
        self.requested_formats.append((photo.photo_id, format_id))
        return self.images.get((photo.photo_id, format_id))


def _photo(photo_id: int, *format_ids: int) -> Photo:
    return Photo(
        photo_id,
        representations=tuple(
            PhotoRepresentation(
                PhotoRepresentationKind.THUMBNAIL,
                format_id,
                f"Photos/Thumbs/F{format_id}_1.ithmb",
                0,
                2,
                1,
                1,
            )
            for format_id in format_ids
        ),
    )


def _image(photo_id: int, format_id: int, color: bytes) -> PhotoImage:
    return PhotoImage(
        f"photo:{photo_id}:{format_id}",
        photo_id,
        format_id,
        1,
        1,
        color,
    )


def test_photo_export_creates_one_folder_per_photo_with_every_rendition(
    tmp_path: Path,
) -> None:
    first = tmp_path / "device-a" / "Beach.JPG"
    second = tmp_path / "device-b" / "Beach.JPG"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"first original")
    second.write_bytes(b"second original")
    output = tmp_path / "output"
    output.mkdir()
    existing = output / "Beach"
    existing.mkdir()
    existing.joinpath("keep.txt").write_text("keep me", encoding="utf-8")
    photos = (_photo(101, 1032, 1023), _photo(102, 1032))
    source = _PhotoSource(
        {101: first, 102: second},
        {
            (101, 1032): _image(101, 1032, bytes((255, 0, 0))),
            (101, 1023): _image(101, 1023, bytes((0, 255, 0))),
            (102, 1032): _image(102, 1032, bytes((0, 0, 255))),
        },
    )

    result = PhotoExporter(source).export_photos(
        (*photos, photos[0]),
        HostPath(output),
    )

    assert result.album_directory is None
    assert result.photo_directories == (
        HostPath(output / "Beach (1)"),
        HostPath(output / "Beach (2)"),
    )
    assert tuple(
        path.path.relative_to(output).as_posix() for path in result.photo_files
    ) == (
        "Beach (1)/Beach.JPG",
        "Beach (1)/iTHMB 1032 - 1x1.jpg",
        "Beach (1)/iTHMB 1023 - 1x1.jpg",
        "Beach (2)/Beach.JPG",
        "Beach (2)/iTHMB 1032 - 1x1.jpg",
    )
    assert existing.joinpath("keep.txt").read_text(encoding="utf-8") == "keep me"
    assert (output / "Beach (1)" / "Beach.JPG").read_bytes() == b"first original"
    assert (output / "Beach (2)" / "Beach.JPG").read_bytes() == b"second original"
    assert source.requested_formats == [(101, 1032), (101, 1023), (102, 1032)]


def test_photo_export_encodes_every_ithmb_format_without_a_full_resolution_file(
    tmp_path: Path,
) -> None:
    from PIL import Image

    output = tmp_path / "output"
    output.mkdir()
    photo = _photo(102, 1032, 1023)
    source = _PhotoSource(
        {102: None},
        {
            (102, 1032): _image(102, 1032, bytes((255, 0, 0))),
            (102, 1023): _image(102, 1023, bytes((0, 255, 0))),
        },
    )

    result = PhotoExporter(source).export_photos((photo,), HostPath(output))

    photo_directory = HostPath(output / "Photo 102")
    assert result.photo_directories == (photo_directory,)
    assert result.photo_files == (
        HostPath(output / "Photo 102" / "iTHMB 1032 - 1x1.jpg"),
        HostPath(output / "Photo 102" / "iTHMB 1023 - 1x1.jpg"),
    )
    for exported_path in result.photo_files:
        with Image.open(Path(os.fspath(exported_path))) as exported:
            assert exported.format == "JPEG"
            assert exported.mode == "RGB"
            assert exported.size == (1, 1)


def test_photo_export_fails_instead_of_omitting_an_unreadable_ithmb_format(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    photo = _photo(102, 1032, 1023)
    source = _PhotoSource(
        {102: None},
        {(102, 1032): _image(102, 1032, bytes((255, 0, 0)))},
    )

    with pytest.raises(ValueError, match="iTHMB format 1023"):
        PhotoExporter(source).export_photos((photo,), HostPath(output))

    assert (output / "Photo 102" / "iTHMB 1032 - 1x1.jpg").is_file()
    assert source.requested_formats == [(102, 1032), (102, 1023)]


def test_photo_album_export_creates_a_unique_named_host_directory(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "device" / "Sunset.png"
    source_file.parent.mkdir()
    source_file.write_bytes(b"png bytes")
    export_parent = tmp_path / "exports"
    export_parent.mkdir()
    retained = export_parent / "Road_ Trip"
    retained.mkdir()
    retained.joinpath("keep.txt").write_text("keep", encoding="utf-8")
    photo = _photo(101, 1032)
    source = _PhotoSource(
        {101: source_file},
        {(101, 1032): _image(101, 1032, bytes((255, 0, 0)))},
    )

    result = PhotoExporter(source).export_photo_album(
        "Road: Trip",
        (photo,),
        HostPath(export_parent),
    )

    assert result.album_directory == HostPath(export_parent / "Road_ Trip (1)")
    assert result.photo_directories == (
        HostPath(export_parent / "Road_ Trip (1)" / "Sunset"),
    )
    assert result.photo_files == (
        HostPath(export_parent / "Road_ Trip (1)" / "Sunset" / "Sunset.png"),
        HostPath(export_parent / "Road_ Trip (1)" / "Sunset" / "iTHMB 1032 - 1x1.jpg"),
    )
    assert retained.joinpath("keep.txt").read_text(encoding="utf-8") == "keep"
    assert Path(os.fspath(result.photo_files[0])).read_bytes() == b"png bytes"
