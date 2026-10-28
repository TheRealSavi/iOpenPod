"""Firmware playlist relationships through the public draft/preparation interface."""

import base64
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.device_time import TimeConversion
from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk, new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhlp import DEFINITION as MHLP
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    MhodOpaquePayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import DEFINITION as MHYP
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    Playlist,
    PlaylistEntry,
    PlaylistKind,
    SmartField,
    SmartOperator,
    SmartPlaylist,
    SmartRule,
    SmartRuleGroup,
    _write_preparation,
)
from iPodDB.library._reconcile import reconcile
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.writing import (
    IdentityMapping,
    IssueSeverity,
    PreparedLibrary,
    WriteIssue,
    WriteResources,
)
from iPodDB.shared.chunk import (
    ChunkHeader,
    ChunkSelection,
    DatabaseDocument,
    EmptyChunkHeader,
    ParsedChunk,
)


def rows(
    document: DatabaseDocument[MhbdHeader], kind: int
) -> tuple[ChunkSelection[MhbdHeader, MhypHeader], ...]:
    dataset = next(
        s
        for s in document.find_chunks(MhsdHeader)
        if s.chunk.header.dataset_type == kind
    )
    return dataset.find_chunks(MhypHeader)


def prepare(
    document: DatabaseDocument[MhbdHeader], desired: LibrarySnapshot
) -> tuple[PreparedLibrary, DatabaseDocument[MhbdHeader]]:
    source = IPodLibrary(write_iTunesDB(document))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    return result.prepared, parse_iTunesDB(result.prepared.itunes)


@pytest.mark.parametrize("mirrored", [False, True])
def test_first_playlist_has_both_counterparts_and_native_identity_fields(
    mirrored: bool,
) -> None:
    document = parse_iTunesDB(library(mirrored=mirrored).serialize().itunes)
    document = replace(document, header=replace(document.header, db_id_2=0x1234567890))
    for dataset in document.find_chunks(MhsdHeader):
        if dataset.chunk.header.dataset_type not in (2, 3):
            continue
        container = dataset.chunk.children[0]
        document = document.replace_chunk(
            dataset,
            replace(
                dataset.chunk,
                children=(replace(container, children=(container.children[0],)),),
            ),
        )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        playlists=(
            Playlist(
                -1, "New", PlaylistKind.PLAYLIST, entries=(PlaylistEntry("a", 1),)
            ),
        ),
    )
    prepared, checked = prepare(document, desired)
    identity = prepared.snapshot.playlists[0].playlist_id
    for kind in (2, 3):
        master, playlist = rows(checked, kind)
        assert master.chunk.header.master_flag == 1
        assert playlist.chunk.header.playlist_id == identity
        assert playlist.chunk.header.playlist_id_2 == identity
        assert playlist.chunk.header.db_id_2 == 0x1234567890
        assert tuple(
            s.chunk.header.track_id for s in playlist.find_chunks(MhipHeader)
        ) == (1,)


@pytest.mark.parametrize("malformation", ["missing", "multiple", "position"])
def test_ambiguous_master_warns_on_noop_and_blocks_dependent_edits(
    malformation: str,
) -> None:
    document = parse_iTunesDB(library().serialize().itunes)
    dataset = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 3
    )
    container = dataset.chunk.children[0]
    master, playlist = container.children
    children: tuple[ParsedChunk[ChunkHeader], ...]
    if malformation == "missing":
        children = (playlist,)
    elif malformation == "multiple":
        duplicate = new_itunes_chunk(MHYP, MhypHeader(master_flag=1, playlist_id=1001))
        children = (master, duplicate, playlist)
    else:
        children = (playlist, master)
    document = document.replace_chunk(
        dataset,
        replace(dataset.chunk, children=(replace(container, children=children),)),
    )
    source = IPodLibrary(write_iTunesDB(document))
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared and noop.prepared.itunes == source.serialize().itunes
    assert any(
        i.severity is IssueSeverity.WARNING and i.code.startswith("playlist.master_")
        for i in noop.issues
    )
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Changed"),),
    )
    changed = source.prepare(source.analyze(source.begin_draft(desired)))
    assert changed.prepared is None
    assert any(
        i.severity is IssueSeverity.ERROR and i.code.startswith("playlist.master_")
        for i in changed.issues
    )


