"""Tests for the model/view library projections."""

from functools import partial

import pytest
from PySide6.QtCore import Qt

from iOpenPod.app.models.album_list_model import AlbumListModel, AlbumRole
from iOpenPod.app.models.collection_list_model import (
    CollectionKind,
    CollectionListModel,
    CollectionRole,
    CollectionSummary,
)
from iOpenPod.app.models.library_filter_models import (
    AlbumFilterProxyModel,
    AlbumSortMode,
    CollectionFilterProxyModel,
    CollectionSortMode,
    TrackFilterProxyModel,
)
from iOpenPod.app.models.track_table_model import (
    TrackColumn,
    TrackRole,
    TrackTableModel,
)
from iPodDB.library import (
    ContentAdvisory,
    IPodTrackDetails,
    LibrarySnapshot,
    MediaKind,
    MediaType,
    Track,
    TrackChapter,
    TrackMetadata,
)


def _record_signal(target: list[None], *_args: object) -> None:
    target.append(None)


def test_models_project_and_filter_ten_thousand_tracks() -> None:
    tracks = TrackTableModel()
    albums = AlbumListModel(tracks)
    album_proxy = AlbumFilterProxyModel(albums)
    track_proxy = TrackFilterProxyModel(tracks)

    tracks.replace_tracks(_tracks(10_000))

    assert tracks.rowCount() == 10_000
    assert albums.rowCount() == 1_000
    assert album_proxy.rowCount() == 1_000
    assert track_proxy.rowCount() == 10_000

    album_proxy.set_query("album 0042")
    assert album_proxy.rowCount() == 1
    assert album_proxy.index(0, 0).data(AlbumRole.TITLE) == "Album 0042"

    album = albums.album_at(42)
    assert album is not None
    track_proxy.set_album_key(album.key)
    assert track_proxy.rowCount() == 10

    track_proxy.set_query("track 00429")
    assert track_proxy.rowCount() == 1
    assert track_proxy.index(0, 0).data(TrackRole.TRACK_ID) == 429


def test_library_proxies_sort_cached_model_values() -> None:
    tracks = TrackTableModel()
    albums = AlbumListModel(tracks)
    tracks.replace_tracks(_tracks(100))

    album_proxy = AlbumFilterProxyModel(albums)
    album_proxy.set_sort_mode(AlbumSortMode.YEAR)
    first_year = album_proxy.index(0, 0).data(AlbumRole.YEAR)
    last_year = album_proxy.index(album_proxy.rowCount() - 1, 0).data(AlbumRole.YEAR)
    assert isinstance(first_year, int)
    assert isinstance(last_year, int)
    assert first_year <= last_year

    album_proxy.set_sort_direction(Qt.SortOrder.DescendingOrder)
    first_year = album_proxy.index(0, 0).data(AlbumRole.YEAR)
    last_year = album_proxy.index(album_proxy.rowCount() - 1, 0).data(AlbumRole.YEAR)
    assert isinstance(first_year, int)
    assert isinstance(last_year, int)
    assert first_year >= last_year

    track_proxy = TrackFilterProxyModel(tracks)
    track_proxy.sort(TrackColumn.SIZE, Qt.SortOrder.DescendingOrder)
    first_size = track_proxy.index(0, TrackColumn.SIZE).data(TrackRole.SORT_VALUE)
    last_size = track_proxy.index(
        track_proxy.rowCount() - 1,
        TrackColumn.SIZE,
    ).data(TrackRole.SORT_VALUE)
    assert isinstance(first_size, int)
    assert isinstance(last_size, int)
    assert first_size >= last_size


