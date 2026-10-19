"""Captured Nano structure: shows, partial playback, and explicit UI repair."""

from dataclasses import replace

import pytest
from tests.iPodDB.SQLiteDB.sqlite_test_support import sample_snapshot, sqlite_rows

from iPodDB.library import IPodTrackDetails, LibrarySnapshot, MediaType
from iPodDB.library.playlists import Playlist, playlist_entries
from iPodDB.library.writing import WriteChecksum
from iPodDB.SQLiteDB.database import build_sqlite_databases
from iPodDB.SQLiteDB.inputs import SQLiteContainer, SQLiteNativeMetadata, SQLiteSource


@pytest.mark.parametrize("bookmark,expected", [(0, 0), (3822, 1)])
def test_partial_playback_is_not_erased_or_counted_as_a_completed_play(
    bookmark: int, expected: int
) -> None:
    track = sample_snapshot().tracks[0]
    track = replace(
        track,
        play_count=0,
        metadata=replace(track.metadata, played=False, bookmark_time_ms=bookmark),
    )
    result = build_sqlite_databases(
        LibrarySnapshot((track,)), database_id=42, checksum=WriteChecksum.NONE
    )
    assert sqlite_rows(
        result.dynamic, "SELECT has_been_played,play_count_user FROM item_stats"
    ) == ((expected, 0),)


def test_podcast_optional_show_artist_and_season_tags_do_not_split_a_feed() -> None:
    track = sample_snapshot().tracks[0]
    episode = replace(
        track,
        album="Show",
        media_types=(MediaType.PODCAST,),
        ipod=IPodTrackDetails(db_track_id=123, media_type_code=4),
        metadata=replace(track.metadata, podcast_rss_url="https://example.com/feed"),
    )
    added = replace(
        episode,
        track_id=8,
        show="Show",
        artist="Guest",
        album_artist="Publisher",
        season_number=2,
        ipod=IPodTrackDetails(db_track_id=124, media_type_code=4),
    )
    result = build_sqlite_databases(
        LibrarySnapshot((episode, added)), database_id=42, checksum=WriteChecksum.NONE
    )
    assert sqlite_rows(result.library, "SELECT name,kind FROM album") == (("Show", 3),)
    assert sqlite_rows(
        result.library, "SELECT COUNT(DISTINCT album_pid) FROM item"
    ) == ((1,),)


def test_different_feeds_and_music_with_the_same_title_keep_separate_albums() -> None:
    track = sample_snapshot().tracks[0]
    podcast = replace(track, media_types=(MediaType.PODCAST,), ipod=None)
    tracks = (
        *(
            replace(
                podcast,
                track_id=i,
                metadata=replace(podcast.metadata, podcast_rss_url=feed),
            )
            for i, feed in enumerate(
                ("https://example.com/a", "https://example.com/b", ""), 1
            )
        ),
        replace(track, track_id=4, ipod=None),
    )
    result = build_sqlite_databases(
        LibrarySnapshot(tracks), database_id=42, checksum=WriteChecksum.NONE
    )
    assert sqlite_rows(
        result.library, "SELECT kind,COUNT(*) FROM album GROUP BY kind"
    ) == ((2, 1), (3, 3))


@pytest.mark.parametrize("normalize", [False, True])
def test_explicit_normalization_repairs_special_ui_but_keeps_user_ui_and_populated_categories(
    normalize: bool,
) -> None:
    snapshot = sample_snapshot()
    native = SQLiteNativeMetadata(
        containers=(
            SQLiteContainer(
                Playlist(21, "Podcasts", entries=playlist_entries((7,))), podcast=True
            ),
            SQLiteContainer(Playlist(22, "Empty Music"), dataset=5, category=4),
            SQLiteContainer(
                Playlist(23, "Populated Music", entries=playlist_entries((7,))),
                dataset=5,
                category=4,
            ),
            SQLiteContainer(Playlist(24, "Empty user playlist")),
        )
    )
    prior = build_sqlite_databases(
        snapshot,
        database_id=42,
        checksum=WriteChecksum.NONE,
        native=native,
        postprocess_commands=(
            'UPDATE "Dynamic.itdb".container_ui SET play_order=99,is_reversed=1,repeat_mode=2,shuffle_items=1',
        ),
    )
    result = build_sqlite_databases(
        snapshot,
        database_id=42,
        checksum=WriteChecksum.NONE,
        native=replace(native, normalize_podcasts=normalize),
        retained=tuple(
            SQLiteSource(n, b) for n, b in prior.artifacts() if n.endswith(".itdb")
        ),
    )
    assert sqlite_rows(result.library, "SELECT name FROM container WHERE pid=22") == (
        () if normalize else (("Empty Music",),)
    )
    assert sqlite_rows(
        result.library, "SELECT name FROM container WHERE pid IN (23,24) ORDER BY pid"
    ) == (("Populated Music",), ("Empty user playlist",))
    assert sqlite_rows(
        result.dynamic,
        "SELECT play_order,is_reversed,repeat_mode,shuffle_items FROM container_ui WHERE container_pid=21",
    ) == (((40 if normalize else 99), 1, 2, 1),)
    assert sqlite_rows(
        result.dynamic,
        "SELECT play_order,is_reversed,repeat_mode,shuffle_items FROM container_ui WHERE container_pid=24",
    ) == ((99, 1, 2, 1),)
