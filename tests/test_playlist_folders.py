from __future__ import annotations

from iopenpod.itunesdb_parser.chunk_parser import parse_chunk
from iopenpod.itunesdb_shared.constants import MEDIA_TYPE_PODCAST
from iopenpod.itunesdb_shared.playlist_hierarchy import reconcile_playlist_hierarchy
from iopenpod.itunesdb_shared.playlist_kinds import playlist_kind_flags
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.itunesdb_writer.mhlp_writer import write_mhlp_with_playlists
from iopenpod.itunesdb_writer.mhod_spl_writer import SmartPlaylistRule
from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo, write_mhyp, write_playlist
from iopenpod.sync._playlist_builder import build_and_evaluate_playlists


def test_playlist_folder_kind_and_parent_round_trip() -> None:
    chunk = write_mhyp(
        "Algorithms",
        [11, 12],
        playlist_id=0xA11,
        playlist_kind_flags=0x0100,
        parent_folder_playlist_id=0xF01,
    )

    parsed, chunk_type = parse_chunk(chunk, 0)
    playlist = parsed["data"]

    assert chunk_type == "mhyp"
    assert playlist["playlist_kind_flags"] == 0x0100
    assert playlist["podcast_flag"] == 0x0100
    assert playlist["is_folder"] is True
    assert playlist["is_podcast"] is False
    assert playlist["parent_folder_playlist_id"] == 0xF01
    assert playlist["unk0x30_playlist_ref"] == 0xF01


def test_playlist_info_exposes_folder_kind_without_becoming_a_podcast() -> None:
    playlist = PlaylistInfo(
        name="This is...",
        playlist_id=0x701,
        playlist_kind_flags=0x0100,
        parent_folder_playlist_id=0x700,
    )

    assert playlist.kind_flags == 0x0100
    assert playlist.podcast_flag == 0x0100
    assert playlist.is_folder is True
    assert playlist.is_podcast is False

    parsed, _chunk_type = parse_chunk(write_playlist(playlist), 0)
    assert parsed["data"]["playlist_kind_flags"] == 0x0100
    assert parsed["data"]["parent_folder_playlist_id"] == 0x700


def test_reconcile_playlist_hierarchy_emits_contiguous_folder_preorder() -> None:
    rows = reconcile_playlist_hierarchy([
        {"playlist_id": 1, "Title": "iPod", "master_flag": 1},
        {"playlist_id": 10, "Title": "Folder", "playlist_kind_flags": 0x0100},
        {"playlist_id": 11, "Title": "First", "parent_folder_playlist_id": 10},
        {"playlist_id": 20, "Title": "Loose"},
        {"playlist_id": 12, "Title": "Second", "parent_folder_playlist_id": 10},
    ])

    assert [row["playlist_id"] for row in rows] == [1, 10, 11, 12, 20]


def test_reconcile_playlist_hierarchy_rebuilds_folder_union_and_rules() -> None:
    rows = reconcile_playlist_hierarchy([
        {
            "playlist_id": 10,
            "Title": "Folder",
            "playlist_kind_flags": 0x0100,
            "items": [
                {"db_track_id": 103},
                {"db_track_id": 999},
                {"db_track_id": 101},
            ],
        },
        {
            "playlist_id": 11,
            "Title": "First",
            "parent_folder_playlist_id": 10,
            "items": [{"db_track_id": 101}, {"db_track_id": 102}],
        },
        {
            "playlist_id": 12,
            "Title": "Second",
            "parent_folder_playlist_id": 10,
            "items": [{"db_track_id": 102}, {"db_track_id": 103}],
        },
    ])

    folder = rows[0]
    assert folder["items"] == [
        {"db_track_id": 103},
        {"db_track_id": 101},
        {"db_track_id": 102},
    ]
    assert folder["mhip_child_count"] == 3
    assert folder["smart_playlist_data"]["check_rules"] is True
    assert folder["smart_playlist_rules"] == {
        "conjunction": "OR",
        "unk004": 0x00010001,
        "rules": [
            {
                "field_id": 0x28,
                "action_id": 1,
                "from_value": 11,
                "from_units": 1,
                "to_value": 11,
                "to_units": 1,
            },
            {
                "field_id": 0x28,
                "action_id": 1,
                "from_value": 12,
                "from_units": 1,
                "to_value": 12,
                "to_units": 1,
            },
        ],
    }


