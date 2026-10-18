"""Original iOpenPod SQLite behavior, exercised with synthetic Library data."""

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.library.test_browse_relationships import browse_source
from tests.iPodDB.library.test_playlists import (
    _smart,  # pyright: ignore[reportPrivateUsage]
    _string_rule,  # pyright: ignore[reportPrivateUsage]
)
from tests.iPodDB.SQLiteDB.sqlite_test_support import (
    sqlite_rows,
    sqlite_value,
)

from iPodDB.device_time import unix_to_mac
from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk, new_string_mhod
from iPodDB.iTunesDB.cdb import compress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhlp import DEFINITION as MHLP
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataChapter,
    MhodChapterDataHedrHeader,
    MhodChapterDataPayload,
    MhodChapterDataPreamble,
    MhodChapterDataRawAtom,
    MhodChapterDataSeanHeader,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import DEFINITION as MHYP
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodPayloadKind, MhodType
from iPodDB.iTunesDB.writer.mhod_encoder import encode_mhod_body
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    IPodTrackDetails,
    LibrarySnapshot,
    MediaType,
    Track,
    TrackMetadata,
)
from iPodDB.library.playlists import Playlist, PlaylistKind, playlist_entries
from iPodDB.library.writing import WriteChecksum, WriteResources, WriteTarget
from iPodDB.shared.chunk import EmptyChunkHeader
from iPodDB.SQLiteDB.artifacts import SQLiteDatabaseSet
from iPodDB.SQLiteDB.database import build_sqlite_databases


def test_all_five_schemas_match_original_reference() -> None:
    path = Path(__file__).parents[2] / "fixtures/SQLiteDB/original-schema.json"
    expected = json.loads(path.read_text(encoding="utf-8"))
    result = build_sqlite_databases(
        LibrarySnapshot(), database_id=42, checksum=WriteChecksum.NONE
    )
    for name, data in result.artifacts()[:-1]:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.deserialize(data)
            tables = [
                r[0]
                for r in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            indexes = [
                r[0]
                for r in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY name"
                )
            ]
            actual = {
                "tables": {
                    table: [
                        list(r)
                        for r in connection.execute(f'PRAGMA table_info("{table}")')
                    ]
                    for table in tables
                },
                "indexes": {
                    index: [
                        list(r)
                        for r in connection.execute(f'PRAGMA index_info("{index}")')
                    ]
                    for index in indexes
                },
            }
            assert actual == expected[name], name


def _prepare_metadata_edit(source: IPodLibrary) -> SQLiteDatabaseSet:
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, year=2026) for t in source.snapshot.tracks),
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired),
            WriteTarget(compressed_database=True, sqlite_database=True),
        ),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.sqlite is not None
    return result.prepared.sqlite


def test_native_container_dates_preserve_the_core_data_epoch() -> None:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    selection = next(
        s for s in document.find_chunks(MhypHeader) if not s.chunk.header.master_flag
    )
    document = document.replace_chunk(
        selection,
        replace(
            selection.chunk,
            header=replace(
                selection.chunk.header,
                timestamp=unix_to_mac(978307200, 0),
                timestamp_2=unix_to_mac(978307260, 0),
            ),
        ),
    )
    for track in document.find_chunks(MhitHeader):
        document = document.replace_chunk(
            track,
            replace(
                track.chunk,
                header=replace(
                    track.chunk.header,
                    date_added=unix_to_mac(1700000000, 0),
                ),
            ),
        )
    data = _prepare_metadata_edit(
        IPodLibrary(compress_iTunesCDB(write_iTunesDB(document)))
    ).library
    assert sqlite_rows(
        data, "SELECT date_created,date_modified FROM container WHERE name='Playlist'"
    ) == ((0, 60),)


