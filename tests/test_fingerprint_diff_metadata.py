from SyncEngine.fingerprint_diff_engine import FingerprintDiffEngine
from SyncEngine.pc_library import PCTrack


def _track(
    *,
    title: str = "Song",
    artist: str = "Unknown Artist",
    album: str = "Unknown Album",
    album_artist: str | None = None,
    sound_check: int = 0,
    chapters: list[dict] | None = None,
) -> PCTrack:
    return PCTrack(
        path="/music/Song.mp3",
        relative_path="Song.mp3",
        filename="Song.mp3",
        extension=".mp3",
        mtime=0,
        size=1,
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
        sound_check=sound_check,
        chapters=chapters,
    )


def _engine() -> FingerprintDiffEngine:
    return FingerprintDiffEngine.__new__(FingerprintDiffEngine)


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
