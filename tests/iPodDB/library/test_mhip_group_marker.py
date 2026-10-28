"""MHIP group discrimination uses the complete byte at native offset 0x11."""

from collections import Counter
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_playlist_datasets import rows
from tests.iPodDB.library.test_playlists import (
    _database,  # pyright: ignore[reportPrivateUsage]
    _dataset,  # pyright: ignore[reportPrivateUsage]
    _playlist,  # pyright: ignore[reportPrivateUsage]
)
from tests.iPodDB.library.test_podcast_row_order import numbering_source
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, PlaylistEntry, WriteResources


@pytest.mark.parametrize("group_byte", (0, 1, 2, 0x80, 0xFF))
@pytest.mark.parametrize("low_byte", (0, 1, 0x80, 0xFF))
def test_raw_group_byte_hides_rows_without_losing_duplicate_occurrences(
    group_byte: int, low_byte: int
) -> None:
    data = bytearray(
        _database(
            _dataset(
                3,
                _playlist(
                    10,
                    "Repeated Tracks",
                    items=tuple(MhipHeader(track_id=i) for i in (1, 1, 1, 2)),
                ),
            )
        )
    )
    offset = data.index(b"mhip")
    # Literal byte offsets keep the fixture independent of the shared predicate.
    data[offset + 0x10] = low_byte
    data[offset + 0x11] = group_byte
    source = IPodLibrary(bytes(data))
    entries = source.snapshot.playlists[0].entries
    assert tuple(entry.track_id for entry in entries) == (
        (1, 1, 2) if group_byte else (1, 1, 1, 2)
    )
    assert len({entry.entry_id for entry in entries}) == len(entries)
    assert source.serialize().itunes == data


def _retagged_podcasts(group_byte: int, *, companion: bool = True) -> IPodLibrary:
    document = parse_iTunesDB(numbering_source("ordered").serialize().itunes)
    for occurrence in document.find_chunks(MhipHeader):
        item = occurrence.chunk
        marker = group_byte if item.raw_header[0x11] else 0
        document = document.replace_chunk(
            occurrence,
            replace(
                item,
                header=replace(
                    item.header, unchecked_override=0x80, group_marker=marker
                ),
            ),
        )
    if not companion:
        document = replace(
            document,
            children=tuple(
                child
                for child in document.children
                if not isinstance(child.header, MhsdHeader)
                or child.header.dataset_type != 2
            ),
        )
    return IPodLibrary(write_iTunesDB(document))


@pytest.mark.parametrize("group_byte", (2, 0x80, 0xFF))
@pytest.mark.parametrize(
    "change", ("track_title", "playlist_name", "reorder", "append_duplicate", "repair")
)
def test_noncanonical_groups_survive_supported_edits(
    group_byte: int, change: str
) -> None:
    source = _retagged_podcasts(group_byte)
    original = source.serialize().itunes
    before = parse_iTunesDB(original)
    groups = {
        item.chunk.header.mhip_persistent_id: item.chunk
        for item in rows(before, 3)[1].find_chunks(MhipHeader)
        if item.chunk.raw_header[0x11]
    }
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared and noop.prepared.itunes == original
    playlist = source.snapshot.playlists[0]
    first, second = playlist.entries
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], title="Edited episode"),
            source.snapshot.tracks[1],
        )
        if change == "track_title"
        else source.snapshot.tracks,
        playlists=(
            replace(
                playlist,
                name="Renamed Podcasts" if change == "playlist_name" else playlist.name,
                entries=(second, first)
                if change == "reorder"
                else (*playlist.entries, PlaylistEntry("new", second.track_id))
                if change == "append_duplicate"
                else playlist.entries,
            ),
        ),
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired, repair_podcast_links=change == "repair")
        )
    )
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    grouped = tuple(s.chunk for s in rows(checked, 3)[1].find_chunks(MhipHeader))
    retained_groups = tuple(item for item in grouped if item.raw_header[0x11])
    assert len(retained_groups) == len(groups) == 2
    for item in retained_groups:
        old = groups[item.header.mhip_persistent_id]
        assert item.raw_header[0x10:0x12] == bytes((0x80, group_byte))
        assert replace(item.header, group_id=old.header.group_id) == old.header
        assert [(c.raw_header, c.raw_body) for c in item.children] == [
            (c.raw_header, c.raw_body) for c in old.children
        ]
    ordinary = tuple(item for item in grouped if not item.raw_header[0x11])
    expected = tuple(entry.track_id for entry in desired.playlists[0].entries)
    assert tuple(item.header.track_id for item in ordinary) == expected
    for item in ordinary:
        if item.header.mhip_persistent_id in (1031, 1032):
            assert item.raw_header[0x10] == 0x80
    flat = tuple(s.chunk for s in rows(checked, 2)[1].find_chunks(MhipHeader))
    assert all(not item.raw_header[0x11] for item in flat)
    assert Counter(item.header.track_id for item in flat) == Counter(expected)
    assert (
        tuple(
            entry.track_id
            for entry in IPodLibrary(result.prepared.itunes)
            .snapshot.playlists[0]
            .entries
        )
        == expected
    )
    assert source.serialize().itunes == original


@pytest.mark.parametrize("group_byte", (2, 0x80, 0xFF))
def test_new_flat_companion_excludes_every_nonzero_group_marker(
    group_byte: int,
) -> None:
    source = _retagged_podcasts(group_byte, companion=False)
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Changed"),),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    flat = tuple(s.chunk for s in rows(checked, 2)[1].find_chunks(MhipHeader))
    assert tuple(item.header.track_id for item in flat) == (1, 2)
    assert all(item.raw_header[0x10:0x12] == b"\x80\x00" for item in flat)
    assert all(item.header.group_id_ref == 0 for item in flat)


@pytest.mark.parametrize("group_byte", (1, 2, 0x80, 0xFF))
def test_track_deletion_preserves_hidden_group_with_matching_unused_track_word(
    group_byte: int,
) -> None:
    document = parse_iTunesDB(library(mirrored=True).serialize().itunes)
    category = _playlist(
        50,
        "Retained category",
        category=7,
        items=(
            MhipHeader(
                unchecked_override=0x80,
                group_marker=group_byte,
                track_id=1,
                group_id=7,
                timestamp=919,
                unk_mhip_0x12=0x8001,
            ),
            MhipHeader(track_id=1),
            MhipHeader(track_id=2),
        ),
    )
    source = IPodLibrary(write_iTunesDB(document.append_child(_dataset(5, category))))
    original = source.serialize().itunes
    before = rows(parse_iTunesDB(original), 5)[0].find_chunks(MhipHeader)[0].chunk
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
    items = rows(parse_iTunesDB(result.prepared.itunes), 5)[0].find_chunks(MhipHeader)
    assert len(items) == 2
    assert items[0].chunk.raw_header == before.raw_header
    assert items[0].chunk.raw_body == before.raw_body
    assert items[1].chunk.raw_header[0x11] == 0
    assert items[1].chunk.header.track_id == 2
    assert source.serialize().itunes == original