def podcast_source() -> IPodLibrary:
    document = parse_iTunesDB(library(mirrored=True).serialize().itunes)
    for selection in document.find_chunks(MhypHeader):
        if selection.chunk.header.master_flag:
            continue
        document = document.replace_chunk(
            selection,
            replace(
                selection.chunk,
                header=replace(selection.chunk.header, playlist_kind_flags=1),
                children=(new_string_mhod(MhodType.TITLE, "Not named Podcasts"),),
            ),
        )
    for track in document.find_chunks(MhitHeader):
        document = document.replace_chunk(
            track,
            replace(
                track.chunk,
                header=replace(track.chunk.header, media_type=4),
                children=(
                    *track.chunk.children,
                    new_string_mhod(MhodType.ALBUM, str(track.chunk.header.track_id)),
                ),
            ),
        )
    return IPodLibrary(write_iTunesDB(document))


def test_special_podcasts_marker_projects_as_system_managed_independent_of_name() -> (
    None
):
    playlist = podcast_source().snapshot.playlists[0]

    assert playlist.name == "Not named Podcasts"
    assert playlist.system_managed


def populated_podcasts(
    *, with_user_playlist: bool = True, with_flat_counterpart: bool = False
) -> IPodLibrary:
    source = podcast_source()
    desired = replace(
        source.snapshot,
        playlists=(
            replace(
                source.snapshot.playlists[0],
                entries=(
                    PlaylistEntry("a", 1),
                    PlaylistEntry("b", 2),
                    PlaylistEntry("c", 1),
                ),
            ),
        ),
    )
    _, document = prepare(parse_iTunesDB(source.serialize().itunes), desired)
    for kind in (2, 3):
        podcast = rows(document, kind)[1]
        document = document.replace_chunk(
            podcast,
            replace(
                podcast.chunk,
                header=replace(
                    podcast.chunk.header, unk_mhyp_0x54=bytes([kind, 1, 2, 3])
                ),
                children=(
                    new_itunes_chunk(
                        MHOD,
                        MhodHeader(mhod_type=999),
                        payload=MhodOpaquePayload(b"private podcast metadata"),
                    ),
                    *podcast.chunk.children,
                ),
            ),
        )
    user = rows(parse_iTunesDB(library().serialize().itunes), 3)[1].chunk
    user = replace(user, header=replace(user.header, playlist_id=20))
    for kind in (2, 3):
        dataset = next(
            s
            for s in document.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == kind
        )
        container = dataset.chunk.children[0]
        retained = (
            container.children[:1]
            if kind == 2 and not with_flat_counterpart
            else container.children
        )
        document = document.replace_chunk(
            dataset,
            replace(
                dataset.chunk,
                children=(
                    replace(
                        container,
                        children=(*retained, user) if with_user_playlist else retained,
                    ),
                ),
            ),
        )
    return IPodLibrary(write_iTunesDB(document))