def test_track_table_exposes_the_full_optional_metadata_projection() -> None:
    model = TrackTableModel()
    model.replace_tracks(
        (
            Track(
                7,
                "Optional Fields",
                "Artist",
                "Album",
                185_000,
                album_artist="Album Artist",
                show="Example Show",
                episode="S01E02",
                season_number=1,
                episode_number=2,
                ipod=IPodTrackDetails(
                    db_track_id=0x0102030405060708,
                    artwork_id_ref=91,
                    album_id=44,
                    artist_id_ref=45,
                    composer_id=46,
                ),
                artwork_id=64,
                metadata=TrackMetadata(
                    composer="Composer",
                    comment="Comment",
                    grouping="Suite",
                    total_tracks=12,
                    disc_number=2,
                    total_discs=3,
                    compilation=True,
                    bpm=128,
                    unscrobbled_play_count=4,
                    skip_count=5,
                    sample_rate_hz=44_100,
                    content_advisory=ContentAdvisory.CLEAN,
                    file_format="AAC audio file",
                    sort_title="Optional Fields, The",
                    tv_network="Network",
                    category="Technology",
                    podcast_rss_url="https://example.test/feed",
                    chapters=(
                        TrackChapter("Opening", 0),
                        TrackChapter("Finale", 120_000),
                    ),
                    gapless=True,
                    skip_shuffle=True,
                    artwork_count=2,
                    equalizer="Acoustic",
                    location=":iPod_Control:Music:F00:track.m4a",
                    lyrics="Words",
                    track_keywords="demo optional",
                    show_locale="en_US",
                ),
            ),
        )
    )

    assert model.columnCount() == len(TrackColumn)
    assert model.columnCount() >= 80
    assert all(
        model.headerData(column, Qt.Orientation.Horizontal) for column in TrackColumn
    )
    assert model.index(0, TrackColumn.ALBUM_ARTIST).data() == "Album Artist"
    assert model.index(0, TrackColumn.COMPOSER).data() == "Composer"
    assert model.index(0, TrackColumn.TOTAL_TRACKS).data() == "12"
    assert model.index(0, TrackColumn.DISC_NUMBER).data() == "2"
    assert model.index(0, TrackColumn.SAMPLE_RATE).data() == "44.1 kHz"
    assert model.index(0, TrackColumn.CONTENT_ADVISORY).data() == "Clean"
    assert model.index(0, TrackColumn.CHAPTERS).data() == "2"
    assert model.index(0, TrackColumn.CHAPTER_TITLES).data() == "Opening, Finale"
    artwork = model.index(0, TrackColumn.ARTWORK)
    assert model.headerData(TrackColumn.ARTWORK, Qt.Orientation.Horizontal) == "Artwork"
    assert artwork.data() == "Artwork"
    assert artwork.data(TrackRole.ARTWORK_ID) == 64
    assert model.index(0, TrackColumn.DB_TRACK_ID).data() == "0x0102030405060708"
    assert (
        model.index(0, TrackColumn.LOCATION).data()
        == ":iPod_Control:Music:F00:track.m4a"
    )
    assert all(isinstance(model.index(0, column).data(), str) for column in TrackColumn)


def test_source_neutral_file_format_has_text_display_and_sort_values() -> None:
    model = TrackTableModel()
    model.replace_tracks(
        (
            Track(
                1,
                "Fallback",
                "Artist",
                "Album",
                1,
                metadata=TrackMetadata(file_format="M4A"),
            ),
        )
    )
    index = model.index(0, TrackColumn.FILE_FORMAT)

    assert index.data() == "M4A"
    assert index.data(TrackRole.SORT_VALUE) == "m4a"


def test_playlist_position_column_uses_aligned_occurrence_context() -> None:
    model = TrackTableModel()
    repeated = Track(1, "Repeated", "Artist", "Album", 1)
    model.replace_tracks(
        (repeated, repeated),
        playlist_positions=(4, 1),
    )

    first = model.index(0, TrackColumn.PLAYLIST_POSITION)
    second = model.index(1, TrackColumn.PLAYLIST_POSITION)
    assert first.data() == "5"
    assert second.data() == "2"
    assert first.data(TrackRole.SORT_VALUE) == 4
    assert second.data(TrackRole.SORT_VALUE) == 1

    model.replace_tracks((repeated, repeated))
    assert model.index(0, TrackColumn.PLAYLIST_POSITION).data() == ""


def test_source_neutral_tracks_use_the_same_models_and_optional_columns() -> None:
    snapshot = LibrarySnapshot(
        (
            Track(
                1,
                "External song",
                "Artist",
                "Album",
                120_000,
                media_types=(MediaType.AUDIO,),
                metadata=TrackMetadata(compilation=True, checked=False),
            ),
            Track(
                2,
                "External episode",
                "",
                "",
                60_000,
                media_types=(MediaType.VIDEO_PODCAST,),
            ),
        )
    )
    model = TrackTableModel()
    model.replace_tracks(snapshot.tracks)
    proxy = TrackFilterProxyModel(model)
    assert model.index(0, TrackColumn.COMPILATION).data() == "Yes"
    assert model.index(0, TrackColumn.CHECKED).data() == "No"
    assert model.index(0, TrackColumn.DB_TRACK_ID).data() == "—"
    assert model.index(1, TrackColumn.MEDIA_TYPE).data() == "Video Podcast"
    proxy.set_media_kinds((MediaKind.PODCAST,))
    assert proxy.rowCount() == 1
    assert proxy.index(0, 0).data(TrackRole.TRACK_ID) == 2


