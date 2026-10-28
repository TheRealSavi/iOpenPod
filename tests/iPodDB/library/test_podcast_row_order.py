"""Podcast row numbering follows serialized group/occurrence order."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_finder_podcasts import finder_source
from tests.iPodDB.library.test_playlist_datasets import rows

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.cdb import compress_iTunesCDB, decompress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, PlaylistEntry, WriteTarget, _write_preparation
from iPodDB.shared.chunk import DatabaseDocument, ParsedChunk


def numbering_source(
    layout: str, *, compressed: bool = False, highest_id: int = 5000
) -> IPodLibrary:
    document = parse_iTunesDB(finder_source().serialize().itunes)
    for kind in (3, 2):
        master, playlist = rows(document, kind)
        document = document.replace_chunk(
            master,
            replace(
                master.chunk,
                children=(
                    *master.chunk.children,
                    *(
                        new_itunes_chunk(
                            MHIP,
                            MhipHeader(
                                track_id=track.chunk.header.track_id,
                                group_id=highest_id - index,
                            ),
                        )
                        for index, track in enumerate(document.find_chunks(MhitHeader))
                    ),
                ),
            ),
        )
        items: list[ParsedChunk[MhipHeader]] = []
        for occurrence in playlist.find_chunks(MhipHeader):
            item = occurrence.chunk
            group = bool(item.header.is_group)
            if group and layout == "flat":
                continue
            show = item.header.group_id // 100
            group_id = 73 + 2 * show if layout == "ordered" else 90 + show
            row_id = (
                group_id
                if group
                else (group_id + 1 if layout == "ordered" else 75 + show)
            )
            items.append(
                replace(
                    item,
                    header=replace(
                        item.header,
                        group_id=row_id,
                        group_id_ref=group_id
                        if kind == 3 and not group and layout != "flat"
                        else 0,
                        mhip_persistent_id=10000 + show
                        if group
                        else 1000 + 10 * kind + show,
                        timestamp=400 + show + kind,
                        unk_mhip_0x12=0x8001,
                    ),
                )
            )
        if kind == 2:
            items.reverse()  # Established flat/grouped orders need not agree.
        document = document.replace_chunk(
            playlist,
            replace(
                playlist.chunk,
                children=(
                    *(
                        c
                        for c in playlist.chunk.children
                        if not isinstance(c.header, MhipHeader)
                    ),
                    *items,
                ),
            ),
        )
    if compressed:
        document = replace(
            document,
            children=tuple(
                c
                for c in document.children
                if not isinstance(c.header, MhsdHeader) or c.header.dataset_type != 2
            ),
        )
    data = write_iTunesDB(document)
    return IPodLibrary(compress_iTunesCDB(data) if compressed else data)


def assert_numbering(document: DatabaseDocument[MhbdHeader]) -> None:
    grouped = [s.chunk for s in rows(document, 3)[1].find_chunks(MhipHeader)]
    ids = [item.header.group_id for item in grouped]
    assert ids == sorted(set(ids)) and all(ids)
    parent = 0
    episode_ids: dict[int, list[tuple[int, tuple[int, ...]]]] = {}
    for item in grouped:
        if item.header.is_group:
            assert item.header.track_id == 0
            parent = item.header.group_id
        else:
            assert 0 < parent < item.header.group_id
            assert item.header.group_id_ref == parent
            positions = tuple(
                c.prefix.position
                for c in item.children
                if isinstance(c.prefix, MhodPlaylistPositionPrefix)
            )
            assert len(positions) == 1
            episode_ids.setdefault(item.header.track_id, []).append(
                (item.header.group_id, positions)
            )
    flat_ids: dict[int, list[tuple[int, tuple[int, ...]]]] = {}
    for occurrence in rows(document, 2)[1].find_chunks(MhipHeader):
        item = occurrence.chunk
        assert not item.header.is_group and not item.header.group_id_ref
        flat_ids.setdefault(item.header.track_id, []).append(
            (
                item.header.group_id,
                tuple(
                    c.prefix.position
                    for c in item.children
                    if isinstance(c.prefix, MhodPlaylistPositionPrefix)
                ),
            )
        )
    assert flat_ids == episode_ids


@pytest.mark.parametrize("layout", ("flat", "backwards"))
@pytest.mark.parametrize("compressed", (False, True))
def test_explicit_repair_orders_rows_and_preserves_occurrence_metadata(
    layout: str, compressed: bool
) -> None:
    source = numbering_source(layout, compressed=compressed)
    original = source.serialize().itunes
    before = parse_iTunesDB(
        decompress_iTunesCDB(original).logical_bytes if compressed else original
    )
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared and noop.prepared.itunes == original

    plan = source.analyze(
        source.begin_draft(repair_podcast_links=True),
        WriteTarget(compressed_database=compressed),
    )
    assert any(change.action == "repair" for change in plan.changes)
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    data = result.prepared.itunes
    checked = parse_iTunesDB(
        decompress_iTunesCDB(data).logical_bytes if compressed else data
    )
    assert_numbering(checked)
    assert source.serialize().itunes == original
    old_items = {
        s.chunk.header.mhip_persistent_id: s.chunk
        for s in before.find_chunks(MhipHeader)
        if s.chunk.header.mhip_persistent_id
    }
    new_items = {
        s.chunk.header.mhip_persistent_id: s.chunk
        for s in checked.find_chunks(MhipHeader)
        if s.chunk.header.mhip_persistent_id
    }
    for persistent_id, old in old_items.items():
        new = new_items[persistent_id]
        assert (
            replace(
                new.header,
                group_id=old.header.group_id,
                group_id_ref=old.header.group_id_ref,
            )
            == old.header
        )
        assert [(c.raw_header, c.raw_body) for c in new.children] == [
            (c.raw_header, c.raw_body) for c in old.children
        ]
    if not compressed:
        before_flat = rows(before, 2)[1].find_chunks(MhipHeader)
        after_flat = rows(checked, 2)[1].find_chunks(MhipHeader)
        assert [s.chunk.header.track_id for s in after_flat] == [2, 1]
        assert [
            (c.raw_header, c.raw_body) for s in after_flat for c in s.chunk.children
        ] == [(c.raw_header, c.raw_body) for s in before_flat for c in s.chunk.children]
    episode_ids = [
        s.chunk.header.group_id
        for s in rows(checked, 3)[1].find_chunks(MhipHeader)
        if s.chunk.header.track_id
    ]
    assert all(identity > 5000 for identity in episode_ids)
    reopened = IPodLibrary(data)
    again = reopened.prepare(
        reopened.analyze(reopened.begin_draft(repair_podcast_links=True))
    )
    assert again.prepared and again.prepared.itunes == data


@pytest.mark.parametrize("change", ("insert", "reorder", "rename", "append"))
def test_membership_edits_number_new_and_retained_rows_in_output_order(
    change: str,
) -> None:
    source = numbering_source("ordered")
    playlist = source.snapshot.playlists[0]
    first, second = playlist.entries
    entries = (
        (first, PlaylistEntry("new", 1), second)
        if change == "insert"
        else (second, first)
        if change == "reorder"
        else (first, second, PlaylistEntry("new", 2))
        if change == "append"
        else playlist.entries
    )
    tracks = source.snapshot.tracks
    desired = replace(
        source.snapshot,
        playlists=(replace(playlist, entries=entries),),
        tracks=(replace(tracks[0], album="Renamed"), tracks[1])
        if change == "rename"
        else tracks,
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert_numbering(checked)
    items = [s.chunk for s in rows(checked, 3)[1].find_chunks(MhipHeader)]
    if change in ("insert", "append"):
        assert [item.header.group_id for item in items[:2]] == [75, 76]
    if change == "append":
        assert [item.header.group_id for item in items[:4]] == [75, 76, 77, 78]
    if change == "rename":
        assert items[-1].header.is_group
        assert items[-1].header.mhip_persistent_id == 10001
    assert {
        s.chunk.header.mhip_persistent_id for s in checked.find_chunks(MhipHeader)
    } >= {1031, 1032, 1021, 1022, 10001, 10002}


def test_numbering_exhaustion_withholds_candidate() -> None:
    source = numbering_source("backwards", highest_id=0xFFFFFFFF)
    original = source.serialize().itunes
    result = source.prepare(
        source.analyze(source.begin_draft(repair_podcast_links=True))
    )
    assert result.prepared is None
    assert any("identities are exhausted" in issue.message for issue in result.issues)
    assert source.serialize().itunes == original


@pytest.mark.parametrize("first_position", (8808, 0))
def test_position_only_repair_preserves_flat_values_and_all_row_headers(
    first_position: int,
) -> None:
    document = parse_iTunesDB(numbering_source("ordered").serialize().itunes)
    expected = {1: first_position, 2: 8819}
    for kind in (2, 3):
        for occurrence in rows(document, kind)[1].find_chunks(MhipHeader):
            item = occurrence.chunk
            if not item.header.track_id:
                continue
            document = document.replace_chunk(
                occurrence,
                replace(
                    item,
                    children=tuple(
                        replace(
                            child,
                            prefix=replace(
                                child.prefix,
                                position=expected[item.header.track_id]
                                if kind == 2
                                else item.header.group_id,
                            ),
                        )
                        if isinstance(child.prefix, MhodPlaylistPositionPrefix)
                        else child
                        for child in item.children
                    ),
                ),
            )
    source = IPodLibrary(write_iTunesDB(document))
    original = source.serialize().itunes
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared and noop.prepared.itunes == original
    plan = source.analyze(source.begin_draft(repair_podcast_links=True))
    assert any(change.action == "repair" for change in plan.changes)
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert_numbering(checked)
    for kind in (2, 3):
        before = rows(document, kind)[1].find_chunks(MhipHeader)
        after = rows(checked, kind)[1].find_chunks(MhipHeader)
        assert [s.chunk.header for s in after] == [s.chunk.header for s in before]
        for occurrence in after:
            item = occurrence.chunk
            if item.header.track_id:
                assert [
                    c.prefix.position
                    for c in item.children
                    if isinstance(c.prefix, MhodPlaylistPositionPrefix)
                ] == [expected[item.header.track_id]]
    reopened = IPodLibrary(result.prepared.itunes)
    again = reopened.prepare(
        reopened.analyze(reopened.begin_draft(repair_podcast_links=True))
    )
    assert again.prepared and again.prepared.itunes == result.prepared.itunes


@pytest.mark.parametrize("missing", ((2,), (3,), (2, 3)))
def test_missing_position_uses_other_counterpart_then_row_id(
    missing: tuple[int, ...],
) -> None:
    document = parse_iTunesDB(numbering_source("ordered").serialize().itunes)
    for kind in missing:
        episode = next(
            s
            for s in rows(document, kind)[1].find_chunks(MhipHeader)
            if s.chunk.header.track_id == 1
        )
        document = document.replace_chunk(
            episode,
            replace(
                episode.chunk,
                children=tuple(
                    c
                    for c in episode.chunk.children
                    if not isinstance(c.prefix, MhodPlaylistPositionPrefix)
                ),
            ),
        )
    source = IPodLibrary(write_iTunesDB(document))
    result = source.prepare(
        source.analyze(source.begin_draft(repair_podcast_links=True))
    )
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert_numbering(checked)
    for kind in (2, 3):
        repaired_episode = next(
            s.chunk
            for s in rows(checked, kind)[1].find_chunks(MhipHeader)
            if s.chunk.header.track_id == 1
        )
        assert [
            c.prefix.position
            for c in repaired_episode.children
            if isinstance(c.prefix, MhodPlaylistPositionPrefix)
        ] == [76 if missing == (2, 3) else 101]


@pytest.mark.parametrize("dataset", (2, 3))
def test_verifier_rejects_position_mismatch_after_serialization(
    monkeypatch: pytest.MonkeyPatch, dataset: int
) -> None:
    source = numbering_source("flat")

    def corrupt(document: DatabaseDocument[MhbdHeader]) -> bytes:
        episode = next(
            s
            for s in rows(document, dataset)[1].find_chunks(MhipHeader)
            if s.chunk.header.track_id
        )
        item = episode.chunk
        damaged = replace(
            item,
            children=tuple(
                replace(child, prefix=replace(child.prefix, position=999))
                if isinstance(child.prefix, MhodPlaylistPositionPrefix)
                else child
                for child in item.children
            ),
        )
        return write_iTunesDB(document.replace_chunk(episode, damaged))

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    result = source.prepare(
        source.analyze(source.begin_draft(repair_podcast_links=True))
    )
    assert result.prepared is None
    assert any(
        issue.code == "verification.podcast_position_mirror" for issue in result.issues
    ), result.issues


@pytest.mark.parametrize("corruption", ("order", "mirror"))
def test_verifier_rejects_numbering_corruption(
    monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    source = numbering_source("flat")

    def corrupt(document: DatabaseDocument[MhbdHeader]) -> bytes:
        playlist = rows(document, 3 if corruption == "order" else 2)[1]
        for index, occurrence in enumerate(playlist.find_chunks(MhipHeader)):
            item = occurrence.chunk
            if corruption == "mirror" and index == 0:
                item = replace(item, header=replace(item.header, group_id=0xFFFFFFFD))
            elif corruption == "order" and index == 0:
                item = replace(item, header=replace(item.header, group_id=0xFFFFFFFE))
            elif corruption == "order" and index == 1:
                item = replace(
                    item, header=replace(item.header, group_id_ref=0xFFFFFFFE)
                )
            document = document.replace_chunk(occurrence, item)
        return write_iTunesDB(document)

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    result = source.prepare(
        source.analyze(source.begin_draft(repair_podcast_links=True))
    )
    assert result.prepared is None
    code = (
        "verification.podcast_row_order"
        if corruption == "order"
        else "verification.podcast_row_mirror"
    )
    assert any(issue.code == code for issue in result.issues), result.issues