@pytest.mark.parametrize("kind", [PlaylistKind.PLAYLIST, PlaylistKind.SMART])
@pytest.mark.parametrize("with_user_playlist", [False, True])
@pytest.mark.parametrize("with_flat_counterpart", [False, True])
def test_new_playlist_completes_podcast_counterparts_and_preserves_existing_rows(
    kind: PlaylistKind, with_user_playlist: bool, with_flat_counterpart: bool
) -> None:
    source = populated_podcasts(
        with_user_playlist=with_user_playlist,
        with_flat_counterpart=with_flat_counterpart,
    )
    original_bytes = source.serialize().itunes
    original = parse_iTunesDB(original_bytes)
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared is not None, noop.issues
    assert noop.prepared.itunes == original_bytes
    smart = (
        SmartPlaylist(
            rules=SmartRuleGroup(
                rules=(
                    SmartRule(SmartField.DATE_ADDED, SmartOperator.IN_LAST, 1209600),
                    SmartRule(SmartField.GENRE, SmartOperator.CONTAINS, "House"),
                )
            )
        )
        if kind is PlaylistKind.SMART
        else None
    )
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(
                -1,
                "New",
                kind,
                entries=(PlaylistEntry("new-a", 1), PlaylistEntry("new-b", 2)),
                smart=smart,
            ),
        ),
    )
    plan = source.analyze(source.begin_draft(desired))
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    output_bytes = result.prepared.itunes
    checked = parse_iTunesDB(output_bytes)
    added = result.prepared.snapshot.playlists[-1]
    assert added.track_ids == (1, 2)
    assert added.smart == smart
    for dataset in (2, 3):
        output_rows = {s.chunk.header.playlist_id: s for s in rows(checked, dataset)}
        assert added.playlist_id in output_rows
        assert 10 in output_rows
        assert tuple(
            s.chunk.header.track_id
            for s in output_rows[added.playlist_id].find_chunks(MhipHeader)
        ) == (1, 2)
        for row in rows(original, dataset):
            before = row.chunk
            after = output_rows[before.header.playlist_id].chunk
            assert (
                original_bytes[
                    before.offset : before.offset
                    + before.generic_header.length_or_child_count
                ]
                == output_bytes[
                    after.offset : after.offset
                    + after.generic_header.length_or_child_count
                ]
            )
    flat = next(s for s in rows(checked, 2) if s.chunk.header.playlist_id == 10)
    grouped = next(s for s in rows(original, 3) if s.chunk.header.playlist_id == 10)
    flat_episodes = [s.chunk for s in flat.find_chunks(MhipHeader)]
    grouped_episodes = [
        s.chunk for s in grouped.find_chunks(MhipHeader) if not s.chunk.header.is_group
    ]
    assert tuple(c.header.track_id for c in flat_episodes) == (1, 1, 2)
    assert all(
        not c.header.is_group and not c.header.group_id_ref for c in flat_episodes
    )
    if not with_flat_counterpart:
        assert flat.chunk.header == replace(
            grouped.chunk.header, mhip_child_count=len(flat_episodes)
        )
        for episode, original_episode in zip(
            flat_episodes, grouped_episodes, strict=True
        ):
            assert episode.header == replace(
                original_episode.header,
                group_id_ref=0,
                mhip_persistent_id=episode.header.mhip_persistent_id,
            )
            assert [c.prefix for c in episode.children] == [
                c.prefix for c in original_episode.children
            ]
        assert [
            output_bytes[c.offset : c.offset + c.generic_header.length_or_child_count]
            for c in flat.chunk.children
            if not isinstance(c.header, MhipHeader)
        ] == [
            original_bytes[c.offset : c.offset + c.generic_header.length_or_child_count]
            for c in grouped.chunk.children
            if not isinstance(c.header, MhipHeader)
        ]
        fresh_ids = {c.header.mhip_persistent_id for c in flat_episodes}
        assert len(fresh_ids) == len(flat_episodes)
        assert 0 not in fresh_ids
        assert fresh_ids.isdisjoint(
            s.chunk.header.mhip_persistent_id for s in original.find_chunks(MhipHeader)
        )
    assert plan.resolution is not None
    companion_effects = [
        e for e in plan.resolution.effects if e.code == "playlist.companion"
    ]
    assert len(companion_effects) == (0 if with_flat_counterpart else 1)
    if companion_effects:
        assert companion_effects[0].record_id == 10
        assert companion_effects[0].dataset == 2
        assert companion_effects[0].causes
    assert source.serialize().itunes == original_bytes


