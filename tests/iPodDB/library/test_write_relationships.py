"""Firmware relationships remain consistent without exposing their Chunks to UI records."""

from dataclasses import replace

from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk, new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhia import DEFINITION as MHIA
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhii import DEFINITION as MHII
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhla import DEFINITION as MHLA
from iPodDB.iTunesDB.shared.chunk_defs.mhli import DEFINITION as MHLI
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartNumericRuleData,
    MhodSmartRulesPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    Playlist,
    PlaylistEntry,
    PlaylistKind,
    SmartPlaylist,
)
from iPodDB.library._smart_writing import smart_chunks
from iPodDB.library.writing import WriteResources
from iPodDB.shared.chunk import EmptyChunkHeader


def test_recursive_folder_aggregates_are_unique_and_rules_reference_direct_children() -> (
    None
):
    source = library()
    root = Playlist(-1, "Root", PlaylistKind.FOLDER)
    nested = Playlist(-2, "Nested", PlaylistKind.FOLDER, parent_id=-1)
    desired = replace(
        source.snapshot,
        playlists=(root, nested, replace(source.snapshot.playlists[0], parent_id=-2)),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    ids = {p.name: p.playlist_id for p in result.prepared.snapshot.playlists}
    folders = [
        s
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhypHeader)
        if s.chunk.header.playlist_kind_flags & 0x100
    ]
    assert len(folders) == 4
    for selection in folders:
        assert tuple(
            s.chunk.header.track_id for s in selection.find_chunks(MhipHeader)
        ) == (1, 2)
        rules = next(
            c.payload
            for c in selection.chunk.children
            if isinstance(c.payload, MhodSmartRulesPayload)
        )
        assert len(rules.rules) == 1
        rule = rules.rules[0]
        assert rule.field_id == 0x28 and isinstance(rule.data, MhodSmartNumericRuleData)
        assert rule.data.from_value == (
            ids["Nested"] if selection.chunk.header.playlist_id == ids["Root"] else 10
        )
    assert all(
        not p.entries
        for p in result.prepared.snapshot.playlists
        if p.kind is PlaylistKind.FOLDER
    )