def test_media_type_column_displays_translated_types_and_unknown_diagnostics() -> None:
    model = TrackTableModel()
    model.replace_tracks(
        (
            Track(
                1,
                "Mixed",
                "",
                "",
                1,
                media_types=(MediaType.AUDIO, MediaType.RINGTONE),
                ipod=IPodTrackDetails(unknown_media_type_bits=0x10),
            ),
        )
    )
    assert model.index(0, TrackColumn.MEDIA_TYPE).data() == "Audio | Ringtone | 0x10"


def test_media_type_sorting_uses_semantic_text_supported_by_qt() -> None:
    model = TrackTableModel()
    model.replace_tracks(
        (
            Track(1, "Video", "", "", 1, media_types=(MediaType.VIDEO,)),
            Track(2, "Audio", "", "", 1, media_types=(MediaType.AUDIO,)),
        )
    )
    proxy = TrackFilterProxyModel(model)
    proxy.sort(TrackColumn.MEDIA_TYPE, Qt.SortOrder.AscendingOrder)
    assert proxy.index(0, 0).data(TrackRole.TRACK_ID) == 2
    assert proxy.index(1, 0).data(TrackRole.TRACK_ID) == 1


@pytest.mark.parametrize(
    ("gain_db", "display"),
    ((None, "—"), (0.0, "+0.0 dB"), (10.0, "+10.0 dB"), (-10.0, "-10.0 dB")),
)
def test_normalization_gain_column_preserves_missing_zero_and_signed_values(
    gain_db: float | None, display: str
) -> None:
    model = TrackTableModel()
    model.replace_tracks(
        (
            Track(
                1,
                "Track",
                "",
                "",
                1,
                metadata=TrackMetadata(normalization_gain_db=gain_db),
            ),
        )
    )
    index = model.index(0, TrackColumn.SOUND_CHECK)

    assert index.data() == display
    assert index.data(TrackRole.SORT_VALUE) == gain_db


def test_collection_proxy_sorts_relevant_aggregate_values() -> None:
    tracks = TrackTableModel()
    artists = CollectionListModel(tracks, CollectionKind.ARTIST)
    tracks.replace_tracks(
        (
            Track(1, "One", "Alpha", "Only", 100),
            Track(2, "Two", "Beta", "First", 20),
            Track(3, "Three", "Beta", "Second", 20),
            Track(4, "Four", "Gamma", "Shared", 10),
            Track(5, "Five", "Gamma", "Shared", 10),
            Track(6, "Six", "Gamma", "Shared", 10),
            Track(7, "Seven", "Delta", "Long", 1_000),
        )
    )
    proxy = CollectionFilterProxyModel(artists)

    assert proxy.index(0, 0).data(CollectionRole.TITLE) == "Alpha"

    proxy.set_sort_mode(CollectionSortMode.ITEM_COUNT)
    assert proxy.index(0, 0).data(CollectionRole.TITLE) == "Beta"

    proxy.set_sort_direction(Qt.SortOrder.DescendingOrder)
    assert proxy.index(0, 0).data(CollectionRole.ITEM_COUNT) == 1
    assert proxy.index(proxy.rowCount() - 1, 0).data(CollectionRole.ITEM_COUNT) == 2
    proxy.set_sort_direction(Qt.SortOrder.AscendingOrder)

    proxy.set_sort_mode(CollectionSortMode.TRACK_COUNT)
    assert proxy.index(0, 0).data(CollectionRole.TITLE) == "Gamma"

    proxy.set_sort_mode(CollectionSortMode.DURATION)
    assert proxy.index(0, 0).data(CollectionRole.TITLE) == "Delta"


def test_album_summary_uses_the_first_available_track_artwork_id() -> None:
    tracks = TrackTableModel()
    albums = AlbumListModel(tracks)
    first = _track(0)
    second = _track(1)
    tracks.replace_tracks(
        (
            first,
            Track(
                track_id=second.track_id,
                title=second.title,
                artist=second.artist,
                album=second.album,
                length_ms=second.length_ms,
                artwork_id=64,
            ),
        )
    )

    summary = albums.album_at(0)
    assert summary is not None
    assert summary.artwork_id == 64
    assert albums.index(0, 0).data(AlbumRole.ARTWORK_ID) == 64


def test_collection_models_build_fixed_four_tile_artwork_collages() -> None:
    tracks = TrackTableModel()
    artists = CollectionListModel(tracks, CollectionKind.ARTIST)
    tracks.replace_tracks(
        (
            Track(1, "One", "Artist", "First", 1, genre="Rock", artwork_id=11),
            Track(2, "Two", "Artist", "First", 1, genre="Rock", artwork_id=11),
            Track(3, "Three", "Artist", "Second", 1, genre="Rock", artwork_id=22),
            Track(4, "Four", "Artist", "Third", 1, genre="Rock"),
        )
    )

    assert artists.rowCount() == 1
    index = artists.index(0, 0)
    assert index.data(CollectionRole.TITLE) == "Artist"
    assert index.data(CollectionRole.ARTWORK_IDS) == (11, 22, 0, 0)
    summary = index.data(CollectionRole.SUMMARY)
    assert isinstance(summary, CollectionSummary)
    assert summary.representative_artwork_id == 11