@pytest.mark.parametrize("mismatch", ["missing", "conflicting"])
def test_dataset3_only_podcasts_does_not_exempt_ordinary_playlist_mirrors(
    mismatch: str,
) -> None:
    source = populated_podcasts()
    document = parse_iTunesDB(source.serialize().itunes)
    dataset = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 2
    )
    container = dataset.chunk.children[0]
    master, user = container.children
    children: tuple[ParsedChunk[ChunkHeader], ...]
    if mismatch == "missing":
        children = (master,)
    else:
        children = (
            master,
            replace(
                user,
                children=(
                    new_string_mhod(MhodType.TITLE, "Conflict"),
                    *user.children[1:],
                ),
            ),
        )
    document = document.replace_chunk(
        dataset,
        replace(dataset.chunk, children=(replace(container, children=children),)),
    )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(-1, "New", PlaylistKind.PLAYLIST),
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(issue.code == "playlist.ambiguous_mirror" for issue in result.issues)


@pytest.mark.parametrize("missing_dataset", [False, True])
def test_new_podcast_counterpart_receives_edits_in_the_same_write(
    missing_dataset: bool,
) -> None:
    source = populated_podcasts()
    if missing_dataset:
        document = parse_iTunesDB(source.serialize().itunes)
        document = replace(
            document,
            children=tuple(
                c
                for c in document.children
                if not isinstance(c.header, MhsdHeader) or c.header.dataset_type != 2
            ),
        )
        source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        playlists=tuple(
            replace(
                p,
                name="Renamed Podcasts",
                entries=(PlaylistEntry("edited", 2),),
            )
            if p.playlist_id == 10
            else p
            for p in source.snapshot.playlists
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    for kind in (2, 3):
        podcast = next(
            s for s in rows(checked, kind) if s.chunk.header.playlist_id == 10
        )
        episodes = [
            s.chunk
            for s in podcast.find_chunks(MhipHeader)
            if not s.chunk.header.is_group
        ]
        assert [c.header.track_id for c in episodes] == [2]
    assert (
        next(p.name for p in result.prepared.snapshot.playlists if p.playlist_id == 10)
        == "Renamed Podcasts"
    )


@pytest.mark.parametrize(
    ("corruption", "code"),
    [
        ("missing", "playlist_missing_mirror"),
        ("group", "podcast_dataset"),
        ("row_id", "podcast_row_mirror"),
        ("position", "podcast_position_mirror"),
    ],
)
def test_verification_rejects_a_missing_or_invalid_new_podcast_counterpart(
    monkeypatch: pytest.MonkeyPatch, corruption: str, code: str
) -> None:
    source = populated_podcasts()
    original_bytes = source.serialize().itunes
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(-1, "New", PlaylistKind.PLAYLIST),
        ),
    )

    def corrupt(document: DatabaseDocument[MhbdHeader]) -> bytes:
        podcast = next(
            (s for s in rows(document, 2) if s.chunk.header.playlist_id == 10), None
        )
        if podcast is None:
            return write_iTunesDB(document)
        if corruption == "missing":
            dataset = next(
                s
                for s in document.find_chunks(MhsdHeader)
                if s.chunk.header.dataset_type == 2
            )
            container = dataset.chunk.children[0]
            document = document.replace_chunk(
                dataset,
                replace(
                    dataset.chunk,
                    children=(
                        replace(
                            container,
                            children=tuple(
                                c for c in container.children if c is not podcast.chunk
                            ),
                        ),
                    ),
                ),
            )
        else:
            episode = podcast.find_chunks(MhipHeader)[0]
            if corruption == "position":
                replacement = replace(
                    episode.chunk,
                    children=tuple(
                        replace(c, prefix=replace(c.prefix, position=999))
                        if isinstance(c.prefix, MhodPlaylistPositionPrefix)
                        else c
                        for c in episode.chunk.children
                    ),
                )
            else:
                replacement = replace(
                    episode.chunk,
                    header=replace(episode.chunk.header, group_id_ref=999)
                    if corruption == "group"
                    else replace(episode.chunk.header, group_id=999),
                )
            document = document.replace_chunk(episode, replacement)
        return write_iTunesDB(document)

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(i.code == f"verification.{code}" for i in result.issues)
    assert source.serialize().itunes == original_bytes


