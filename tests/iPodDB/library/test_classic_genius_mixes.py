"""Classic Mix authoring, native records, and retained Library preservation."""

from dataclasses import replace
from hashlib import sha256

import pytest
from tests.iPodDB.library.test_genius_writing import (
    remove_second_track,
    retained_resources,
    update,
)
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, WriteTarget
from iPodDB.library.genius import GeniusData, GeniusMix, GeniusUpdate
from iPodDB.library.writing import FileDependency, PreparedLibrary, PreparedMedia

TARGET = WriteTarget(classic_genius_mixes=True)


def authored() -> PreparedLibrary:
    source = library(mirrored=True)
    result = source.prepare(
        source.analyze(source.begin_draft(genius_update=update(mix=True)), TARGET)
    )
    assert result.prepared is not None, result.issues
    return result.prepared


def mix_bytes(data: bytes) -> tuple[bytes, ...]:
    return tuple(
        data[
            s.chunk.offset : s.chunk.offset
            + s.chunk.generic_header.length_or_child_count
        ]
        for s in parse_iTunesDB(data).find_chunks(MhypHeader)
        if s.chunk.header.is_genius_mix
    )


def test_authored_mix_uses_native_kind_and_track_ids_in_both_datasets() -> None:
    prepared = authored()
    source = IPodLibrary(prepared.itunes)
    browse = source.classic_genius_mixes()
    assert not browse.issues
    assert len(browse.collections) == 1
    mix = browse.collections[0]
    assert (mix.name, mix.track_ids, mix.seed_track_id, mix.native_playlist_id) == (
        "Test Mix",
        (2, 1),
        None,
        900,
    )
    assert 900 not in {p.playlist_id for p in source.snapshot.playlists}
    document = parse_iTunesDB(prepared.itunes)
    assert (
        document.header.genius_target_count,
        document.header.genius_minimum_count,
    ) == (25, 10)
    kinds: set[int] = set()
    occurrence_ids: list[int] = []
    for dataset in document.find_chunks(MhsdHeader):
        for row in dataset.find_chunks(MhypHeader):
            if row.chunk.header.playlist_id != 900:
                continue
            kinds.add(dataset.chunk.header.dataset_type)
            occurrence_ids.extend(
                m.chunk.header.mhip_persistent_id for m in row.find_chunks(MhipHeader)
            )
            assert prepared.itunes[row.chunk.offset + 0x52] == 32
            assert row.chunk.header.mhsd_5_type == 0
            assert tuple(
                (m.chunk.header.track_id, m.chunk.header.track_persistent_id)
                for m in row.find_chunks(MhipHeader)
            ) == ((2, 102), (1, 101))
            assert not any(
                m.chunk.header.mhod_type == 54 for m in row.find_chunks(MhodHeader)
            )
    assert kinds == {2, 3}
    assert len(set(occurrence_ids)) == 4 and all(occurrence_ids)
    assert prepared.sqlite is None and prepared.genius is not None


def test_noop_and_unrelated_metadata_edits_preserve_native_mix_bytes() -> None:
    first = authored()
    source = IPodLibrary(first.itunes)
    noop = source.prepare(
        source.analyze(source.begin_draft(), TARGET), retained_resources(first)
    )
    assert noop.prepared is not None, noop.issues
    assert noop.prepared.itunes == first.itunes
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], title="Renamed"),
            source.snapshot.tracks[1],
        ),
    )
    edited = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET), retained_resources(first)
    )
    assert edited.prepared is not None, edited.issues
    assert mix_bytes(edited.prepared.itunes) == mix_bytes(first.itunes)
    assert edited.prepared.genius == first.genius


def test_track_deletion_prunes_candidates_and_removes_newly_empty_mix() -> None:
    first = authored()
    source = IPodLibrary(first.itunes)
    desired = remove_second_track(source)
    result = source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=True), TARGET),
        retained_resources(first),
    )
    assert result.prepared is not None, result.issues
    assert IPodLibrary(result.prepared.itunes).classic_genius_mixes().collections[
        0
    ].track_ids == (1,)
    source = IPodLibrary(result.prepared.itunes)
    empty = replace(
        source.snapshot,
        tracks=(),
        playlists=tuple(replace(p, entries=()) for p in source.snapshot.playlists),
    )
    cleared = source.prepare(
        source.analyze(source.begin_draft(empty, delete_omissions=True), TARGET),
        retained_resources(result.prepared),
    )
    assert cleared.prepared is not None, cleared.issues
    assert not IPodLibrary(cleared.prepared.itunes).classic_genius_mixes().collections


def test_replaced_audio_is_removed_from_retained_mix_candidates() -> None:
    first = authored()
    source = IPodLibrary(first.itunes)
    track = source.snapshot.tracks[1]
    replacement = replace(
        track,
        size_bytes=4,
        metadata=replace(
            track.metadata,
            location="iPod_Control/Music/F00/replaced.mp3",
            sample_rate_hz=44100,
            file_format="MPEG audio file",
        ),
    )
    desired = replace(source.snapshot, tracks=(source.snapshot.tracks[0], replacement))
    media = PreparedMedia(
        2,
        FileDependency(replacement.metadata.location, 4, sha256(b"test").hexdigest()),
        int.from_bytes(b"MP3 ", "big"),
        1,
        0xFFFF,
        12,
        0,
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired, replace_media=(2,)), TARGET),
        replace(retained_resources(first), media=(media,)),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks[1].ipod is not None
    assert result.prepared.snapshot.tracks[1].ipod.genius_id == 0
    assert IPodLibrary(result.prepared.itunes).classic_genius_mixes().collections[
        0
    ].track_ids == (1,)


