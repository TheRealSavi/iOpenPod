from __future__ import annotations

import base64
import io
import threading
from pathlib import Path

import pytest
from mutagen.id3 import ID3
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image

import iopenpod.device.virtual as virtual_device_module
import iopenpod.sync.rockbox_metadata as rockbox_metadata_module
from iopenpod.artworkdb_writer.artwork_types import ExistingFormatRef
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


def test_mp4_writer_can_preserve_prevalidated_embedded_artwork(tmp_path: Path) -> None:
    media_path = tmp_path / "track.m4a"
    media_path.write_bytes(_SILENT_M4A)
    track = _track(":iPod_Control:Music:F00:track.m4a", title="Before")
    write_rockbox_track_metadata(media_path, track, artwork=_jpeg_artwork())
    original_cover = bytes(MP4(media_path)["covr"][0])
    track.title = "After"

    write_rockbox_track_metadata(
        media_path,
        track,
        force_write=True,
        preserve_embedded_artwork=True,
    )

    tagged = MP4(media_path)
    assert tagged["\xa9nam"] == ["After"]
    assert bytes(tagged["covr"][0]) == original_cover


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


def test_library_pass_skips_unchanged_id3_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    media_path = tmp_path / "iPod_Control" / "Music" / "F00" / "track.mp3"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    track = _track(":iPod_Control:Music:F00:track.mp3")

    write_rockbox_metadata_library(tmp_path, [track], defer_durability=True)
    original_size = media_path.stat().st_size
    monkeypatch.setattr(
        rockbox_metadata_module,
        "_write_id3_metadata",
        lambda *_args: pytest.fail("unchanged ID3 metadata should not be rewritten"),
    )

    result = write_rockbox_metadata_library(tmp_path, [track], defer_durability=True)

    assert result.updated == 0
    assert result.bytes_delta == 0
    assert media_path.stat().st_size == original_size