@pytest.mark.parametrize("track_ids", [(1,), (1, 2, 1)])
def test_empty_podcasts_gains_groups_only_in_dataset3(
    track_ids: tuple[int, ...],
) -> None:
    source = podcast_source()
    playlist = replace(
        source.snapshot.playlists[0],
        entries=tuple(PlaylistEntry(str(i), t) for i, t in enumerate(track_ids)),
    )
    desired = replace(source.snapshot, playlists=(playlist,))
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    expected = (1,) if len(track_ids) == 1 else (1, 1, 2)
    assert result.prepared.snapshot.playlists[0].track_ids == expected
    assert not any(
        issue.code == "playlist.podcast_group_order" for issue in result.issues
    )
    checked = parse_iTunesDB(result.prepared.itunes)
    standard = rows(checked, 2)[1].find_chunks(MhipHeader)
    grouped = rows(checked, 3)[1].find_chunks(MhipHeader)
    assert tuple(s.chunk.header.track_id for s in standard) == expected
    assert all(
        not s.chunk.header.is_group and not s.chunk.header.group_id_ref
        for s in standard
    )
    assert sum(s.chunk.header.is_group for s in grouped) == len(set(track_ids))
    assert all(s.chunk.header.unchecked_override == 0 for s in (*standard, *grouped))
    assert all(
        s.chunk.header.group_marker == 1 for s in grouped if s.chunk.header.is_group
    )
    assert all(s.chunk.header.group_id for s in grouped)
    grouped_ids = [s.chunk.header.group_id for s in grouped]
    assert grouped_ids == sorted(set(grouped_ids))
    assert [s.chunk.header.group_id for s in standard] == [
        s.chunk.header.group_id for s in grouped if s.chunk.header.track_id
    ]


@pytest.mark.parametrize("category", [0, 2, 3, 4, 5, 6, 7])
def test_dataset5_flags_and_same_ids_do_not_make_it_a_folder_or_master(
    category: int,
) -> None:
    document = parse_iTunesDB(library(mirrored=True).serialize().itunes)
    category_row = new_itunes_chunk(
        MHYP,
        MhypHeader(
            playlist_id=10,
            master_flag=1,
            playlist_kind_flags=0x100,
            mhsd_5_type=category,
            phase_game_flag=category,
            unk_mhyp_0x54=b"\x01\x00\x00\x00",
        ),
        children=(new_string_mhod(MhodType.TITLE, "Firmware"),),
    )
    document = document.append_child(
        new_itunes_chunk(
            MHSD,
            MhsdHeader(dataset_type=5),
            children=(
                new_itunes_chunk(MHLP, EmptyChunkHeader(), children=(category_row,)),
            ),
        )
    )
    source = IPodLibrary(write_iTunesDB(document))
    original = parse_iTunesDB(source.serialize().itunes)
    category_before = rows(original, 5)[0].chunk
    desired = replace(
        source.snapshot,
        playlists=(
            replace(source.snapshot.playlists[0], kind=PlaylistKind.FOLDER, entries=()),
            Playlist(
                -1,
                "Child",
                PlaylistKind.PLAYLIST,
                parent_id=10,
                entries=(PlaylistEntry("a", 1),),
            ),
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    category_after = rows(parse_iTunesDB(result.prepared.itunes), 5)[0].chunk
    assert (
        source.serialize().itunes[
            category_before.offset : category_before.offset
            + category_before.generic_header.length_or_child_count
        ]
        == result.prepared.itunes[
            category_after.offset : category_after.offset
            + category_after.generic_header.length_or_child_count
        ]
    )


def test_verification_rejects_missing_extended_identity_after_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = library(mirrored=True)
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(-1, "New", PlaylistKind.PLAYLIST),
        ),
    )

    def corrupt(document: DatabaseDocument[MhbdHeader]) -> bytes:
        data = bytearray(write_iTunesDB(document))
        checked = parse_iTunesDB(bytes(data))
        for selection in checked.find_chunks(MhypHeader):
            if selection.chunk.header.playlist_id > 1000:
                offset = selection.chunk.offset
                data[offset + 0x44 : offset + 0x4C] = bytes(8)
        return bytes(data)

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(i.code == "verification.playlist_native_identity" for i in result.issues)
    assert source.snapshot.playlists[0].name == "Playlist"