def test_reconcile_playlist_hierarchy_detaches_dangling_parent_links() -> None:
    rows = reconcile_playlist_hierarchy([
        {
            "playlist_id": 11,
            "Title": "Orphan",
            "podcast_flag": 0,
            "unk0x30_playlist_ref": 999,
        },
    ])

    assert rows == [{
        "playlist_id": 11,
        "Title": "Orphan",
        "podcast_flag": 0,
        "playlist_kind_flags": 0,
        "is_folder": False,
        "is_podcast": False,
        "unk0x30_playlist_ref": 0,
        "parent_folder_playlist_id": 0,
    }]


def test_reconcile_playlist_hierarchy_detaches_cyclic_folder_links() -> None:
    rows = reconcile_playlist_hierarchy([
        {
            "playlist_id": 10,
            "Title": "A",
            "playlist_kind_flags": 0x0100,
            "parent_folder_playlist_id": 20,
        },
        {
            "playlist_id": 20,
            "Title": "B",
            "playlist_kind_flags": 0x0100,
            "parent_folder_playlist_id": 10,
        },
    ])

    assert [row["parent_folder_playlist_id"] for row in rows] == [0, 0]


def test_reconcile_playlist_hierarchy_supports_nested_folders() -> None:
    rows = reconcile_playlist_hierarchy([
        {
            "playlist_id": 10,
            "Title": "Outer",
            "playlist_kind_flags": 0x0100,
        },
        {
            "playlist_id": 20,
            "Title": "Inner",
            "playlist_kind_flags": 0x0100,
            "parent_folder_playlist_id": 10,
        },
        {
            "playlist_id": 21,
            "Title": "Child",
            "parent_folder_playlist_id": 20,
        },
    ])

    outer, inner, child = rows
    assert outer["parent_folder_playlist_id"] == 0
    assert inner["parent_folder_playlist_id"] == 10
    assert child["parent_folder_playlist_id"] == 20
    assert [
        rule["from_value"]
        for rule in outer["smart_playlist_rules"]["rules"]
    ] == [20]
    assert [
        rule["from_value"]
        for rule in inner["smart_playlist_rules"]["rules"]
    ] == [21]


def test_nested_folder_writer_round_trips_recursive_aggregates_and_rules() -> None:
    playlists = [
        PlaylistInfo(
            name="Outer",
            playlist_id=10,
            playlist_kind_flags=0x0100,
            track_ids=[999, 102],
        ),
        PlaylistInfo(
            name="Inner",
            playlist_id=20,
            playlist_kind_flags=0x0100,
            parent_folder_playlist_id=10,
            track_ids=[998, 101],
        ),
        PlaylistInfo(
            name="Grandchild",
            playlist_id=21,
            parent_folder_playlist_id=20,
            track_ids=[101, 102],
        ),
    ]

    parsed, chunk_type = parse_chunk(
        write_mhlp_with_playlists([], playlists, db_id_2=77),
        0,
    )
    rows = [child["data"] for child in parsed["data"]][1:]

    assert chunk_type == "mhlp"
    assert [row["playlist_id"] for row in rows] == [10, 20, 21]
    outer, inner, grandchild = rows
    assert [
        outer["parent_folder_playlist_id"],
        inner["parent_folder_playlist_id"],
        grandchild["parent_folder_playlist_id"],
    ] == [0, 10, 20]
    assert [
        child["data"]["track_id"] for child in outer["mhip_children"]
    ] == [102, 101]
    assert [
        child["data"]["track_id"] for child in inner["mhip_children"]
    ] == [101, 102]

    outer_rules = next(
        child["data"]["data"]
        for child in outer["mhod_children"]
        if child["data"]["mhod_type"] == 51
    )
    inner_rules = next(
        child["data"]["data"]
        for child in inner["mhod_children"]
        if child["data"]["mhod_type"] == 51
    )
    def playlist_child_rule(playlist_id: int) -> dict[str, int]:
        return {
            "field_id": 0x28,
            "action_id": 1,
            "data_length": 68,
            "from_value": playlist_id,
            "from_date": 0,
            "from_units": 1,
            "to_value": playlist_id,
            "to_date": 0,
            "to_units": 1,
            "unk052": 0,
            "unk056": 0,
            "unk060": 0,
            "unk064": 0,
            "unk068": 0,
        }

    assert outer_rules["conjunction"] == 1
    assert outer_rules["unk004"] == 0x00010001
    assert outer_rules["rules"] == [playlist_child_rule(20)]
    assert inner_rules["conjunction"] == 1
    assert inner_rules["unk004"] == 0x00010001
    assert inner_rules["rules"] == [playlist_child_rule(21)]

    # Writer reconciliation is pure even though both folder aggregates changed.
    assert playlists[0].track_ids == [999, 102]
    assert playlists[1].track_ids == [998, 101]


