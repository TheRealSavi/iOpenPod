from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from mutagen.id3 import ID3
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image

import iopenpod.device.virtual as virtual_device_module
import iopenpod.sync.rockbox_metadata as rockbox_metadata_module
from iopenpod.device.virtual import create_virtual_ipod
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.sync.rockbox_metadata import (
    RockboxArtwork,
    write_rockbox_metadata_library,
    write_rockbox_track_metadata,
)

_SILENT_M4A = base64.b64decode(
    "AAAAHGZ0eXBNNEEgAAACAE00QSBpc29taXNvMgAAAwNtb292AAAAbG12aGQAAAAAAAAAAAAAAAAAAAPoAAAAFAABAAABAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAACLXRyYWsAAABcdGtoZAAAAAMAAAAAAAAAAAAAAAEAAAAAAAAAFAAAAAAAAAAAAAAAAQEAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAACRlZHRzAAAAHGVsc3QAAAAAAAAAAQAAABQAAAQAAAEAAAAAAaVtZGlhAAAAIG1kaGQAAAAAAAAAAAAAAAAAAB9AAAAEoFXEAAAAAAAtaGRscgAAAAAAAAAAc291bgAAAAAAAAAAAAAAAFNvdW5kSGFuZGxlcgAAAAFQbWluZgAAABBzbWhkAAAAAAAAAAAAAAAkZGluZgAAABxkcmVmAAAAAAAAAAEAAAAMdXJsIAAAAAEAAAEUc3RibAAAAGpzdHNkAAAAAAAAAAEAAABabXA0YQAAAAAAAAABAAAAAAAAAAAAAQAQAAAAAB9AAAAAAAA2ZXNkcwAAAAADgICAJQABAASAgIAXQBUAAAAAAB9AAAAFRwWAgIAFFYhW5QAGgICAAQIAAAAgc3R0cwAAAAAAAAACAAAAAQAABAAAAAABAAAAoAAAABxzdHNjAAAAAAAAAAEAAAABAAAAAgAAAAEAAAAcc3RzegAAAAAAAAAAAAAAAgAAABUAAAAEAAAAFHN0Y28AAAAAAAAAAQAAAy8AAAAac2dwZAEAAAByb2xsAAAAAgAAAAH//wAAABxzYmdwAAAAAHJvbGwAAAABAAAAAgAAAAEAAABidWR0YQAAAFptZXRhAAAAAAAAACFoZGxyAAAAAAAAAABtZGlyYXBwbAAAAAAAAAAAAAAAAC1pbHN0AAAAJal0b28AAAAdZGF0YQAAAAEAAAAATGF2ZjYyLjEzLjEwMQAAAAhmcmVlAAAAIW1kYXTeAgBMYXZjNjIuMjkuMTAwAAIwQA4BGCAH"
)


def _jpeg_artwork() -> RockboxArtwork:
    output = io.BytesIO()
    Image.new("RGB", (640, 360), (20, 80, 160)).save(
        output,
        format="JPEG",
        quality=95,
        progressive=True,
    )
    return RockboxArtwork(output.getvalue(), "image/jpeg")


def _track(location: str, *, title: str = "Final title") -> TrackInfo:
    return TrackInfo(
        title=title,
        location=location,
        artist="Final artist",
        album="Final album",
        album_artist="Final album artist",
        genre="Rock",
        composer="Final composer",
        comment="Final comment",
        grouping="Final grouping",
        year=2026,
        track_number=3,
        total_tracks=12,
        disc_number=2,
        total_discs=3,
        bpm=124,
        compilation_flag=True,
        lyrics="Final lyrics",
        sort_name="Title, Final",
        sort_artist="Artist, Final",
        sort_album="Album, Final",
        sort_album_artist="Album Artist, Final",
        sort_composer="Composer, Final",
        db_track_id=123,
    )


def _create_metadata_test_ipod(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(
        virtual_device_module,
        "ensure_virtual_itunes_database",
        lambda _root: None,
    )
    create_virtual_ipod(root, "MC297")


def test_mp3_writer_materializes_database_metadata_and_rockbox_jpeg(
    tmp_path: Path,
) -> None:
    media_path = tmp_path / "track.mp3"
    media_path.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 256)

    result = write_rockbox_track_metadata(
        media_path,
        _track(":iPod_Control:Music:F00:track.mp3"),
        artwork=_jpeg_artwork(),
    )

    tags = ID3(media_path, translate=False)
    assert result.file_size == media_path.stat().st_size
    assert tags.version[:2] == (2, 3)
    assert str(tags["TIT2"]) == "Final title"
    assert str(tags["TPE1"]) == "Final artist"
    assert str(tags["TALB"]) == "Final album"
    assert str(tags["TPE2"]) == "Final album artist"
    assert str(tags["TRCK"]) == "3/12"
    assert str(tags["TPOS"]) == "2/3"
    assert str(tags["TCMP"]) == "1"
    assert str(tags["USLT::eng"]) == "Final lyrics"
    cover = tags.getall("APIC")[0]
    assert cover.mime == "image/jpeg"
    with Image.open(io.BytesIO(cover.data)) as image:
        assert image.width <= 500
        assert image.height <= 500
        assert image.info.get("progressive") is None


