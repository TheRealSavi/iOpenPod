"""Every Library write reconciles dataset 2 with authoritative dataset 3."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_playlist_datasets import rows
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.builder.build_iTunesDB import new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
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
    SmartPlaylistReference,
    SmartRule,
    SmartRuleGroup,
    _write_preparation,
)
from iPodDB.library._playlist_mirroring import counterparts_match
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk


def divergent_source(mismatch: str) -> IPodLibrary:
    source = library(mirrored=True)
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(
                -1,
                "Existing Smart Playlist",
                PlaylistKind.SMART,
                smart=SmartPlaylist(
                    rules=SmartRuleGroup(
                        rules=(SmartRule(SmartField.GENRE, SmartOperator.IS, "Rock"),)
                    ),
                ),
                entries=(PlaylistEntry("a", 1), PlaylistEntry("b", 2)),
            ),
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    document = parse_iTunesDB(result.prepared.itunes)
    dataset = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 2
    )
    container = dataset.chunk.children[0]
    master, ordinary, smart = container.children
    children: tuple[ParsedChunk[ChunkHeader], ...]
    if mismatch == "missing":
        children = (master, ordinary)
    elif mismatch == "order":
        children = (master, smart, ordinary)
    elif mismatch == "name":
        children = (
            master,
            ordinary,
            replace(
                smart,
                children=(
                    new_string_mhod(MhodType.TITLE, "Other saved name"),
                    *smart.children[1:],
                ),
            ),
        )
    else:
        assert mismatch == "membership"
        children = (
            master,
            ordinary,
            replace(
                smart,
                children=tuple(
                    c
                    for c in smart.children
                    if not isinstance(c.header, MhipHeader) or c.header.track_id != 2
                ),
            ),
        )
    document = document.replace_chunk(
        dataset,
        replace(dataset.chunk, children=(replace(container, children=children),)),
    )
    return IPodLibrary(write_iTunesDB(document))


@pytest.mark.parametrize("mismatch", ["missing", "name", "membership", "order"])
@pytest.mark.parametrize(
    "operation", ["none", "append", "rename", "folder", "reference"]
)
def test_every_write_reconciles_counterparts_from_dataset3(
    mismatch: str,
    operation: str,
) -> None:
    source = divergent_source(mismatch)
    original_bytes = source.serialize().itunes
    original = parse_iTunesDB(original_bytes)
    desired = source.snapshot
    if operation == "rename":
        desired = replace(
            desired,
            playlists=(
                desired.playlists[0],
                replace(desired.playlists[1], name="Changed"),
            ),
        )
    elif operation != "none":
        added = Playlist(
            -1,
            "New",
            PlaylistKind.FOLDER if operation == "folder" else PlaylistKind.SMART,
            smart=None if operation == "folder" else SmartPlaylist(),
        )
        if operation == "reference":
            added = replace(
                added,
                smart=SmartPlaylist(
                    rules=SmartRuleGroup(
                        rules=(
                            SmartRuleGroup(
                                rules=(
                                    SmartRule(
                                        SmartField.PLAYLIST,
                                        SmartOperator.IS,
                                        SmartPlaylistReference(
                                            desired.playlists[-1].playlist_id
                                        ),
                                    ),
                                )
                            ),
                        )
                    )
                ),
            )
        desired = replace(desired, playlists=(*desired.playlists, added))
    plan = source.analyze(source.begin_draft(desired))
    assert any(
        c.action == "repair" and "playlist_counterparts" in c.fields
        for c in plan.changes
    )
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert counterparts_match(checked)
    assert [s.chunk.header.playlist_id for s in rows(checked, 2)] == [
        s.chunk.header.playlist_id for s in rows(checked, 3)
    ]
    if operation == "none":
        assert result.prepared.snapshot == source.snapshot
        # Authority and its private data survive the repair byte-for-byte.
        for old, new in zip(rows(original, 3), rows(checked, 3), strict=True):
            assert (
                original_bytes[
                    old.chunk.offset : old.chunk.offset
                    + old.chunk.generic_header.length_or_child_count
                ]
                == result.prepared.itunes[
                    new.chunk.offset : new.chunk.offset
                    + new.chunk.generic_header.length_or_child_count
                ]
            )
    repaired = IPodLibrary(result.prepared.itunes)
    repeated = repaired.prepare(repaired.analyze(repaired.begin_draft()))
    assert repeated.prepared is not None, repeated.issues
    assert repeated.prepared.itunes == result.prepared.itunes
    assert source.serialize().itunes == original_bytes


@pytest.mark.parametrize(
    "malformation", ["extra", "duplicate", "master", "duplicate_dataset"]
)
def test_dataset2_only_rows_and_structural_conflicts_are_repaired(
    malformation: str,
) -> None:
    source = library(mirrored=True)
    document = parse_iTunesDB(source.serialize().itunes)
    dataset = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 2
    )
    container = dataset.chunk.children[0]
    _master, ordinary = container.children
    assert isinstance(ordinary.header, MhypHeader)
    if malformation == "duplicate_dataset":
        document = document.append_child(dataset.chunk)
    else:
        children: tuple[ParsedChunk[ChunkHeader], ...]
        if malformation == "master":
            children = (ordinary,)
        elif malformation == "duplicate":
            children = (*container.children, ordinary)
        else:
            children = (
                *container.children,
                replace(ordinary, header=replace(ordinary.header, playlist_id=9999)),
            )
        document = document.replace_chunk(
            dataset,
            replace(dataset.chunk, children=(replace(container, children=children),)),
        )
    source = IPodLibrary(write_iTunesDB(document))
    before = source.serialize().itunes
    result = source.prepare(source.analyze(source.begin_draft()))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert counterparts_match(checked)
    assert (
        len(
            [
                s
                for s in checked.find_chunks(MhsdHeader)
                if s.chunk.header.dataset_type == 2
            ]
        )
        == 1
    )
    assert [s.chunk.header.playlist_id for s in rows(checked, 2)] == [1000, 10]
    assert source.serialize().itunes == before


@pytest.mark.parametrize("corruption", ["retained", "missing_new", "extra", "order"])
def test_verification_rejects_divergent_output_after_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    source = divergent_source("name")
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(-1, "New", PlaylistKind.PLAYLIST),
        ),
    )
    corrupted = False

    def corrupt(document: DatabaseDocument[MhbdHeader]) -> bytes:
        nonlocal corrupted
        if corrupted:
            return write_iTunesDB(document)
        corrupted = True
        dataset = next(
            s
            for s in document.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == 2
        )
        container = dataset.chunk.children[0]
        children = list(container.children)
        if corruption == "missing_new":
            children.pop()
        elif corruption == "extra":
            row = rows(document, 3)[2].chunk
            children.append(replace(row, header=replace(row.header, playlist_id=9999)))
        elif corruption == "order":
            children[1], children[2] = children[2], children[1]
        else:
            children[2] = replace(
                children[2],
                children=(new_string_mhod(MhodType.TITLE, "Unexpected edit"),),
            )
        document = document.replace_chunk(
            dataset,
            replace(
                dataset.chunk, children=(replace(container, children=tuple(children)),)
            ),
        )
        return write_iTunesDB(document)

    original_bytes = source.serialize().itunes
    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(i.code == "verification.playlist_mirror" for i in result.issues), (
        result.issues
    )
    assert source.serialize().itunes == original_bytes


def test_ambiguous_dataset3_authority_cannot_publish_a_divergent_noop() -> None:
    source = library(mirrored=True)
    document = parse_iTunesDB(source.serialize().itunes)
    dataset3 = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 3
    )
    source = IPodLibrary(write_iTunesDB(document.append_child(dataset3.chunk)))
    original_bytes = source.serialize().itunes
    result = source.prepare(source.analyze(source.begin_draft()))
    assert result.prepared is None
    assert any(i.code == "library.ambiguous_dataset" for i in result.issues)
    assert source.serialize().itunes == original_bytes
