"""Standalone native-order vectors, independent of the private firmware lab."""

import pytest
from tests.iPodDB.alarm_fixtures import (
    playlist_chunk,
    playlist_dataset,
    playlist_library,
    track_dataset,
)

from iPodDB.iTunesDB.builder.build_iTunesDB import (
    new_iTunesDB,
)
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import AlarmPlaylistLayout
from iPodDB.library.alarm_playlists import project_alarm_playlists
from iPodDB.shared.chunk import ParsedChunk


@pytest.mark.parametrize(
    "layout", (AlarmPlaylistLayout.CLOCK, AlarmPlaylistLayout.VIDEO)
)
def test_imported_order_and_filter_match_original_arm_array_vectors(
    layout: AlarmPlaylistLayout,
) -> None:
    # Original native count/fill receipt v6: source ordinals [0,1,5,6,7]
    # from Master, audio, empty, video, podcast, smartempty, smartvideo,
    # mediazero, internal. Internal0x40 is runtime-only and absent from MHYP.
    members = (MhipHeader(track_id=1),)
    video = (MhipHeader(track_id=2),)
    library = playlist_library(
        track_dataset(
            MhitHeader(track_id=1, media_type=1),
            MhitHeader(track_id=2, media_type=2),
            MhitHeader(track_id=3, media_type=0),
        ),
        playlist_dataset(
            3,
            (
                playlist_chunk(100, master=1),
                playlist_chunk(101, items=members),
                playlist_chunk(102),
                playlist_chunk(103, items=video),
                playlist_chunk(104, flags=1, items=members),
                playlist_chunk(105, smart=True),
                playlist_chunk(106, smart=True, items=video),
                playlist_chunk(107, items=(MhipHeader(track_id=3),)),
            ),
        ),
    )
    catalog = library.alarm_playlists(layout)
    assert catalog.complete, catalog.issues
    assert [(p.index, p.playlist_id) for p in catalog.playlists] == list(
        enumerate((100, 101, 105, 106, 107))
    )
    assert catalog.playlists[0].is_master
    assert catalog.playlists[1].name == "101"


@pytest.mark.parametrize("first,second", ((2, 3), (3, 2)))
@pytest.mark.parametrize("layout", tuple(AlarmPlaylistLayout))
def test_first_native_playlist_dataset_wins_without_semantic_deduplication(
    first: int, second: int, layout: AlarmPlaylistLayout
) -> None:
    library = playlist_library(
        track_dataset(MhitHeader(track_id=1)),
        playlist_dataset(
            first,
            (
                playlist_chunk(100, master=1),
                playlist_chunk(101, items=(MhipHeader(track_id=1),)),
            ),
        ),
        playlist_dataset(
            second,
            (
                playlist_chunk(200, master=1),
                playlist_chunk(201, items=(MhipHeader(track_id=1),)),
            ),
        ),
    )
    catalog = library.alarm_playlists(layout)
    assert catalog.complete
    assert [p.playlist_id for p in catalog.playlists] == [100, 101]


def test_mini_keeps_empty_folder_shaped_and_video_only_rows() -> None:
    library = playlist_library(
        playlist_dataset(
            2,
            (
                playlist_chunk(100, master=2),
                playlist_chunk(101),
                playlist_chunk(102, flags=0x100),
                playlist_chunk(103, flags=2),
                playlist_chunk(104, flags=1),
            ),
        )
    )
    catalog = library.alarm_playlists(AlarmPlaylistLayout.MINI)
    assert catalog.complete
    assert [p.playlist_id for p in catalog.playlists] == [100, 101, 102, 103]


def test_record_classes_media_low_word_and_import_order_are_native() -> None:
    tracks = track_dataset(
        MhitHeader(track_id=1, record_class=2, media_type=1),
        MhitHeader(track_id=2, record_class=3, media_type=1),
        MhitHeader(track_id=3, record_class=99, media_type=1),
        MhitHeader(track_id=4, media_type=0x10002),
    )
    lists = playlist_dataset(
        2,
        (
            playlist_chunk(100, master=1),
            *(
                playlist_chunk(100 + i, items=(MhipHeader(track_id=i),))
                for i in range(1, 5)
            ),
        ),
    )
    library = playlist_library(tracks, lists)
    nano = library.alarm_playlists(AlarmPlaylistLayout.CLOCK)
    video = library.alarm_playlists(AlarmPlaylistLayout.VIDEO)
    assert nano.complete and video.complete
    assert [p.playlist_id for p in nano.playlists] == [100]
    assert [p.playlist_id for p in video.playlists] == [100, 101, 102]
    # Loading Tracks later cannot repair already skipped MHIP references.
    assert [
        p.playlist_id
        for p in playlist_library(lists, tracks)
        .alarm_playlists(AlarmPlaylistLayout.VIDEO)
        .playlists
    ] == [100]


def test_groups_require_prior_parent_and_resolved_tracks() -> None:
    library = playlist_library(
        track_dataset(MhitHeader(track_id=1)),
        playlist_dataset(
            3,
            (
                playlist_chunk(100, master=1),
                playlist_chunk(
                    101,
                    items=(
                        MhipHeader(track_id=1, group_id_ref=7),
                        MhipHeader(group_marker=1, group_id=7),
                    ),
                ),
                playlist_chunk(
                    102,
                    items=(
                        MhipHeader(group_marker=1, group_id=7),
                        MhipHeader(group_marker=1, group_id=8, group_id_ref=7),
                        MhipHeader(track_id=1, group_id_ref=8),
                    ),
                ),
                playlist_chunk(103, items=(MhipHeader(track_id=999),)),
            ),
        ),
    )
    catalog = library.alarm_playlists(AlarmPlaylistLayout.CLOCK)
    assert catalog.complete
    assert [p.playlist_id for p in catalog.playlists] == [100, 102]


@pytest.mark.parametrize(
    "rows",
    (
        (playlist_chunk(100),),
        (playlist_chunk(100, master=1), playlist_chunk(101, master=1)),
        (playlist_chunk(100), playlist_chunk(101, master=1)),
        (playlist_chunk(100, master=1), playlist_chunk(100)),
        (playlist_chunk(0, master=1),),
    ),
)
def test_ambiguous_master_or_ids_never_qualify_choices(
    rows: tuple[ParsedChunk[MhypHeader], ...],
) -> None:
    document = parse_iTunesDB(
        write_iTunesDB(
            new_iTunesDB(MhbdHeader(), datasets=(playlist_dataset(2, rows),))
        )
    )
    catalog = project_alarm_playlists(document, AlarmPlaylistLayout.MINI)
    assert not catalog.complete and catalog.issues


def test_duplicate_native_track_identity_blocks_clock_choices() -> None:
    document = parse_iTunesDB(
        write_iTunesDB(
            new_iTunesDB(
                MhbdHeader(),
                datasets=(
                    track_dataset(MhitHeader(track_id=1), MhitHeader(track_id=1)),
                    playlist_dataset(2, (playlist_chunk(100, master=1),)),
                ),
            )
        )
    )
    assert not project_alarm_playlists(document, AlarmPlaylistLayout.CLOCK).complete
    assert project_alarm_playlists(document, AlarmPlaylistLayout.MINI).complete