@pytest.mark.parametrize("suffix", [".m4a", ".mov"])
def test_mp4_writer_uses_native_atoms_and_replaces_stale_cover(
    tmp_path: Path,
    suffix: str,
) -> None:
    media_path = tmp_path / f"track{suffix}"
    media_path.write_bytes(_SILENT_M4A)
    original = MP4(media_path)
    original["\xa9nam"] = ["Stale title"]
    original["covr"] = [MP4Cover(b"stale", imageformat=MP4Cover.FORMAT_JPEG)]
    original.save()

    write_rockbox_track_metadata(
        media_path,
        _track(f":iPod_Control:Music:F00:track{suffix}"),
        artwork=_jpeg_artwork(),
    )

    tagged = MP4(media_path)
    assert tagged["\xa9nam"] == ["Final title"]
    assert tagged["\xa9ART"] == ["Final artist"]
    assert tagged["aART"] == ["Final album artist"]
    assert tagged["trkn"] == [(3, 12)]
    assert tagged["disk"] == [(2, 3)]
    assert tagged["cpil"] is True
    assert bytes(tagged["covr"][0]) != b"stale"
    assert tagged["covr"][0].imageformat == MP4Cover.FORMAT_JPEG


def test_library_pass_visits_every_safe_track_and_updates_database_sizes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    first = tmp_path / "iPod_Control" / "Music" / "F00" / "first.mp3"
    second = tmp_path / "iPod_Control" / "Music" / "F01" / "second.mp3"
    first.parent.mkdir(parents=True, exist_ok=True)
    second.parent.mkdir(parents=True, exist_ok=True)
    first.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    second.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    tracks = [
        _track(":iPod_Control:Music:F00:first.mp3", title="First"),
        _track(":iPod_Control:Music:F01:second.mp3", title="Second"),
    ]

    result = write_rockbox_metadata_library(tmp_path, tracks)

    assert result.updated == 2
    assert result.failures == ()
    assert str(ID3(first)["TIT2"]) == "First"
    assert str(ID3(second)["TIT2"]) == "Second"
    assert tracks[0].size == first.stat().st_size
    assert tracks[1].size == second.stat().st_size


def test_library_pass_can_defer_per_track_durability_and_revalidation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    first = tmp_path / "iPod_Control" / "Music" / "F00" / "first.mp3"
    second = tmp_path / "iPod_Control" / "Music" / "F01" / "second.mp3"
    first.parent.mkdir(parents=True, exist_ok=True)
    second.parent.mkdir(parents=True, exist_ok=True)
    first.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    second.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    tracks = [
        _track(":iPod_Control:Music:F00:first.mp3", title="First"),
        _track(":iPod_Control:Music:F01:second.mp3", title="Second"),
    ]
    revalidations: list[None] = []
    flushes: list[None] = []
    disk_usage_calls: list[None] = []
    free_space = rockbox_metadata_module.shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        rockbox_metadata_module,
        "flush_written_file",
        lambda _file: flushes.append(None),
    )
    monkeypatch.setattr(
        rockbox_metadata_module.shutil,
        "disk_usage",
        lambda _path: (disk_usage_calls.append(None) or free_space),
    )

    result = write_rockbox_metadata_library(
        tmp_path,
        tracks,
        before_device_mutation=lambda: revalidations.append(None),
        defer_durability=True,
        revalidate_interval_seconds=60,
    )

    assert result.updated == 2
    assert revalidations == [None]
    assert flushes == []
    assert disk_usage_calls == [None]


def test_library_pass_rejects_a_database_path_outside_ipod_music(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"untouched")
    track = _track(":outside.mp3")

    result = write_rockbox_metadata_library(tmp_path, [track])

    assert result.updated == 0
    assert len(result.failures) == 1
    assert "unsafe" in result.failures[0].message.lower()
    assert outside.read_bytes() == b"untouched"
