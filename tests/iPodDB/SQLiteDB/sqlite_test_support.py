"""Public synthetic Library and query helpers shared by SQLite tests."""

import sqlite3

from iPodDB.library import (
    IPodTrackDetails,
    LibrarySnapshot,
    Track,
    TrackChapter,
    TrackMetadata,
)
from iPodDB.library.playlists import Playlist, playlist_entries


def sample_snapshot() -> LibrarySnapshot:
    track = Track(
        7,
        "Title",
        "Artist",
        "Album",
        12_345,
        genre="Genre",
        year=2020,
        track_number=2,
        size_bytes=123_456,
        bitrate_kbps=256,
        play_count=3,
        rating=80,
        metadata=TrackMetadata(
            file_format="m4a",
            date_added=1_700_000_000,
            sample_rate_hz=44_100,
            location=":iPod_Control:Music:F03:ABCD.m4a",
            lyrics="words",
            chapters=(TrackChapter("Opening", 0),),
        ),
        ipod=IPodTrackDetails(db_track_id=0xF123456789ABCDEF, app_rating=60),
    )
    return LibrarySnapshot(
        (track,),
        (Playlist(23, "Favorites", entries=playlist_entries((7,))),),
        "Test iPod",
    )


def sqlite_value(data: bytes, query: str) -> object:
    connection = sqlite3.connect(":memory:")
    connection.deserialize(data)
    result = connection.execute(query).fetchone()[0]
    connection.close()
    return result


def sqlite_rows(data: bytes, query: str) -> tuple[tuple[object, ...], ...]:
    connection = sqlite3.connect(":memory:")
    connection.deserialize(data)
    result = tuple(connection.execute(query))
    connection.close()
    return result
