from __future__ import annotations

from iopenpod.subsonic.mapping import IPOD_NATIVE_AUDIO, song_to_pc_track


def _song(**overrides):
    base = {
        "id": "t1",
        "title": "Song One",
        "artist": "Artist A",
        "album": "Album X",
        "suffix": "mp3",
        "duration": 200,
        "bitRate": 320,
        "size": 6_400_000,
        "track": 1,
        "discNumber": 2,
        "year": 2019,
        "genre": "Rock",
        "sampleRate": 44100,
    }
    base.update(overrides)
    return base


def test_basic_field_mapping() -> None:
    pc = song_to_pc_track(_song())
    assert pc.path == "subsonic://t1"
    assert pc.title == "Song One"
    assert pc.artist == "Artist A"
    assert pc.album == "Album X"
    assert pc.extension == ".mp3"
    assert pc.duration_ms == 200_000  # seconds -> ms
    assert pc.bitrate == 320
    assert pc.size == 6_400_000
    assert pc.year == 2019
    assert pc.genre == "Rock"
    assert pc.track_number == 1
    assert pc.disc_number == 2
    assert pc.sample_rate == 44100
    assert pc.rating is None
    assert pc.is_podcast is False
    assert pc.is_video is False


def test_path_is_virtual_subsonic_uri() -> None:
    pc = song_to_pc_track(_song(id="abc9"))
    assert pc.path == "subsonic://abc9"


def test_falls_back_to_album_fields() -> None:
    song = _song()
    song.pop("artist")
    song.pop("album")
    song.pop("genre")
    song.pop("year")
    album = {
        "artist": "Album Artist",
        "name": "Album From Album",
        "genre": "Jazz",
        "year": 2001,
        "isCompilation": True,
    }
    pc = song_to_pc_track(song, album=album)
    assert pc.artist == "Album Artist"
    assert pc.album == "Album From Album"
    assert pc.genre == "Jazz"
    assert pc.year == 2001
    assert pc.compilation is True


def test_needs_transcoding_for_non_native_formats() -> None:
    assert ".flac" not in IPOD_NATIVE_AUDIO
    pc = song_to_pc_track(_song(suffix="flac"))
    assert pc.needs_transcoding is True


def test_native_format_not_flagged_for_transcode() -> None:
    pc = song_to_pc_track(_song(suffix="m4a"))
    assert pc.needs_transcoding is False


def test_unknown_artist_and_title_defaults() -> None:
    pc = song_to_pc_track({"id": "x", "suffix": "mp3"})
    assert pc.title == "Unknown Title"
    assert pc.artist == "Unknown Artist"
    assert pc.album == "Unknown Album"


def test_art_hash_left_none_without_artwork_probe() -> None:
    pc = song_to_pc_track(_song(coverArt="cov1"))
    assert pc.art_hash is None


def test_check_artwork_false_classifies_missing_when_no_cover() -> None:
    # no coverArt id -> has_artwork False regardless of check flag
    pc = song_to_pc_track(_song(), check_artwork=True, client=object())
    assert pc.art_hash is None


def test_duration_zero_when_missing() -> None:
    pc = song_to_pc_track({"id": "x", "suffix": "mp3"})
    assert pc.duration_ms == 0