def test_podcast_addition_retains_group_and_episode_private_metadata() -> None:
    source = library()
    document = parse_iTunesDB(source.serialize().itunes)
    playlist = next(
        s for s in document.find_chunks(MhypHeader) if s.chunk.header.playlist_id == 10
    )
    group = new_itunes_chunk(
        MHIP,
        MhipHeader(podcast_group_flag=0x100, group_id=7, timestamp=919),
        children=(new_string_mhod(MhodType.TITLE, ""),),
    )
    episodes = tuple(
        replace(c, header=replace(c.header, group_id=8 + i, group_id_ref=7))
        for i, c in enumerate(s.chunk for s in playlist.find_chunks(MhipHeader))
    )
    document = document.replace_chunk(
        playlist,
        replace(
            playlist.chunk,
            header=replace(playlist.chunk.header, playlist_kind_flags=1),
            children=(playlist.chunk.children[0], group, *episodes),
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        playlists=(
            replace(
                source.snapshot.playlists[0],
                entries=(
                    *source.snapshot.playlists[0].entries,
                    PlaylistEntry("added", 2),
                ),
            ),
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    dataset = next(
        s
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhsdHeader)
        if s.chunk.header.dataset_type == 3
    )
    rows = tuple(s.chunk for s in dataset.find_chunks(MhipHeader))
    assert rows[0].header.timestamp == 919
    assert tuple(c.header.timestamp for c in rows[1:4]) == (200, 201, 202)
    assert all(c.header.group_id_ref == 7 for c in rows[1:])
    for child in rows[1:]:
        assert (
            next(
                c.prefix.position
                for c in child.children
                if isinstance(c.prefix, MhodPlaylistPositionPrefix)
            )
            == child.header.group_id
        )


def test_album_artist_composer_and_title_index_keep_native_group_identity() -> None:
    source = library()
    document = parse_iTunesDB(source.serialize().itunes)
    for selection in document.find_chunks(MhitHeader):
        document = document.replace_chunk(
            selection,
            replace(
                selection.chunk,
                header=replace(
                    selection.chunk.header, album_id=5, artist_id_ref=6, composer_id=7
                ),
                children=(
                    *selection.chunk.children,
                    new_string_mhod(MhodType.ALBUM, "Before"),
                    new_string_mhod(MhodType.ARTIST, "Before artist"),
                    new_string_mhod(MhodType.COMPOSER, "Before composer"),
                ),
            ),
        )
    for kind, definition, row in (
        (
            4,
            MHLA,
            new_itunes_chunk(
                MHIA,
                MhiaHeader(album_id=5, sql_id=12345, album_track_db_id=101),
                children=(new_string_mhod(MhodType.ALBUM_ITEM_ALBUM, "Before"),),
            ),
        ),
        (
            8,
            MHLI,
            new_itunes_chunk(
                MHII,
                MhiiHeader(artist_id=6, sql_id=12346),
                children=(
                    new_string_mhod(MhodType.ARTIST_ITEM_ARTIST, "Before artist"),
                ),
            ),
        ),
    ):
        document = document.append_child(
            new_itunes_chunk(
                MHSD,
                MhsdHeader(dataset_type=kind),
                children=(
                    new_itunes_chunk(definition, EmptyChunkHeader(), children=(row,)),
                ),
            )
        )
    master = next(
        s for s in document.find_chunks(MhypHeader) if s.chunk.header.master_flag
    )
    document = document.replace_chunk(
        master,
        master.chunk.append_child(
            new_itunes_chunk(
                MHOD,
                MhodHeader(mhod_type=52),
                prefix=MhodLibraryIndexPrefix(sort_type=3),
                payload=MhodLibraryIndexPayload((0, 1), b"retained"),
            )
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(
                t,
                album="After",
                artist="After artist",
                title="Z" if t.track_id == 1 else "A",
                metadata=replace(t.metadata, composer="After composer"),
            )
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert len(checked.find_chunks(MhiaHeader)) == 1
    assert len(checked.find_chunks(MhiiHeader)) == 1
    album = checked.find_chunks(MhiaHeader)[0].chunk.header
    assert (album.album_id, album.sql_id, album.album_track_db_id) == (5, 12345, 101)
    assert (
        len({s.chunk.header.composer_id for s in checked.find_chunks(MhitHeader)}) == 1
    )
    assert all(s.chunk.header.composer_id != 7 for s in checked.find_chunks(MhitHeader))
    index = next(
        s.chunk.payload
        for s in checked.find_chunks(MhodHeader)
        if isinstance(s.chunk.payload, MhodLibraryIndexPayload)
    )
    assert index.indices == (1, 0) and index.trailing_data == b"retained"


def test_unsupported_rules_and_saved_membership_survive_rename() -> None:
    source = library()
    document = parse_iTunesDB(source.serialize().itunes)
    selection = next(
        s for s in document.find_chunks(MhypHeader) if s.chunk.header.playlist_id == 10
    )
    prefs, rules = smart_chunks(SmartPlaylist(), ())
    from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
        MhodSmartRawRuleData,
        MhodSmartRule,
    )

    rules = replace(
        rules,
        payload=MhodSmartRulesPayload(
            (
                MhodSmartRule(
                    0xFFFF,
                    0xEEEE,
                    0,
                    bytes(40),
                    MhodSmartRawRuleData(b"unknown rule bytes"),
                ),
            ),
            b"private suffix",
        ),
    )
    document = document.replace_chunk(
        selection,
        replace(
            selection.chunk,
            children=(
                *selection.chunk.children[:1],
                prefs,
                rules,
                *selection.chunk.children[1:],
            ),
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    assert (
        source.snapshot.playlists[0].smart is not None
        and not source.snapshot.playlists[0].smart.editable
    )
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Rename only"),),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.playlists[0].track_ids == (1, 2, 1)
    assert (
        b"unknown rule bytes" in result.prepared.itunes
        and b"private suffix" in result.prepared.itunes
    )


def test_pending_playback_context_is_not_silently_consumed() -> None:
    source = library()
    desired = replace(source.snapshot, tracks=tuple(reversed(source.snapshot.tracks)))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(pending_playback_sidecars=True),
    )
    assert result.prepared is None
    assert any(i.code == "resources.playback_sidecars" for i in result.issues)
