from __future__ import annotations

import struct
from pathlib import Path

import iopenpod.sync.pc_library as pc_library_module
from iopenpod.sync.pc_library import PCLibrary, PCTrack


def _write_minimal_mp4_with_duration(
    path: Path,
    *,
    timescale: int,
    duration: int,
) -> None:
    mvhd_payload = (
        b"\0\0\0\0"
        + struct.pack(">IIII", 0, 0, timescale, duration)
        + (b"\0" * 80)
    )
    mvhd = struct.pack(">I4s", 8 + len(mvhd_payload), b"mvhd") + mvhd_payload
    moov = struct.pack(">I4s", 8 + len(mvhd), b"moov") + mvhd
    ftyp = struct.pack(">I4s", 16, b"ftyp") + b"mp42\0\0\0\0"
    path.write_bytes(ftyp + moov)


def test_count_audio_files_skips_appledouble_sidecars(tmp_path):
    (tmp_path / "Album").mkdir()
    (tmp_path / "Album" / "track.mp3").write_bytes(b"audio")
    (tmp_path / "Album" / "._track.mp3").write_bytes(b"sidecar")
    (tmp_path / "Album" / "clip.m4a").write_bytes(b"audio")

    library = PCLibrary(tmp_path)

    assert library.count_audio_files(include_video=False) == 2


def test_count_audio_files_skips_macos_system_entries(tmp_path):
    album = tmp_path / "Album"
    apple_double = album / ".AppleDouble"
    apple_double.mkdir(parents=True)
    (album / "Café.m4a").write_bytes(b"audio")
    (album / ".DS_Store").write_bytes(b"metadata")
    (album / "._Café.m4a").write_bytes(b"sidecar")
    (apple_double / "Café.m4a").write_bytes(b"sidecar")

    library = PCLibrary(tmp_path)

    assert library.count_audio_files(include_video=False) == 1


def test_count_audio_files_respects_nonrecursive_folder_entry(tmp_path):
    nested = tmp_path / "Nested"
    nested.mkdir()
    (tmp_path / "top.mp3").write_bytes(b"audio")
    (nested / "deep.mp3").write_bytes(b"audio")

    library = PCLibrary([{
        "directory": str(tmp_path),
        "recurse": False,
        "media_types": ["music"],
    }])

    assert library.count_audio_files(include_video=False) == 1


def test_count_audio_files_respects_media_type_allowlist(tmp_path):
    (tmp_path / "song.mp3").write_bytes(b"audio")
    (tmp_path / "clip.mp4").write_bytes(b"video")

    video_only = PCLibrary([{
        "directory": str(tmp_path),
        "recurse": True,
        "media_types": ["video"],
    }])

    assert video_only.count_audio_files(include_video=True) == 1
    assert video_only.count_audio_files(include_video=False) == 0


def test_scan_skips_appledouble_sidecars(tmp_path, monkeypatch):
    album = tmp_path / "Album"
    album.mkdir()
    real_track = album / "track.mp3"
    sidecar = album / "._track.mp3"
    real_track.write_bytes(b"audio")
    sidecar.write_bytes(b"sidecar")

    monkeypatch.setattr(pc_library_module, "MUTAGEN_AVAILABLE", True)

    def fake_read_track(self, file_path: Path, library_root: Path | None = None):
        return PCTrack(
            path=str(file_path),
            relative_path=file_path.name,
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            mtime=file_path.stat().st_mtime,
            size=file_path.stat().st_size,
            title=file_path.stem,
            artist="Artist",
            album="Album",
            duration_ms=1000,
            album_artist=None,
            genre=None,
            year=None,
            track_number=None,
            track_total=None,
            disc_number=None,
            disc_total=None,
            bitrate=None,
            sample_rate=None,
            rating=None,
            needs_transcoding=False,
        )

    monkeypatch.setattr(PCLibrary, "_read_track", fake_read_track)

    tracks = list(PCLibrary(tmp_path).scan(include_video=False))

    assert [track.filename for track in tracks] == ["track.mp3"]


def test_scan_skips_macos_system_entries_and_keeps_unicode_names(tmp_path, monkeypatch):
    album = tmp_path / "Album"
    apple_double = album / ".AppleDouble"
    apple_double.mkdir(parents=True)
    real_track = album / "Café.m4a"
    real_track.write_bytes(b"audio")
    (album / ".DS_Store").write_bytes(b"metadata")
    (album / "._Café.m4a").write_bytes(b"sidecar")
    (apple_double / "Café.m4a").write_bytes(b"sidecar")

    monkeypatch.setattr(pc_library_module, "MUTAGEN_AVAILABLE", True)

    def fake_read_track(self, file_path: Path, library_root: Path | None = None):
        return PCTrack(
            path=str(file_path),
            relative_path=file_path.name,
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            mtime=file_path.stat().st_mtime,
            size=file_path.stat().st_size,
            title=file_path.stem,
            artist="Artist",
            album="Album",
            duration_ms=1000,
            album_artist=None,
            genre=None,
            year=None,
            track_number=None,
            track_total=None,
            disc_number=None,
            disc_total=None,
            bitrate=None,
            sample_rate=None,
            rating=None,
            needs_transcoding=False,
        )

    monkeypatch.setattr(PCLibrary, "_read_track", fake_read_track)

    tracks = list(PCLibrary(tmp_path).scan(include_video=False))

    assert [track.filename for track in tracks] == ["Café.m4a"]