def test_track_proxy_filters_specific_media_kinds() -> None:
    tracks = TrackTableModel()
    tracks.replace_tracks(
        (
            Track(1, "Song", "Artist", "Album", 1, media_types=(MediaType.AUDIO,)),
            Track(2, "Book", "Narrator", "Book", 1, media_types=(MediaType.AUDIOBOOK,)),
            Track(3, "Movie", "", "", 1, media_types=(MediaType.VIDEO,)),
            Track(
                4, "Episode", "", "", 1, media_types=(MediaType.TV_SHOW,), show="Show"
            ),
            Track(
                5, "Clip", "Artist", "Album", 1, media_types=(MediaType.MUSIC_VIDEO,)
            ),
        )
    )
    proxy = TrackFilterProxyModel(tracks)

    proxy.set_media_kinds((MediaKind.AUDIOBOOK,))
    assert proxy.rowCount() == 1
    assert proxy.index(0, 0).data(TrackRole.TRACK_ID) == 2

    proxy.set_media_kinds((MediaKind.MOVIE, MediaKind.TV_SHOW, MediaKind.MUSIC_VIDEO))
    assert proxy.rowCount() == 3


def test_same_track_sequence_updates_without_a_whole_model_reset() -> None:
    model = TrackTableModel()
    original = Track(1, "Before", "Artist", "Album", 1)
    changed = Track(1, "After", "Artist", "Album", 1)
    resets: list[None] = []
    changes: list[None] = []
    model.modelReset.connect(partial(_record_signal, resets))
    model.dataChanged.connect(partial(_record_signal, changes))

    model.replace_tracks((original,))
    resets.clear()
    model.replace_tracks((changed,))

    assert resets == []
    assert changes == [None]
    assert model.index(0, TrackColumn.TITLE).data() == "After"


def test_aggregate_models_update_existing_keys_without_resetting() -> None:
    tracks = TrackTableModel()
    albums = AlbumListModel(tracks)
    artists = CollectionListModel(tracks, CollectionKind.ARTIST)
    original = Track(1, "Before", "Artist", "Album", 1)
    changed = Track(1, "After", "Artist", "Album", 2)
    album_resets: list[None] = []
    artist_resets: list[None] = []
    album_changes: list[None] = []
    artist_changes: list[None] = []
    albums.modelReset.connect(partial(_record_signal, album_resets))
    artists.modelReset.connect(partial(_record_signal, artist_resets))
    albums.dataChanged.connect(partial(_record_signal, album_changes))
    artists.dataChanged.connect(partial(_record_signal, artist_changes))
    tracks.replace_tracks((original,))
    album_resets.clear()
    artist_resets.clear()

    tracks.replace_tracks((changed,))

    assert album_resets == []
    assert artist_resets == []
    assert album_changes == [None]
    assert artist_changes == [None]


def test_whole_library_snapshot_resets_each_aggregate_exactly_once() -> None:
    tracks = TrackTableModel()
    albums = AlbumListModel(tracks)
    artists = CollectionListModel(tracks, CollectionKind.ARTIST)
    tracks.replace_tracks((Track(1, "One", "First", "First", 1),))
    album_resets: list[None] = []
    artist_resets: list[None] = []
    album_inserts: list[None] = []
    artist_inserts: list[None] = []
    albums.modelReset.connect(partial(_record_signal, album_resets))
    artists.modelReset.connect(partial(_record_signal, artist_resets))
    albums.rowsInserted.connect(partial(_record_signal, album_inserts))
    artists.rowsInserted.connect(partial(_record_signal, artist_inserts))

    tracks.reset_tracks((Track(2, "Two", "Second", "Second", 1),))

    assert album_resets == [None]
    assert artist_resets == [None]
    assert album_inserts == []
    assert artist_inserts == []


def _tracks(count: int) -> tuple[Track, ...]:
    return tuple(_track(index) for index in range(count))


def _track(index: int) -> Track:
    album = index // 10
    return Track(
        track_id=index,
        title=f"Track {index:05d}",
        artist=f"Artist {album % 100:03d}",
        album=f"Album {album:04d}",
        length_ms=120_000 + index,
        genre=f"Genre {album % 12:02d}",
        year=1980 + (album % 45),
        track_number=(index % 10) + 1,
        size_bytes=3_000_000 + index,
        bitrate_kbps=256,
        play_count=index % 30,
        rating=(index % 6) * 20,
    )