def test_library_pass_uses_persisted_validation_marker_for_unchanged_track(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    media_path = tmp_path / "iPod_Control" / "Music" / "F00" / "track.mp3"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    track = _track(":iPod_Control:Music:F00:track.mp3")

    first = write_rockbox_metadata_library(tmp_path, [track], defer_durability=True)
    monkeypatch.setattr(
        rockbox_metadata_module,
        "_rockbox_metadata_is_current",
        lambda *_args: pytest.fail("a matching validation marker should skip tag parsing"),
    )
    monkeypatch.setattr(
        rockbox_metadata_module,
        "read_existing_artwork",
        lambda *_args: pytest.fail("a matching validation marker should skip ArtworkDB loading"),
    )

    second = write_rockbox_metadata_library(
        tmp_path,
        [track],
        defer_durability=True,
        validation_markers=first.validation_markers,
        validation_artwork_state=first.validation_artwork_state,
    )

    assert second.updated == 0
    assert second.validated_from_marker == 1


def test_validation_marker_avoids_full_path_resolution_for_safe_music_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    media_path = tmp_path / "iPod_Control" / "Music" / "F00" / "track.mp3"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    track = _track(":iPod_Control:Music:F00:track.mp3")
    first = write_rockbox_metadata_library(tmp_path, [track], defer_durability=True)
    monkeypatch.setattr(
        rockbox_metadata_module,
        "expected_ipod_track_file_path",
        lambda *_args: pytest.fail("matching marker should use its cached Music directory"),
    )

    second = write_rockbox_metadata_library(
        tmp_path,
        [track],
        defer_durability=True,
        validation_markers=first.validation_markers,
        validation_artwork_state=first.validation_artwork_state,
    )

    assert second.updated == 0
    assert second.validated_from_marker == 1


def test_validation_marker_falls_back_when_database_metadata_changes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    media_path = tmp_path / "iPod_Control" / "Music" / "F00" / "track.mp3"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    track = _track(":iPod_Control:Music:F00:track.mp3", title="Before")
    first = write_rockbox_metadata_library(tmp_path, [track], defer_durability=True)
    track.title = "After"
    full_resolutions: list[None] = []
    original_resolver = rockbox_metadata_module.expected_ipod_track_file_path
    monkeypatch.setattr(
        rockbox_metadata_module,
        "expected_ipod_track_file_path",
        lambda *args: (full_resolutions.append(None) or original_resolver(*args)),
    )

    second = write_rockbox_metadata_library(
        tmp_path,
        [track],
        defer_durability=True,
        validation_markers=first.validation_markers,
        validation_artwork_state=first.validation_artwork_state,
    )

    assert second.updated == 1
    assert second.validated_from_marker == 0
    assert full_resolutions == []
    assert str(ID3(media_path)["TIT2"]) == "After"


def test_validation_marker_never_follows_a_replaced_media_symlink(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    media_path = tmp_path / "iPod_Control" / "Music" / "F00" / "track.mp3"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    track = _track(":iPod_Control:Music:F00:track.mp3")
    first = write_rockbox_metadata_library(tmp_path, [track], defer_durability=True)
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"outside")
    media_path.unlink()
    try:
        media_path.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    second = write_rockbox_metadata_library(
        tmp_path,
        [track],
        defer_durability=True,
        validation_markers=first.validation_markers,
        validation_artwork_state=first.validation_artwork_state,
    )

    assert second.updated == 0
    assert second.validated_from_marker == 0
    assert second.failures[0].message == "Unsafe iPod media path; the file was not modified"


def test_library_pass_reuses_verified_music_folders_for_new_tracks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    media_path = tmp_path / "iPod_Control" / "Music" / "F00" / "track.mp3"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    track = _track(":iPod_Control:Music:F00:track.mp3")
    monkeypatch.setattr(
        rockbox_metadata_module,
        "expected_ipod_track_file_path",
        lambda *_args: pytest.fail("conventional Music paths should reuse their verified folder"),
    )

    result = write_rockbox_metadata_library(tmp_path, [track], defer_durability=True)

    assert result.updated == 1


def test_library_pass_forces_planned_changes_without_first_parsing_the_tag(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    media_path = tmp_path / "iPod_Control" / "Music" / "F00" / "track.mp3"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    track = _track(":iPod_Control:Music:F00:track.mp3")
    monkeypatch.setattr(
        rockbox_metadata_module,
        "_rockbox_metadata_is_current",
        lambda *_args: pytest.fail("a planned update should not parse the old tag first"),
    )

    result = write_rockbox_metadata_library(
        tmp_path,
        [track],
        defer_durability=True,
        force_write_track_ids={track.db_track_id},
    )

    assert result.updated == 1


def test_library_pass_loads_existing_artwork_only_when_a_track_needs_it(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    media_path = tmp_path / "iPod_Control" / "Music" / "F00" / "track.mp3"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    track = _track(":iPod_Control:Music:F00:track.mp3")
    monkeypatch.setattr(
        rockbox_metadata_module,
        "read_existing_artwork",
        lambda *_args: pytest.fail("source artwork should not load the whole ArtworkDB"),
    )
    monkeypatch.setattr(
        rockbox_metadata_module,
        "extract_art_with_folder",
        lambda _source_path: _jpeg_artwork().data,
    )

    result = write_rockbox_metadata_library(
        tmp_path,
        [track],
        pc_file_paths={track.db_track_id: "/host/source.mp3"},
        defer_durability=True,
    )

    assert result.updated == 1


def test_library_pass_prefetches_unique_source_artwork_in_parallel(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    tracks = [
        _track(f":iPod_Control:Music:F00:track-{index}.mp3")
        for index in range(3)
    ]
    for index, track in enumerate(tracks):
        track.db_track_id = index + 1
        media_path = tmp_path / "iPod_Control" / "Music" / "F00" / f"track-{index}.mp3"
        media_path.parent.mkdir(parents=True, exist_ok=True)
        media_path.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)

    started = threading.Barrier(3)
    worker_threads: set[int] = set()

    def extract_in_worker(_source_path: str) -> bytes:
        worker_threads.add(threading.get_ident())
        started.wait(timeout=2)
        return _jpeg_artwork().data

    monkeypatch.setattr(rockbox_metadata_module, "extract_art_with_folder", extract_in_worker)

    result = write_rockbox_metadata_library(
        tmp_path,
        tracks,
        pc_file_paths={track.db_track_id: f"/host/{track.db_track_id}.mp3" for track in tracks},
        defer_durability=True,
        force_write_track_ids={track.db_track_id for track in tracks},
    )

    assert result.updated == 3
    assert len(worker_threads) == 3


def test_planned_metadata_update_preserves_prevalidated_embedded_artwork(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    media_path = tmp_path / "iPod_Control" / "Music" / "F00" / "track.mp3"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    track = _track(":iPod_Control:Music:F00:track.mp3", title="Before")
    monkeypatch.setattr(
        rockbox_metadata_module,
        "extract_art_with_folder",
        lambda _source_path: _jpeg_artwork().data,
    )
    first = write_rockbox_metadata_library(
        tmp_path,
        [track],
        pc_file_paths={track.db_track_id: "/host/source.mp3"},
        defer_durability=True,
    )
    original_cover = ID3(media_path).getall("APIC")[0].data
    track.title = "After"
    monkeypatch.setattr(
        rockbox_metadata_module,
        "read_existing_artwork",
        lambda *_args: pytest.fail("a prevalidated cover should remain embedded"),
    )

    second = write_rockbox_metadata_library(
        tmp_path,
        [track],
        defer_durability=True,
        validation_markers=first.validation_markers,
        validation_artwork_state=first.validation_artwork_state,
        force_write_track_ids={track.db_track_id},
        preserve_embedded_artwork_track_ids={track.db_track_id},
    )

    assert second.updated == 1
    assert str(ID3(media_path)["TIT2"]) == "After"
    assert ID3(media_path).getall("APIC")[0].data == original_cover


def test_library_pass_skips_unchanged_mp4_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    media_path = tmp_path / "iPod_Control" / "Music" / "F00" / "track.m4a"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(_SILENT_M4A)
    track = _track(":iPod_Control:Music:F00:track.m4a")

    write_rockbox_metadata_library(tmp_path, [track], defer_durability=True)
    original_size = media_path.stat().st_size
    monkeypatch.setattr(
        rockbox_metadata_module,
        "_write_mp4_metadata",
        lambda *_args: pytest.fail("unchanged MP4 metadata should not be rewritten"),
    )

    result = write_rockbox_metadata_library(tmp_path, [track], defer_durability=True)

    assert result.updated == 0
    assert result.bytes_delta == 0
    assert media_path.stat().st_size == original_size


def test_library_pass_rewrites_changed_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_metadata_test_ipod(monkeypatch, tmp_path)
    media_path = tmp_path / "iPod_Control" / "Music" / "F00" / "track.mp3"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)
    track = _track(":iPod_Control:Music:F00:track.mp3", title="Before")

    write_rockbox_metadata_library(tmp_path, [track], defer_durability=True)
    track.title = "After"

    result = write_rockbox_metadata_library(tmp_path, [track], defer_durability=True)

    assert result.updated == 1
    assert str(ID3(media_path)["TIT2"]) == "After"


def test_artwork_resolver_reads_shared_existing_thumbnail_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    artwork_path = tmp_path / "F1000_1.ithmb"
    artwork_path.write_bytes(b"data")
    ref = ExistingFormatRef(
        path=str(artwork_path),
        ithmb_offset=0,
        size=4,
        width=1,
        height=1,
    )
    monkeypatch.setattr(
        rockbox_metadata_module,
        "read_existing_artwork",
        lambda *_args: {
            1: {"song_id": 1, "formats": {1000: ref}},
            2: {"song_id": 2, "formats": {1000: ref}},
        },
    )
    monkeypatch.setattr(
        rockbox_metadata_module,
        "decode_pixels_for_format",
        lambda *_args, **_kwargs: Image.new("RGB", (1, 1)),
    )
    original_open = open
    thumbnail_reads: list[None] = []

    def count_thumbnail_read(*args, **kwargs):
        if args and args[0] == str(artwork_path):
            thumbnail_reads.append(None)
        return original_open(*args, **kwargs)

    monkeypatch.setattr("builtins.open", count_thumbnail_read)
    resolver = rockbox_metadata_module._ArtworkResolver(
        tmp_path,
        {},
        device_artwork_formats={},
    )

    first_track = _track(":iPod_Control:Music:F00:first.mp3")
    first_track.db_track_id = 1
    first = resolver.for_track(first_track)
    second_track = _track(":iPod_Control:Music:F00:second.mp3")
    second_track.db_track_id = 2
    second = resolver.for_track(second_track)

    assert first == second
    assert thumbnail_reads == [None]


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
