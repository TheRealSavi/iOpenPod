from __future__ import annotations

from pathlib import Path

import SyncEngine.pc_library as pc_library_module
from SyncEngine.pc_library import PCLibrary, PCTrack


def test_count_audio_files_skips_appledouble_sidecars(tmp_path):
    (tmp_path / "Album").mkdir()
    (tmp_path / "Album" / "track.mp3").write_bytes(b"audio")
    (tmp_path / "Album" / "._track.mp3").write_bytes(b"sidecar")
    (tmp_path / "Album" / "clip.m4a").write_bytes(b"audio")

    library = PCLibrary(tmp_path)

    assert library.count_audio_files(include_video=False) == 2


def test_scan_skips_appledouble_sidecars(tmp_path, monkeypatch):
    album = tmp_path / "Album"
    album.mkdir()
    real_track = album / "track.mp3"
    sidecar = album / "._track.mp3"
    real_track.write_bytes(b"audio")
    sidecar.write_bytes(b"sidecar")

    monkeypatch.setattr(pc_library_module, "MUTAGEN_AVAILABLE", True)

    def fake_read_track(self, file_path: Path):
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


def test_scan_deduplicates_overlapping_library_roots(tmp_path, monkeypatch):
    album = tmp_path / "Music" / "Album"
    album.mkdir(parents=True)
    track = album / "song.mp3"
    track.write_bytes(b"audio")

    monkeypatch.setattr(pc_library_module, "MUTAGEN_AVAILABLE", True)
    monkeypatch.setattr(PCLibrary, "_read_track", lambda self, file_path: PCTrack(
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