def test_selective_add_and_remove_preserve_unmentioned_native_mix() -> None:
    first = authored()
    source = IPodLibrary(first.itunes)
    intent = replace(
        update(), mixes=None, mix_additions=(GeniusMix(901, "Second Mix", (1,)),)
    )
    added = source.prepare(
        source.analyze(source.begin_draft(genius_update=intent), TARGET),
        retained_resources(first),
    )
    assert added.prepared is not None, added.issues
    assert all(
        row in mix_bytes(added.prepared.itunes) for row in mix_bytes(first.itunes)
    )
    source = IPodLibrary(added.prepared.itunes)
    removed = source.prepare(
        source.analyze(
            source.begin_draft(
                genius_update=replace(update(), mixes=None, mix_removals=(901,))
            ),
            TARGET,
        ),
        retained_resources(added.prepared),
    )
    assert removed.prepared is not None, removed.issues
    assert mix_bytes(removed.prepared.itunes) == mix_bytes(first.itunes)


@pytest.mark.parametrize("identity", [10, 900])
def test_mix_additions_cannot_overwrite_existing_playlist_or_mix(identity: int) -> None:
    first = authored()
    source = IPodLibrary(first.itunes)
    intent = replace(
        update(), mixes=None, mix_additions=(GeniusMix(identity, "Collision", (1,)),)
    )
    result = source.prepare(
        source.analyze(source.begin_draft(genius_update=intent), TARGET),
        retained_resources(first),
    )
    assert result.prepared is None
    assert any("collides" in issue.message for issue in result.issues)


@pytest.mark.parametrize("count", (12, 13))
def test_native_preparation_enforces_twelve_mix_limit(count: int) -> None:
    source = library(mirrored=True)
    intent = replace(
        update(),
        mixes=tuple(GeniusMix(900 + i, f"Mix {i}", (1,)) for i in range(count)),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(genius_update=intent), TARGET)
    )
    if count == 12:
        assert result.prepared is not None, result.issues
        assert (
            len(IPodLibrary(result.prepared.itunes).classic_genius_mixes().collections)
            == 12
        )
    else:
        assert result.prepared is None
        assert any("12 Genius Mixes" in issue.message for issue in result.issues)


@pytest.mark.parametrize("explicit", (False, True))
def test_graph_clear_removes_newly_depleted_classic_mixes(explicit: bool) -> None:
    first = authored()
    source = IPodLibrary(first.itunes)
    intent = GeniusUpdate(GeniusData(), mixes=() if explicit else None)
    result = source.prepare(
        source.analyze(source.begin_draft(genius_update=intent), TARGET),
        retained_resources(first),
    )
    assert result.prepared is not None, result.issues
    assert not IPodLibrary(result.prepared.itunes).classic_genius_mixes().collections


def test_new_mix_preserves_nonzero_thresholds_and_more_than_100_members() -> None:
    source = library(mirrored=True)
    document = parse_iTunesDB(source.serialize().itunes)
    document = replace(
        document,
        header=replace(
            document.header, genius_target_count=40, genius_minimum_count=15
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    members = (2, 1) * 101
    intent = replace(update(), mixes=(GeniusMix(900, "Long pool", members),))
    result = source.prepare(
        source.analyze(source.begin_draft(genius_update=intent), TARGET)
    )
    assert result.prepared is not None, result.issues
    document = parse_iTunesDB(result.prepared.itunes)
    assert (
        document.header.genius_target_count,
        document.header.genius_minimum_count,
    ) == (40, 15)
    assert (
        IPodLibrary(result.prepared.itunes)
        .classic_genius_mixes()
        .collections[0]
        .track_ids
        == members
    )


def test_mismatched_mix_copies_are_reported_and_dependent_changes_fail() -> None:
    first = authored()
    document = parse_iTunesDB(first.itunes)
    rows = tuple(
        s for s in document.find_chunks(MhypHeader) if s.chunk.header.is_genius_mix
    )
    document = document.replace_chunk(
        rows[0],
        replace(
            rows[0].chunk,
            children=tuple(
                c
                for c in rows[0].chunk.children
                if not isinstance(c.header, MhipHeader)
            ),
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    assert source.classic_genius_mixes().issues
    intent = replace(update(), mixes=None, mix_removals=(900,))
    result = source.prepare(
        source.analyze(source.begin_draft(genius_update=intent), TARGET),
        retained_resources(first),
    )
    assert result.prepared is None
    assert any("disagree" in issue.message for issue in result.issues)


def test_low_byte_discriminator_preserves_unknown_upper_byte() -> None:
    first = authored()
    document = parse_iTunesDB(first.itunes)
    for row in document.find_chunks(MhypHeader):
        if row.chunk.header.is_genius_mix:
            document = document.replace_chunk(
                row,
                replace(
                    row.chunk, header=replace(row.chunk.header, phase_game_flag=0xAB20)
                ),
            )
    source = IPodLibrary(write_iTunesDB(document))
    assert not source.classic_genius_mixes().issues
    assert len(source.classic_genius_mixes().collections) == 1
    result = source.prepare(
        source.analyze(source.begin_draft(genius_update=update(mix=True)), TARGET),
        retained_resources(first),
    )
    assert result.prepared is not None, result.issues
    assert all(
        s.chunk.header.phase_game_flag == 0xAB20
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhypHeader)
        if s.chunk.header.is_genius_mix
    )
