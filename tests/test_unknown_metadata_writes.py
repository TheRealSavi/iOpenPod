from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.sync.unknown_metadata import (
    UnknownMetadataRegistry,
    apply_unknown_placeholders,
    apply_unknown_placeholders_to_mapping,
    unknown_value,
)


def test_unknown_value_does_not_append_track_specific_identifiers() -> None:
    assert unknown_value("Artist", "", identifier=17) == "Unknown Artist"
    assert unknown_value("Album", None, identifier="6. track.mp3") == "Unknown Album"
    assert unknown_value("Album Artist", " ", identifier=99) == "Unknown Artist"


def test_apply_unknown_placeholders_groups_blank_track_infos_by_album() -> None:
    tracks = [
        TrackInfo("Track 1", ":iPod_Control:Music:F00:ONE.m4a"),
        TrackInfo("Track 2", ":iPod_Control:Music:F00:TWO.m4a"),
    ]

    apply_unknown_placeholders(tracks)

    assert [(t.album, t.album_artist, t.artist) for t in tracks] == [
        ("Unknown Album 1", "Unknown Artist 1", "Unknown Artist 1"),
        ("Unknown Album 1", "Unknown Artist 1", "Unknown Artist 1"),
    ]


def test_apply_unknown_placeholders_uses_source_folders_for_blank_albums() -> None:
    tracks = [
        TrackInfo(
            "Song A",
            ":iPod_Control:Music:F00:ONE.m4a",
            source_relative_path="Artist One/Album One/01 Song A.flac",
        ),
        TrackInfo(
            "Song B",
            ":iPod_Control:Music:F00:TWO.m4a",
            source_relative_path="Artist One/Album One/02 Song B.flac",
        ),
        TrackInfo(
            "Song C",
            ":iPod_Control:Music:F00:THREE.m4a",
            source_relative_path="Artist One/Album Two/01 Song C.flac",
        ),
    ]

    apply_unknown_placeholders(tracks)

    assert [(t.album, t.album_artist, t.artist) for t in tracks] == [
        ("Album One", "Artist One", "Artist One"),
        ("Album One", "Artist One", "Artist One"),
        ("Album Two", "Artist One", "Artist One"),
    ]


def test_apply_unknown_placeholders_collapses_disc_subfolders() -> None:
    tracks = [
        TrackInfo(
            "Song A",
            ":iPod_Control:Music:F00:ONE.m4a",
            source_relative_path="Artist/Album/Disc 1/01 Song A.flac",
        ),
        TrackInfo(
            "Song B",
            ":iPod_Control:Music:F00:TWO.m4a",
            source_relative_path="Artist/Album/Disc 2/01 Song B.flac",
        ),
    ]

    apply_unknown_placeholders(tracks)

    assert [(t.album, t.album_artist, t.artist) for t in tracks] == [
        ("Album", "Artist", "Artist"),
        ("Album", "Artist", "Artist"),
    ]


def test_apply_unknown_placeholders_preserves_literal_backslashes_in_folder_names() -> None:
    track = TrackInfo(
        "Song A",
        ":iPod_Control:Music:F00:ONE.m4a",
        source_relative_path=r"Artist/IGF ¯\_(ツ)_¯/01 Song A.flac",
    )

    apply_unknown_placeholders([track])

    assert track.album == r"IGF ¯\_(ツ)_¯"
    assert track.album_artist == "Artist"
    assert track.artist == "Artist"


def test_apply_unknown_placeholders_does_not_infer_album_from_absolute_root_when_relative_path_has_no_folder() -> None:
    track = TrackInfo(
        "Song A",
        ":iPod_Control:Music:F00:ONE.m4a",
        source_path="/Users/example/Music/Song A.flac",
        source_relative_path="Song A.flac",
    )

    apply_unknown_placeholders([track])

    assert track.album == "Unknown Album 1"
    assert track.album_artist == "Unknown Artist 1"
    assert track.artist == "Unknown Artist 1"


def test_mapping_placeholders_repair_per_track_unknown_artists() -> None:
    registry = UnknownMetadataRegistry()
    tracks = [
        {
            "Title": "Track 1",
            "Album": "Unknown Album 1",
            "Album Artist": "Unknown Album Artist 1",
            "Artist": "Unknown Artist 17670209786460602159",
        },
        {
            "Title": "Track 2",
            "Album": "Unknown Album 1",
            "Album Artist": "Unknown Album Artist 1",
            "Artist": "Unknown Artist 11007425599211842244",
        },
    ]

    for track in tracks:
        apply_unknown_placeholders_to_mapping(track, registry)

    assert [(t["Album"], t["Album Artist"], t["Artist"]) for t in tracks] == [
        ("Unknown Album 1", "Unknown Artist 1", "Unknown Artist 1"),
        ("Unknown Album 1", "Unknown Artist 1", "Unknown Artist 1"),
    ]


def test_mapping_placeholders_strip_filename_suffixes() -> None:
    registry = UnknownMetadataRegistry()
    track = {
        "Title": "Track 1",
        "Album": "Unknown Album 6. two heart tombs.mp3",
        "Album Artist": "Unknown Album Artist 6. two heart tombs.mp3",
        "Artist": "Unknown Artist 6. two heart tombs.mp3",
    }

    apply_unknown_placeholders_to_mapping(track, registry)

    assert track["Album"] == "Unknown Album 1"
    assert track["Album Artist"] == "Unknown Artist 1"
    assert track["Artist"] == "Unknown Artist 1"


def test_mapping_placeholders_use_source_folders_when_repairing_bad_suffixes() -> None:
    registry = UnknownMetadataRegistry()
    tracks = [
        {
            "Title": "Track 1",
            "source_relative_path": "Album A/01 Track 1.mp3",
            "Album": "Unknown Album 1. Track 1.mp3",
            "Album Artist": "Unknown Album Artist 1. Track 1.mp3",
            "Artist": "Unknown Artist 1. Track 1.mp3",
        },
        {
            "Title": "Track 2",
            "source_relative_path": "Album B/01 Track 2.mp3",
            "Album": "Unknown Album 1. Track 2.mp3",
            "Album Artist": "Unknown Album Artist 1. Track 2.mp3",
            "Artist": "Unknown Artist 1. Track 2.mp3",
        },
    ]

    for track in tracks:
        apply_unknown_placeholders_to_mapping(track, registry)

    assert [(t["Album"], t["Album Artist"], t["Artist"]) for t in tracks] == [
        ("Album A", "Unknown Artist 1", "Unknown Artist 1"),
        ("Album B", "Unknown Artist 2", "Unknown Artist 2"),
    ]


def test_mapping_placeholders_do_not_treat_shrug_title_backslash_as_path_separator() -> None:
    registry = UnknownMetadataRegistry()
    track = {
        "Title": r"03. IGF ¯\_(ツ)_/¯ (Instrumental)",
        "source_relative_path": r"Artist/Album/03. IGF ¯\_(ツ)_¯ (Instrumental).mp3",
        "Album": "",
        "Album Artist": "",
        "Artist": "",
    }

    apply_unknown_placeholders_to_mapping(track, registry)

    assert track["Title"] == r"03. IGF ¯\_(ツ)_/¯ (Instrumental)"
    assert track["Album"] == "Album"
    assert track["Album Artist"] == "Artist"
    assert track["Artist"] == "Artist"
