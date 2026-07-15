from iopenpod.sync.fingerprint_diff_engine import FingerprintDiffEngine
from iopenpod.sync.mapping import TrackMapping
from iopenpod.sync.pc_library import PCTrack
from iopenpod.sync.source_identity import source_content_hash


def _track(
    *,
    title: str = "Song",
    artist: str = "Unknown Artist",
    album: str = "Unknown Album",
    album_artist: str | None = None,
    sound_check: int = 0,
    chapters: list[dict] | None = None,
    path: str = "/music/Song.mp3",
    relative_path: str = "Song.mp3",
    filename: str = "Song.mp3",
    extension: str = ".mp3",
    mtime: float = 0,
    size: int = 1,
    is_video: bool = False,
) -> PCTrack:
    return PCTrack(
        path=path,
        relative_path=relative_path,
        filename=filename,
        extension=extension,
        mtime=mtime,
        size=size,
        title=title,
        artist=artist,
        album=album,
        album_artist=album_artist,
        genre=None,
        year=None,
        track_number=None,
        track_total=None,
        disc_number=None,
        disc_total=None,
        duration_ms=1000,
        bitrate=None,
        sample_rate=None,
        rating=None,
        is_video=is_video,
        sound_check=sound_check,
        chapters=chapters,
    )


def _engine() -> FingerprintDiffEngine:
    return FingerprintDiffEngine.__new__(FingerprintDiffEngine)


def _mapping(**overrides) -> TrackMapping:
    values = {
        "db_track_id": 1,
        "source_format": "m4a",
        "ipod_format": "m4a",
        "source_size": 1000,
        "source_mtime": 1.0,
        "last_sync": "now",
        "was_transcoded": True,
    }
    values.update(overrides)
    return TrackMapping(**values)


def _box(box_type: bytes, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + box_type + payload


def _write_m4a(path, *, metadata: bytes, media: bytes) -> None:
    path.write_bytes(
        _box(b"ftyp", b"M4A \x00\x00\x00\x00")
        + _box(b"moov", metadata)
        + _box(b"mdat", media)
    )


def test_metadata_compare_does_not_demote_folder_guesses_to_scanner_defaults() -> None:
    changes = _engine()._compare_metadata(
        _track(),
        {
            "Title": "Song",
            "Artist": "Folder Artist",
            "Album": "Folder Album",
            "Album Artist": "Folder Artist",
        },
    )

    assert changes == {}


def test_metadata_compare_does_not_demote_sound_check_to_absent_zero() -> None:
    changes = _engine()._compare_metadata(
        _track(sound_check=0),
        {
            "Title": "Song",
            "Artist": "Unknown Artist",
            "Album": "Unknown Album",
            "sound_check": 123456,
        },
    )

    assert "sound_check" not in changes


def test_metadata_compare_keeps_real_pc_metadata_authoritative() -> None:
    changes = _engine()._compare_metadata(
        _track(
            artist="Real Artist",
            album="Real Album",
            album_artist="Real Album Artist",
            sound_check=987654,
        ),
        {
            "Title": "Song",
            "Artist": "Folder Artist",
            "Album": "Folder Album",
            "Album Artist": "Folder Artist",
            "sound_check": 123456,
        },
    )

    assert changes["artist"] == ("Real Artist", "Folder Artist")
    assert changes["album"] == ("Real Album", "Folder Album")
    assert changes["album_artist"] == ("Real Album Artist", "Folder Artist")
    assert changes["sound_check"] == (987654, 123456)


def test_metadata_compare_repairs_missing_video_duration() -> None:
    changes = _engine()._compare_metadata(
        _track(
            path="/video/movie.mp4",
            relative_path="movie.mp4",
            filename="movie.mp4",
            extension=".mp4",
            is_video=True,
        ),
        {
            "Title": "Song",
            "Artist": "Unknown Artist",
            "Album": "Unknown Album",
            "length": 0,
        },
    )

    assert changes["duration_ms"] == (1000, 0)


def test_metadata_compare_syncs_pc_chapters_for_any_filetype() -> None:
    chapters = [{"startpos": 0, "title": "Intro"}]

    changes = _engine()._compare_metadata(
        _track(chapters=chapters),
        {
            "Title": "Song",
            "Artist": "Unknown Artist",
            "Album": "Unknown Album",
            "filetype": "MPEG audio file",
        },
    )

    assert changes["chapter_data"] == (
        {"chapters": chapters},
        {"chapters": []},
    )


def test_metadata_compare_does_not_remove_ipod_chapters_when_pc_has_none() -> None:
    changes = _engine()._compare_metadata(
        _track(),
        {
            "Title": "Song",
            "Artist": "Unknown Artist",
            "Album": "Unknown Album",
            "chapter_data": {"chapters": [{"startpos": 0, "title": "Intro"}]},
        },
    )

    assert "chapter_data" not in changes


def test_source_file_changed_ignores_m4a_container_churn_without_stored_hash() -> None:
    pc_track = _track(
        path="/music/Song.m4a",
        relative_path="Song.m4a",
        filename="Song.m4a",
        extension=".m4a",
        size=1500,
        mtime=2.0,
    )

    assert _engine()._source_file_changed(pc_track, _mapping()) is False


def test_source_file_changed_uses_m4a_audio_hash_when_available(tmp_path) -> None:
    before = tmp_path / "before.m4a"
    after = tmp_path / "after.m4a"
    changed = tmp_path / "changed.m4a"
    _write_m4a(before, metadata=b"before", media=b"same-audio")
    _write_m4a(after, metadata=b"after-and-larger", media=b"same-audio")
    _write_m4a(changed, metadata=b"before", media=b"different-audio")
    stored_hash = source_content_hash(before)

    unchanged_audio = _track(
        path=str(after),
        relative_path="after.m4a",
        filename="after.m4a",
        extension=".m4a",
        size=after.stat().st_size,
        mtime=2.0,
    )
    changed_audio = _track(
        path=str(changed),
        relative_path="changed.m4a",
        filename="changed.m4a",
        extension=".m4a",
        size=changed.stat().st_size,
        mtime=2.0,
    )

    assert _engine()._source_file_changed(
        unchanged_audio,
        _mapping(source_size=before.stat().st_size, source_hash=stored_hash),
    ) is False
    assert _engine()._source_file_changed(
        changed_audio,
        _mapping(source_size=before.stat().st_size, source_hash=stored_hash),
    ) is True


def test_source_file_changed_keeps_size_gate_for_non_mp4_sources() -> None:
    pc_track = _track(
        path="/music/Song.flac",
        relative_path="Song.flac",
        filename="Song.flac",
        extension=".flac",
        size=20_000,
        mtime=2.0,
    )

    assert _engine()._source_file_changed(
        pc_track,
        _mapping(source_format="flac", source_size=1_000),
    ) is True