def test_new_empty_library_gets_master_before_first_user_playlist() -> None:
    document = parse_iTunesDB(library().serialize().itunes)
    document = replace(
        document,
        children=tuple(
            c
            for c in document.children
            if not isinstance(c.header, MhsdHeader)
            or c.header.dataset_type not in (2, 3)
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        device_name="Device",
        playlists=(Playlist(-1, "New", PlaylistKind.PLAYLIST),),
    )
    _, checked = prepare(document, desired)
    master, playlist = rows(checked, 2)
    assert master.chunk.header.master_flag == 1
    assert tuple(s.chunk.header.track_id for s in master.find_chunks(MhipHeader)) == (
        1,
        2,
    )
    assert not playlist.chunk.header.master_flag
    assert {
        c.header.mhod_type
        for c in master.chunk.children
        if isinstance(c.header, MhodHeader)
    } >= {52, 53, 100}


def test_podcast_track_changes_create_and_update_special_membership() -> None:
    source = library(mirrored=True)
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, podcast=t.track_id == 1))
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert not any(
        issue.code == "playlist.podcast_membership" for issue in result.issues
    )
    podcasts = next(
        p for p in result.prepared.snapshot.playlists if p.name == "Podcasts"
    )
    assert podcasts.track_ids == (1,)
    checked = parse_iTunesDB(result.prepared.itunes)
    for kind in (2, 3):
        playlist = next(
            s
            for s in rows(checked, kind)
            if s.chunk.header.playlist_id == podcasts.playlist_id
        )
        assert playlist.chunk.header.playlist_kind_flags & 1
        assert sum(
            bool(s.chunk.header.is_group) for s in playlist.find_chunks(MhipHeader)
        ) == (1 if kind == 3 else 0)
    reloaded = IPodLibrary(result.prepared.itunes)
    cleared = replace(
        reloaded.snapshot,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, podcast=False))
            for t in reloaded.snapshot.tracks
        ),
    )
    updated = reloaded.prepare(reloaded.analyze(reloaded.begin_draft(cleared)))
    assert updated.prepared is not None, updated.issues
    assert not any(
        issue.code == "playlist.podcast_membership" for issue in updated.issues
    )
    assert (
        next(
            p
            for p in updated.prepared.snapshot.playlists
            if p.playlist_id == podcasts.playlist_id
        ).entries
        == ()
    )


def test_new_playlist_preferences_match_fixed_original_writer_bytes() -> None:
    evidence = json.loads(
        (
            Path(__file__).parents[2] / "fixtures/writing/playlists-original.json"
        ).read_text(encoding="utf-8")
    )
    source = library(mirrored=True)
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(-1, "New", PlaylistKind.PLAYLIST),
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    for kind in (2, 3):
        playlist = next(
            s for s in rows(checked, kind) if s.chunk.header.playlist_id > 1000
        )
        prefs = next(
            c
            for c in playlist.chunk.children
            if isinstance(c.header, MhodHeader) and c.header.mhod_type == 100
        )
        assert isinstance(prefs.payload, MhodOpaquePayload)
        assert result.prepared.itunes[
            prefs.offset : prefs.offset + prefs.generic_header.length_or_child_count
        ] == bytes.fromhex(evidence["playlist_preferences"])