def test_playlist_kind_flags_includes_explicit_true_semantics() -> None:
    assert playlist_kind_flags({"is_folder": True}) == 0x0100
    assert playlist_kind_flags({"is_podcast": True}) == 0x0001
    assert playlist_kind_flags({
        "playlist_kind_flags": 0x0100,
        "is_folder": False,
        "is_podcast": True,
    }) == 0x0101


def test_playlist_builder_preserves_folder_hierarchy_and_membership() -> None:
    song = TrackInfo(
        title="Song",
        location=":iPod_Control:Music:F00:SONG.mp3",
        track_id=1,
        db_track_id=101,
    )
    podcast = TrackInfo(
        title="Episode",
        location=":iPod_Control:Music:F00:POD.mp3",
        track_id=2,
        db_track_id=102,
        media_type=MEDIA_TYPE_PODCAST,
        podcast_flag=1,
    )

    _master, _master_id, playlists, *_rest = build_and_evaluate_playlists(
        [
            {"track_id": 1, "db_track_id": 101},
            {"track_id": 2, "db_track_id": 102},
        ],
        [
            {"playlist_id": 1, "Title": "iPod", "master_flag": 1},
            {
                "playlist_id": 10,
                "Title": "Folder",
                "playlist_kind_flags": 0x0100,
                "items": [{"db_track_id": 999}],
            },
            {
                "playlist_id": 11,
                "Title": "Child",
                "parent_folder_playlist_id": 10,
                "items": [{"db_track_id": 101}],
            },
        ],
        [],
        [],
        [song, podcast],
    )

    folder, child = playlists
    assert (folder.name, child.name) == ("Folder", "Child")
    assert folder.is_folder is True
    assert folder.is_podcast is False
    assert folder.track_ids == [101]
    assert child.parent_folder_playlist_id == 10
    assert folder.smart_rules is not None
    assert folder.smart_rules.conjunction == "OR"
    assert all(
        isinstance(rule, SmartPlaylistRule)
        for rule in folder.smart_rules.rules
    )
    assert [
        rule.from_value
        for rule in folder.smart_rules.rules
        if isinstance(rule, SmartPlaylistRule)
    ] == [11]


def test_playlist_builder_keeps_an_empty_folder_empty() -> None:
    song = TrackInfo(
        title="Song",
        location=":iPod_Control:Music:F00:SONG.mp3",
        track_id=1,
        db_track_id=101,
    )

    _master, _master_id, playlists, *_rest = build_and_evaluate_playlists(
        [{"track_id": 1, "db_track_id": 101}],
        [
            {"playlist_id": 1, "Title": "iPod", "master_flag": 1},
            {
                "playlist_id": 10,
                "Title": "Empty Folder",
                "playlist_kind_flags": 0x0100,
                "items": [],
            },
        ],
        [],
        [],
        [song],
    )

    assert len(playlists) == 1
    assert playlists[0].is_folder is True
    assert playlists[0].track_ids == []


def test_mhlp_writer_reconciles_playlist_info_folders_without_mutating_inputs() -> None:
    folder = PlaylistInfo(
        name="Folder",
        playlist_id=10,
        playlist_kind_flags=0x0100,
        track_ids=[102, 999, 101],
    )
    playlists = [
        folder,
        PlaylistInfo(
            name="First",
            playlist_id=11,
            parent_folder_playlist_id=10,
            track_ids=[101],
        ),
        PlaylistInfo(name="Loose", playlist_id=20, track_ids=[200]),
        PlaylistInfo(
            name="Second",
            playlist_id=12,
            parent_folder_playlist_id=10,
            track_ids=[101, 102],
        ),
    ]

    parsed, chunk_type = parse_chunk(
        write_mhlp_with_playlists([], playlists, db_id_2=77),
        0,
    )
    rows = [child["data"] for child in parsed["data"]]
    folder_row = rows[1]
    folder_rules = next(
        child["data"]["data"]
        for child in folder_row["mhod_children"]
        if child["data"]["mhod_type"] == 51
    )

    assert chunk_type == "mhlp"
    assert [row["playlist_id"] for row in rows[1:]] == [10, 11, 12, 20]
    assert [child["data"]["track_id"] for child in folder_row["mhip_children"]] == [
        102,
        101,
    ]
    assert folder_rules["conjunction"] == 1
    assert [rule["from_value"] for rule in folder_rules["rules"]] == [11, 12]
    assert [rule["to_value"] for rule in folder_rules["rules"]] == [11, 12]
    assert [rule["from_units"] for rule in folder_rules["rules"]] == [1, 1]
    assert [rule["to_units"] for rule in folder_rules["rules"]] == [1, 1]
    assert folder.track_ids == [102, 999, 101]