def test_scan_accepts_multiple_library_roots(tmp_path, monkeypatch):
    root_a = tmp_path / "Music"
    root_b = tmp_path / "Audiobooks"
    (root_a / "Album").mkdir(parents=True)
    (root_b / "Book").mkdir(parents=True)
    track_a = root_a / "Album" / "song.mp3"
    track_b = root_b / "Book" / "chapter.m4b"
    track_a.write_bytes(b"audio")
    track_b.write_bytes(b"audio")

    monkeypatch.setattr(pc_library_module, "MUTAGEN_AVAILABLE", True)
    monkeypatch.setattr(PCLibrary, "_extract_metadata", lambda self, audio, ext, file_path=None: {})
    monkeypatch.setattr(PCLibrary, "_compute_art_hash", lambda self, file_path: None)

    library = PCLibrary([root_a, root_b])
    tracks = list(library.scan(include_video=False))

    assert library.count_audio_files(include_video=False) == 2
    assert {track.relative_path for track in tracks} == {
        str(Path("Album") / "song.mp3"),
        str(Path("Book") / "chapter.m4b"),
    }


def test_scan_marks_audible_containers_as_audiobooks(tmp_path, monkeypatch):
    book = tmp_path / "book.aax"
    book.write_bytes(b"audio")

    monkeypatch.setattr(pc_library_module, "MUTAGEN_AVAILABLE", True)
    monkeypatch.setattr(PCLibrary, "_extract_metadata", lambda self, audio, ext, file_path=None: {})
    monkeypatch.setattr(PCLibrary, "_compute_art_hash", lambda self, file_path: None)

    tracks = list(PCLibrary(tmp_path).scan(include_video=False))

    assert len(tracks) == 1
    assert tracks[0].is_audiobook is True


def test_scan_deduplicates_overlapping_library_roots(tmp_path, monkeypatch):
    album = tmp_path / "Music" / "Album"
    album.mkdir(parents=True)
    track = album / "song.mp3"
    track.write_bytes(b"audio")

    monkeypatch.setattr(pc_library_module, "MUTAGEN_AVAILABLE", True)
    monkeypatch.setattr(PCLibrary, "_read_track", lambda self, file_path, library_root=None: PCTrack(
        path=str(file_path),
        relative_path=file_path.name,
        filename=file_path.name,
        extension=file_path.suffix.lower(),
        mtime=file_path.stat().st_mtime,
        size=file_path.stat().st_size,
        title=file_path.stem,
        artist="Artist",
        album="Album",
        duration_ms=1000,
        album_artist=None,
        genre=None,
        year=None,
        track_number=None,
        track_total=None,
        disc_number=None,
        disc_total=None,
        bitrate=None,
        sample_rate=None,
        rating=None,
        needs_transcoding=False,
    ))

    library = PCLibrary([tmp_path / "Music", album])

    assert library.count_audio_files(include_video=False) == 1
    assert [track.filename for track in library.scan(include_video=False)] == ["song.mp3"]


def test_metadata_text_falls_back_for_none_and_blank_values() -> None:
    assert pc_library_module.PCLibrary._metadata_text({"title": None}, "title", "fallback") == "fallback"
    assert pc_library_module.PCLibrary._metadata_text({"title": "   "}, "title", "fallback") == "fallback"
    assert pc_library_module.PCLibrary._metadata_text({"title": " Song "}, "title", "fallback") == "Song"


def test_video_scan_never_extracts_artwork_or_decodes_thumbnail(
    tmp_path,
    monkeypatch,
) -> None:
    from iopenpod.artworkdb_writer import art_extractor
    from iopenpod.podcasts import downloader
    from iopenpod.sync import transcoder

    video = tmp_path / "recording.mp4"
    video.write_bytes(b"video")
    scan_calls: list[str] = []

    class RecordingMutagen:
        @staticmethod
        def File(_path):
            scan_calls.append("mutagen")
            return None

    monkeypatch.setattr(pc_library_module, "mutagen", RecordingMutagen())
    monkeypatch.setattr(
        PCLibrary,
        "_extract_metadata",
        lambda self, audio, ext, file_path=None: scan_calls.append("metadata") or {},
    )
    monkeypatch.setattr(
        art_extractor,
        "extract_art_with_folder",
        lambda _path: scan_calls.append("artwork") or None,
    )
    monkeypatch.setattr(
        downloader,
        "extract_chapters",
        lambda _path: scan_calls.append("chapters") or None,
    )
    monkeypatch.setattr(
        transcoder,
        "probe_video_needs_transcode",
        lambda _path: scan_calls.append("codec-probe") or True,
    )

    track = PCLibrary(tmp_path)._read_track(video, library_root=tmp_path)

    assert track is not None
    assert track.is_video is True
    assert scan_calls == []


def test_video_scan_reads_mp4_duration_without_external_probe(
    tmp_path,
    monkeypatch,
) -> None:
    video = tmp_path / "recording.mp4"
    _write_minimal_mp4_with_duration(video, timescale=1_000, duration=90_250)

    def unexpected_process(*_args, **_kwargs):
        raise AssertionError("video duration launched an external process")

    monkeypatch.setattr(pc_library_module.subprocess, "run", unexpected_process)
    monkeypatch.setattr(pc_library_module.subprocess, "check_output", unexpected_process)

    track = PCLibrary(tmp_path)._read_track(video, library_root=tmp_path)

    assert track is not None
    assert track.duration_ms == 90_250