@pytest.mark.parametrize(
    "command", ("INVALID SQL", 'DELETE FROM "Locations.itdb".location')
)
def test_failed_generation_closes_all_temporary_connections(
    monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    from iPodDB.SQLiteDB import database as database_module

    connections: list[sqlite3.Connection] = []
    # Instrument both private constructors to verify cleanup on failure.
    new = database_module._new  # pyright: ignore[reportPrivateUsage]
    reopen = database_module._open  # pyright: ignore[reportPrivateUsage]

    def remember_new(schema: str) -> sqlite3.Connection:
        connection = new(schema)
        connections.append(connection)
        return connection

    def remember_open(data: bytes) -> sqlite3.Connection:
        connection = reopen(data)
        connections.append(connection)
        return connection

    monkeypatch.setattr(database_module, "_new", remember_new)
    monkeypatch.setattr(database_module, "_open", remember_open)
    with pytest.raises(ValueError):
        build_sqlite_databases(
            LibrarySnapshot((Track(1, "Track", "Artist", "Album", 1000),)),
            database_id=42,
            checksum=WriteChecksum.NONE,
            postprocess_commands=(command,),
        )
    assert len(connections) >= 5
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


@pytest.mark.parametrize("dataset", (3, 5))
def test_native_smart_preferences_and_rule_bytes_survive_projection(
    dataset: int,
) -> None:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    prefs = MhodSmartPrefsPrefix(
        live_update=0,
        check_rules=1,
        check_limits=0,
        limit_type=3,
        limit_sort=23,
        limit_value=73,
        match_checked_only=1,
        reverse_sort=1,
    )
    metadata = _smart(_string_rule(), prefs=prefs)
    if dataset == 3:
        selection = next(
            s
            for s in document.find_chunks(MhypHeader)
            if not s.chunk.header.master_flag
        )
        document = document.replace_chunk(
            selection,
            replace(selection.chunk, children=(*metadata, *selection.chunk.children)),
        )
    else:
        row = new_itunes_chunk(
            MHYP,
            MhypHeader(playlist_id=10, master_flag=1, mhsd_5_type=4),
            children=(new_string_mhod(MhodType.TITLE, "Music"), *metadata),
        )
        document = document.append_child(
            new_itunes_chunk(
                MHSD,
                MhsdHeader(dataset_type=5),
                children=(new_itunes_chunk(MHLP, EmptyChunkHeader(), children=(row,)),),
            )
        )
    data = _prepare_metadata_edit(
        IPodLibrary(compress_iTunesCDB(write_iTunesDB(document)))
    ).library
    assert sqlite_rows(
        data,
        "SELECT smart_is_dynamic,smart_is_filtered,smart_is_limited,smart_limit_kind,smart_limit_order,smart_limit_value,smart_enabled_only,smart_reverse_limit_order FROM container WHERE smart_criteria IS NOT NULL",
    ) == ((0, 1, 0, 3, 23, 73, 1, 1),)
    criteria, _ = encode_mhod_body(metadata[1], MhodPayloadKind.SMART_RULES)
    assert (
        sqlite_value(
            data,
            "SELECT smart_criteria FROM container WHERE smart_criteria IS NOT NULL",
        )
        == criteria
    )


def test_extras_preserves_checked_native_chapter_preamble_and_unknown_atoms() -> None:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    payload = MhodChapterDataPayload(
        MhodChapterDataPreamble(7, 8, 9),
        MhodChapterDataSeanHeader(atom_type=b"sean", unk_0x08=1),
        MhodChapterDataHedrHeader(atom_type=b"hedr", unk_0x08=1, unk_0x18=1),
        (
            MhodChapterDataChapter(
                "Opening",
                0,
                (MhodChapterDataRawAtom(b"test", b"\x00\x00\x00\x0ctestdata"),),
            ),
        ),
        (),
    )
    chapter = new_itunes_chunk(
        MHOD, MhodHeader(mhod_type=MhodType.CHAPTER_DATA), payload=payload
    )
    track = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(track, track.chunk.append_child(chapter))
    databases = _prepare_metadata_edit(
        IPodLibrary(compress_iTunesCDB(write_iTunesDB(document)))
    )
    expected, _ = encode_mhod_body(chapter, MhodPayloadKind.CHAPTER_DATA)
    assert sqlite_rows(databases.extras, "SELECT item_pid,data FROM chapter") == (
        (101, expected),
    )


def test_container_identity_collisions_keep_folder_edges_and_repeated_entries() -> None:
    snapshot = LibrarySnapshot(
        (Track(7, "Track", "Artist", "Album", 1000),),
        (
            Playlist(42, "Folder", PlaylistKind.FOLDER),
            Playlist(23, "Child", parent_id=42, entries=playlist_entries((7, 7))),
        ),
    )
    databases = build_sqlite_databases(
        snapshot, database_id=42, checksum=WriteChecksum.NONE
    )
    assert (
        sqlite_value(
            databases.library,
            "SELECT p.name FROM container c JOIN container p ON c.parent_pid=p.pid WHERE c.name='Child'",
        )
        == "Folder"
    )
    assert sqlite_rows(
        databases.library,
        "SELECT i.item_pid,i.physical_order FROM item_to_container i JOIN container c ON c.pid=i.container_pid WHERE c.name='Child' ORDER BY physical_order",
    ) == ((7, 0), (7, 1))
    assert sqlite_value(databases.dynamic, "SELECT count(*) FROM container_ui") == 3


def test_audio_duration_uses_native_samples_then_original_duration_fallback() -> None:
    tracks = tuple(
        Track(
            i,
            "Track",
            "Artist",
            "Album",
            1200,
            metadata=TrackMetadata(sample_count=samples, sample_rate_hz=44100),
        )
        for i, samples in ((1, 52199), (2, 0))
    )
    data = build_sqlite_databases(
        LibrarySnapshot(tracks), database_id=42, checksum=WriteChecksum.NONE
    ).library
    assert sqlite_rows(
        data, "SELECT duration FROM avformat_info ORDER BY item_pid"
    ) == (
        (52199,),
        (52920,),
    )


@pytest.mark.parametrize(
    "command",
    (
        'DELETE FROM "Dynamic.itdb".container_ui',
        "DELETE FROM item_to_container",
        "UPDATE item SET album_pid=123456",
        'UPDATE "Locations.itdb".location SET base_location_id=123456',
        'UPDATE "Locations.itdb".location SET kind_id=123456',
        "INSERT INTO podcast_info(item_pid) VALUES (123456)",
    ),
)
def test_invalid_cross_file_relationships_block_publication(command: str) -> None:
    with pytest.raises(ValueError, match=r"SQLite.*(relationship|identity|membership)"):
        build_sqlite_databases(
            LibrarySnapshot((Track(1, "Track", "Artist", "Album", 1000),)),
            database_id=42,
            checksum=WriteChecksum.NONE,
            postprocess_commands=(command,),
        )


def test_duplicate_track_persistent_ids_are_rejected_as_a_preparation_error() -> None:
    tracks = tuple(
        Track(i, "Track", "Artist", "Album", 1000, ipod=IPodTrackDetails(db_track_id=9))
        for i in (1, 2)
    )
    with pytest.raises(ValueError, match="SQLite"):
        build_sqlite_databases(
            LibrarySnapshot(tracks), database_id=42, checksum=WriteChecksum.NONE
        )


def test_original_indexes_and_all_item_browse_orders_exist_without_postprocessing() -> (
    None
):
    tracks = tuple(
        Track(
            index,
            name,
            name,
            name,
            1000,
            genre=name,
            album_artist=name,
            metadata=TrackMetadata(composer=name),
        )
        for index, name in enumerate(("The Zebra", "An Apple"), 1)
    )
    data = build_sqlite_databases(
        LibrarySnapshot(tracks), database_id=42, checksum=WriteChecksum.NONE
    ).library
    assert {
        row[0]
        for row in sqlite_rows(
            data,
            "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL",
        )
    } == {
        "idx_item_album_pid",
        "idx_item_track_artist_pid",
        "item_album_order_idx",
        "item_artist_sort_order_idx",
        "item_composer_order_idx",
        "item_genre_id_idx",
        "item_title_order_idx",
        "item_to_container_container_pid_idx",
        "item_to_container_physical_order_idx",
    }
    assert sqlite_rows(
        data,
        "SELECT title_order,artist_order,album_order,genre_order,composer_order,album_artist_order,album_by_artist_order,series_name_order FROM item ORDER BY pid",
    ) == (
        (200, 200, 200, 200, 200, 200, 200, 100),
        (100, 100, 100, 100, 100, 100, 100, 100),
    )
    assert sqlite_rows(
        data,
        "SELECT sort_title,sort_artist,sort_album_artist,sort_composer FROM item ORDER BY pid",
    ) == (
        ("Zebra", "Zebra", "Zebra", "Zebra"),
        ("Apple", "Apple", "Apple", "Apple"),
    )


def test_browse_groups_have_artwork_links_ranks_and_calculated_counts() -> None:
    tracks = (
        Track(
            1,
            "One",
            "The Zebra",
            "One",
            1000,
            genre="Rock",
            artwork_id=7,
            metadata=TrackMetadata(composer="Zed", compilation=True),
        ),
        Track(
            2,
            "Two",
            "Apple",
            "Two",
            1000,
            genre="Rock",
            metadata=TrackMetadata(composer="Amy"),
        ),
        Track(
            3,
            "Three",
            "Apple",
            "Two",
            1000,
            genre="Rock",
            metadata=TrackMetadata(composer="Amy"),
        ),
    )
    data = build_sqlite_databases(
        LibrarySnapshot(tracks), database_id=42, checksum=WriteChecksum.NONE
    ).library
    assert sqlite_rows(
        data,
        "SELECT artist_count_calc,album_count_calc,compilation_count_calc FROM genre_map",
    ) == ((2, 2, 1),)
    assert sqlite_rows(
        data,
        "SELECT name,name_order,sort_name,artwork_status FROM artist ORDER BY name_order",
    ) == (
        ("Apple", 100, "Apple", 0),
        ("The Zebra", 200, "Zebra", 1),
    )
    assert (
        sqlite_value(
            data,
            "SELECT a.artwork_item_pid FROM artist r JOIN album a ON a.pid=r.artwork_album_pid WHERE r.name='The Zebra'",
        )
        == 1
    )
    assert sqlite_rows(
        data, "SELECT name,name_order FROM composer ORDER BY name_order"
    ) == (
        ("Amy", 100),
        ("Zed", 200),
    )
    assert sqlite_rows(
        data,
        "SELECT name,album_count,has_non_compilation_tracks FROM track_artist ORDER BY name",
    ) == (("Apple", 1, 1), ("The Zebra", 1, 0))


@pytest.mark.parametrize("remove_track", (False, True))
def test_cdb_preparation_projects_native_categories_and_dynamic_rows(
    remove_track: bool,
) -> None:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    categories = tuple(
        new_itunes_chunk(
            MHYP,
            MhypHeader(
                playlist_id=identity,
                master_flag=1,
                mhsd_5_type=kind,
                playlist_kind_flags=0x100,
            ),
            children=(
                new_string_mhod(MhodType.TITLE, name),
                *(new_itunes_chunk(MHIP, MhipHeader(track_id=i)) for i in (1, 2)),
            ),
        )
        # A category can share an ID with the user Playlist in dataset 3.
        for identity, kind, name in ((10, 4, "Music"), (90, 5, "Audiobooks"))
    )
    document = document.append_child(
        new_itunes_chunk(
            MHSD,
            MhsdHeader(dataset_type=5),
            children=(new_itunes_chunk(MHLP, EmptyChunkHeader(), children=categories),),
        )
    )
    source = IPodLibrary(compress_iTunesCDB(write_iTunesDB(document)))
    assert tuple(p.name for p in source.snapshot.playlists) == ("Playlist",)
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, year=2026)
            for t in source.snapshot.tracks
            if not remove_track or t.track_id == 2
        ),
    )
    if remove_track:
        desired = replace(
            desired,
            playlists=tuple(
                replace(p, entries=tuple(e for e in p.entries if e.track_id == 2))
                for p in desired.playlists
            ),
        )
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired, delete_omissions=remove_track),
            WriteTarget(compressed_database=True, sqlite_database=True),
        ),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    databases = result.prepared.sqlite
    assert databases is not None
    assert (
        sqlite_value(
            databases.library, "SELECT pid FROM container WHERE name='Playlist'"
        )
        == 10
    )
    assert sqlite_rows(
        databases.library,
        "SELECT name,distinguished_kind,media_kinds,is_hidden,smart_is_folder FROM container WHERE distinguished_kind!=0 ORDER BY distinguished_kind",
    ) == (
        ("Music", 4, 1, 1, 0),
        ("Audiobooks", 5, 0, 1, 0),
    )
    assert sqlite_rows(
        databases.library,
        "SELECT c.name,count(i.item_pid) FROM container c LEFT JOIN item_to_container i ON c.pid=i.container_pid GROUP BY c.pid ORDER BY c.name",
    ) == (
        ("Audiobooks", 1 if remove_track else 2),
        ("Music", 1 if remove_track else 2),
        ("My iPod", 1 if remove_track else 2),
        ("Playlist", 1 if remove_track else 3),
    )
    assert sqlite_rows(
        databases.library, "SELECT pid FROM container ORDER BY pid"
    ) == sqlite_rows(
        databases.dynamic,
        "SELECT container_pid FROM container_ui ORDER BY container_pid",
    )


def test_companion_validation_rejects_postprocessing_that_breaks_track_links() -> None:
    with pytest.raises(ValueError, match=r"SQLite.*(relationship|identity|membership)"):
        build_sqlite_databases(
            LibrarySnapshot((Track(1, "Track", "Artist", "Album", 1000),)),
            database_id=42,
            checksum=WriteChecksum.NONE,
            postprocess_commands=('DELETE FROM "Locations.itdb".location',),
        )


def test_media_browse_flags_do_not_turn_spoken_content_into_songs() -> None:
    data = build_sqlite_databases(
        LibrarySnapshot(
            (
                Track(
                    1,
                    "Chapter",
                    "Author",
                    "Book",
                    1000,
                    media_types=(MediaType.AUDIOBOOK,),
                    metadata=TrackMetadata(composer="Narrator"),
                ),
            )
        ),
        database_id=42,
        checksum=WriteChecksum.NONE,
    ).library
    assert sqlite_rows(
        data, "SELECT has_songs,has_music_videos,has_movies FROM album"
    ) == ((0, 0, 0),)
    assert sqlite_value(data, "SELECT has_songs FROM artist") == 0