@pytest.mark.parametrize("name", ["regular", "folder", "podcasts", "rentals"])
def test_fixed_original_playlist_chunks_roundtrip_exactly(name: str) -> None:
    evidence = json.loads(
        (
            Path(__file__).parents[2] / "fixtures/writing/playlists-original.json"
        ).read_text(encoding="utf-8")
    )
    native = base64.b64decode(evidence["cases"][name])
    source_bytes = library().serialize().itunes
    source = parse_iTunesDB(source_bytes)
    dataset = next(
        s for s in source.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 3
    )
    playlist = rows(source, 3)[1].chunk
    end = playlist.offset + playlist.generic_header.length_or_child_count
    data = bytearray(source_bytes[: playlist.offset] + native + source_bytes[end:])
    delta = len(native) - playlist.generic_header.length_or_child_count
    struct.pack_into("<I", data, 8, len(data))
    struct.pack_into(
        "<I",
        data,
        dataset.chunk.offset + 8,
        dataset.chunk.generic_header.length_or_child_count + delta,
    )
    if name == "rentals":
        struct.pack_into("<I", data, dataset.chunk.offset + 12, 5)
    loaded = IPodLibrary(bytes(data))
    result = loaded.prepare(loaded.analyze(loaded.begin_draft()))
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == bytes(data)


def test_distinct_podcast_mirror_order_survives_a_rename() -> None:
    source = podcast_source()
    desired = replace(
        source.snapshot,
        playlists=(
            replace(
                source.snapshot.playlists[0],
                entries=(
                    PlaylistEntry("a", 1),
                    PlaylistEntry("b", 1),
                    PlaylistEntry("c", 2),
                ),
            ),
        ),
    )
    ready = source.prepare(source.analyze(source.begin_draft(desired))).prepared
    assert ready is not None
    document = parse_iTunesDB(ready.itunes)
    standard = rows(document, 2)[1]
    entries = [c for c in standard.chunk.children if isinstance(c.header, MhipHeader)]
    metadata = [
        c for c in standard.chunk.children if not isinstance(c.header, MhipHeader)
    ]
    document = document.replace_chunk(
        standard,
        replace(
            standard.chunk, children=(*metadata, entries[0], entries[2], entries[1])
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Renamed"),),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    output = parse_iTunesDB(result.prepared.itunes)
    assert tuple(
        s.chunk.header.track_id for s in rows(output, 2)[1].find_chunks(MhipHeader)
    ) == (1, 2, 1)
    assert result.prepared.snapshot.playlists[0].track_ids == (1, 1, 2)


def test_large_playlist_creation_extends_every_mirror() -> None:
    source = library(mirrored=True)
    additions = tuple(
        Playlist(
            -i,
            f"Playlist {i}",
            PlaylistKind.PLAYLIST,
            entries=(PlaylistEntry("a", 1), PlaylistEntry("b", 2)),
        )
        for i in range(1, 1001)
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(
                replace(
                    source.snapshot, playlists=(*source.snapshot.playlists, *additions)
                )
            )
        )
    )
    assert result.prepared is not None, result.issues
    document = parse_iTunesDB(result.prepared.itunes)
    assert len(rows(document, 2)) == len(rows(document, 3)) == 1002


def test_legacy_dataset2_edit_does_not_invent_podcast_dataset() -> None:
    document = parse_iTunesDB(library().serialize().itunes)
    ds = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 3
    )
    document = document.replace_chunk(
        ds, replace(ds.chunk, header=replace(ds.chunk.header, dataset_type=2))
    )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Renamed"),),
    )
    _, checked = prepare(document, desired)
    assert [s.chunk.header.dataset_type for s in checked.find_chunks(MhsdHeader)] == [
        1,
        2,
        999,
    ]


def test_unrelated_track_text_edit_preserves_missing_master_with_warning() -> None:
    document = parse_iTunesDB(library().serialize().itunes)
    ds = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 3
    )
    container = ds.chunk.children[0]
    document = document.replace_chunk(
        ds,
        replace(
            ds.chunk, children=(replace(container, children=(container.children[1],)),)
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, comment="Words"))
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert all(i.severity is IssueSeverity.WARNING for i in result.issues)
    assert not any(
        s.chunk.header.master_flag
        for s in rows(parse_iTunesDB(result.prepared.itunes), 3)
    )


def test_dataset5_track_deletion_preserves_category_fields_and_metadata() -> None:
    document = parse_iTunesDB(library(mirrored=True).serialize().itunes)
    category = rows(document, 3)[1].chunk
    category = replace(
        category,
        header=replace(
            category.header,
            master_flag=1,
            mhsd_5_type=7,
            phase_game_flag=7,
            unk_mhyp_0x54=b"\x01\x00\x00\x00",
        ),
    )
    document = document.append_child(
        new_itunes_chunk(
            MHSD,
            MhsdHeader(dataset_type=5),
            children=(
                new_itunes_chunk(MHLP, EmptyChunkHeader(), children=(category,)),
            ),
        )
    )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        tracks=(source.snapshot.tracks[1],),
        playlists=(
            replace(
                source.snapshot.playlists[0],
                entries=(source.snapshot.playlists[0].entries[1],),
            ),
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    retained = rows(parse_iTunesDB(result.prepared.itunes), 5)[0]
    assert (
        retained.chunk.header.mhsd_5_type == retained.chunk.header.phase_game_flag == 7
    )
    assert retained.chunk.header.unk_mhyp_0x54 == b"\x01\x00\x00\x00"
    assert tuple(
        s.chunk.header.timestamp for s in retained.find_chunks(MhipHeader)
    ) == (201,)


def test_verification_rejects_a_dropped_existing_mirror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = library(mirrored=True)
    original_bytes = source.serialize().itunes
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Renamed"),),
    )

    def omit(
        document: DatabaseDocument[MhbdHeader],
        resolved: ResolvedWrite,
        resources: WriteResources,
        issues: list[WriteIssue],
        device_time: TimeConversion = 0,
    ) -> tuple[DatabaseDocument[MhbdHeader], tuple[IdentityMapping, ...]]:
        candidate, identities = reconcile(
            document,
            resolved,
            resources,
            issues,
            device_time,
        )
        dataset = next(
            s
            for s in candidate.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == 2
        )
        container = dataset.chunk.children[0]
        candidate = candidate.replace_chunk(
            dataset,
            replace(
                dataset.chunk,
                children=(replace(container, children=(container.children[0],)),),
            ),
        )
        return candidate, identities

    monkeypatch.setattr(_write_preparation, "reconcile", omit)
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(i.code == "verification.playlist_missing_mirror" for i in result.issues)
    assert source.serialize().itunes == original_bytes


def test_existing_dataset2_podcasts_updates_without_creating_dataset3() -> None:
    document = parse_iTunesDB(podcast_source().serialize().itunes)
    document = replace(
        document,
        children=tuple(
            c
            for c in document.children
            if not isinstance(c.header, MhsdHeader) or c.header.dataset_type != 3
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(source.snapshot, tracks=tuple(reversed(source.snapshot.tracks)))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert not any(
        s.chunk.header.dataset_type == 3 for s in checked.find_chunks(MhsdHeader)
    )
    assert result.prepared.snapshot.playlists[0].track_ids == (2, 1)
    assert all(
        not s.chunk.header.is_group for s in rows(checked, 2)[1].find_chunks(MhipHeader)
    )
