"""Native Genius preparation coordinates Track IDs, graphs, and Mix artifacts."""

from dataclasses import replace
from hashlib import sha256

import pytest
from tests.iPodDB.library.test_sidecar_projection import short_header_library
from tests.iPodDB.library.test_writing import library
from tests.iPodDB.SQLiteDB.sqlite_test_support import sqlite_rows

from iPodDB.genius import GeniusMetadata, GeniusSimilarities, make_no_rule_genius_config
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.library import (
    IPodLibrary,
    LibrarySnapshot,
    WriteResources,
    WriteTarget,
    _write_preparation,
)
from iPodDB.library._genius_writing import reconcile_genius_tracks
from iPodDB.library.genius import (
    GeniusConfigRow,
    GeniusData,
    GeniusMetadataRow,
    GeniusMix,
    GeniusSimilaritiesRow,
    GeniusTrack,
    GeniusUpdate,
    parse_genius_database,
    read_sqlite_genius_state,
)
from iPodDB.library.sqlite import SQLiteSource
from iPodDB.library.writing import FileDependency, PreparedLibrary, PreparedMedia
from iPodDB.shared.chunk import DatabaseDocument


def update(*, mix: bool = False) -> GeniusUpdate:
    return GeniusUpdate(
        GeniusData(
            (GeniusConfigRow(1, 2, 25, 10, make_no_rule_genius_config()),),
            tuple(
                GeniusMetadataRow(gid, 2, GeniusMetadata((1, gid, gid, gid)))
                for gid in (1001, 1002)
            ),
            (
                GeniusSimilaritiesRow(1001, 2, GeniusSimilarities((1002,))),
                GeniusSimilaritiesRow(1002, 2, GeniusSimilarities((1001,))),
            ),
        ),
        (GeniusTrack(1, 1001), GeniusTrack(2, 1002)),
        (GeniusMix(900, "Test Mix", (2, 1), seed_track_id=2),) if mix else (),
    )


def authored(*, sqlite: bool = False) -> PreparedLibrary:
    source = library()
    result = source.prepare(
        source.analyze(
            source.begin_draft(genius_update=update(mix=sqlite)),
            WriteTarget(sqlite_database=sqlite),
        ),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    return result.prepared


def retained_resources(prepared: PreparedLibrary) -> WriteResources:
    return WriteResources(
        pending_playback_sidecars=False,
        genius_source=prepared.genius,
        sqlite_sources=(
            ()
            if prepared.sqlite is None
            else tuple(
                SQLiteSource(name, data)
                for name, data in prepared.sqlite.artifacts()
                if name.endswith(".itdb")
            )
        ),
    )


def remove_second_track(source: IPodLibrary) -> LibrarySnapshot:
    return replace(
        source.snapshot,
        tracks=tuple(t for t in source.snapshot.tracks if t.track_id != 2),
        playlists=tuple(
            replace(p, entries=tuple(e for e in p.entries if e.track_id != 2))
            for p in source.snapshot.playlists
        ),
    )


@pytest.mark.parametrize("sqlite", [False, True])
def test_authoring_coordinates_binary_track_ids_and_native_graph(sqlite: bool) -> None:
    source = library()
    unchanged = source.serialize()
    intent = update(mix=sqlite)
    plan = source.analyze(
        source.begin_draft(genius_update=intent), WriteTarget(sqlite_database=sqlite)
    )
    assert plan.changes_itunes
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    output = result.prepared
    assert source.serialize() == unchanged
    assert tuple(
        (s.chunk.header.track_id, s.chunk.header.db_track_id, s.chunk.header.genius_id)
        for s in parse_iTunesDB(output.itunes).find_chunks(MhitHeader)
    ) == ((1, 101, 1001), (2, 102, 1002))
    assert tuple(t.ipod.genius_id for t in output.snapshot.tracks if t.ipod) == (
        1001,
        1002,
    )
    if sqlite:
        assert output.genius is None
        assert output.sqlite is not None
        state = read_sqlite_genius_state(
            output.sqlite.library, output.sqlite.dynamic, output.sqlite.genius
        )
        assert state.data == intent.data
        assert state.track_genius_ids == ((101, 1001), (102, 1002))
        assert len(state.mixes) == 1
        assert state.mixes[0].container_id == 900
        assert state.mixes[0].item_pids == (102, 101)
        assert state.mixes[0].seed_pids == (102,)
        assert all(p.playlist_id != 900 for p in output.snapshot.playlists)
    else:
        assert output.sqlite is None
        assert output.genius is not None
        assert parse_genius_database(output.genius).data == intent.data


@pytest.mark.parametrize("sqlite", [False, True])
def test_metadata_edit_retains_graph_bytes_and_mix_membership(sqlite: bool) -> None:
    first = authored(sqlite=sqlite)
    source = IPodLibrary(first.itunes)
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], title="Renamed"),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired), WriteTarget(sqlite_database=sqlite)
        ),
        retained_resources(first),
    )
    assert result.prepared is not None, result.issues
    second = result.prepared
    assert second.snapshot.tracks[0].title == "Renamed"
    assert tuple(t.ipod.genius_id for t in second.snapshot.tracks if t.ipod) == (
        1001,
        1002,
    )
    if sqlite:
        assert first.sqlite is not None and second.sqlite is not None
        assert second.sqlite.genius == first.sqlite.genius
        assert read_sqlite_genius_state(
            second.sqlite.library, second.sqlite.dynamic, second.sqlite.genius
        ) == read_sqlite_genius_state(
            first.sqlite.library, first.sqlite.dynamic, first.sqlite.genius
        )
    else:
        assert second.genius == first.genius


@pytest.mark.parametrize("sqlite", [False, True])
def test_explicit_clear_removes_graph_assignments_and_native_mixes(
    sqlite: bool,
) -> None:
    first = authored(sqlite=sqlite)
    source = IPodLibrary(first.itunes)
    result = source.prepare(
        source.analyze(
            source.begin_draft(genius_update=GeniusUpdate(GeniusData(), mixes=())),
            WriteTarget(sqlite_database=sqlite),
        ),
        retained_resources(first),
    )
    assert result.prepared is not None, result.issues
    output = result.prepared
    assert all(t.ipod and t.ipod.genius_id == 0 for t in output.snapshot.tracks)
    if sqlite:
        assert output.sqlite is not None
        state = read_sqlite_genius_state(
            output.sqlite.library, output.sqlite.dynamic, output.sqlite.genius
        )
        assert state.data == GeniusData()
        assert state.track_genius_ids == ()
        assert state.mixes == ()
        assert (
            sqlite_rows(
                output.sqlite.dynamic,
                "SELECT container_pid FROM container_ui WHERE container_pid=900",
            )
            == ()
        )
    else:
        assert output.genius is not None
        assert parse_genius_database(output.genius).data == GeniusData()


def test_classic_removal_requires_captured_graph_before_binary_ids_change() -> None:
    first = authored()
    source = IPodLibrary(first.itunes)
    original = source.serialize()
    result = source.prepare(
        source.analyze(
            source.begin_draft(remove_second_track(source), delete_omissions=True)
        ),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is None
    assert any("Extras.itdb" in issue.message for issue in result.issues)
    assert source.serialize() == original


@pytest.mark.parametrize("sqlite", [False, True])
def test_track_removal_prunes_graph_and_surviving_mix_membership(sqlite: bool) -> None:
    first = authored(sqlite=sqlite)
    source = IPodLibrary(first.itunes)
    result = source.prepare(
        source.analyze(
            source.begin_draft(remove_second_track(source), delete_omissions=True),
            WriteTarget(sqlite_database=sqlite),
        ),
        retained_resources(first),
    )
    assert result.prepared is not None, result.issues
    output = result.prepared
    assert len(output.snapshot.tracks) == 1
    assert output.snapshot.tracks[0].ipod is not None
    assert output.snapshot.tracks[0].ipod.genius_id == 1001
    if sqlite:
        assert output.sqlite is not None
        state = read_sqlite_genius_state(
            output.sqlite.library, output.sqlite.dynamic, output.sqlite.genius
        )
        data = state.data
        assert state.track_genius_ids == ((101, 1001),)
        assert state.mixes[0].item_pids == (101,)
        assert state.mixes[0].seed_pids == ()
    else:
        assert output.genius is not None
        data = parse_genius_database(output.genius).data
    assert tuple(row.genius_id for row in data.metadata) == (1001,)
    assert data.similarities == (
        GeniusSimilaritiesRow(1001, 2, GeniusSimilarities(())),
    )
    assert data.configs == update().data.configs


@pytest.mark.parametrize("case", ["track", "candidate", "metadata", "mix", "duplicate"])
def test_invalid_genius_references_fail_without_partial_preparation(case: str) -> None:
    source = library()
    original = source.serialize()
    intent = update(mix=True)
    if case == "track":
        intent = replace(intent, tracks=(GeniusTrack(999, 1001), GeniusTrack(2, 1002)))
    elif case == "candidate":
        intent = replace(
            intent,
            data=replace(
                intent.data,
                similarities=(
                    GeniusSimilaritiesRow(1001, 2, GeniusSimilarities((999,))),
                    intent.data.similarities[1],
                ),
            ),
        )
    elif case == "metadata":
        intent = replace(
            intent, data=replace(intent.data, metadata=intent.data.metadata[:1])
        )
    elif case == "mix":
        intent = replace(intent, mixes=(GeniusMix(900, "Invalid", (999,)),))
    else:
        intent = replace(intent, tracks=(GeniusTrack(1, 1001), GeniusTrack(2, 1001)))
    result = source.prepare(
        source.analyze(
            source.begin_draft(genius_update=intent), WriteTarget(sqlite_database=True)
        )
    )
    assert result.prepared is None
    assert any("Genius" in issue.message for issue in result.issues)
    assert source.serialize() == original


def test_mix_authoring_requires_sqlite_target() -> None:
    source = library()
    plan = source.analyze(source.begin_draft(genius_update=update(mix=True)))
    assert plan.blocked
    assert any(issue.code == "genius.mix_requires_sqlite" for issue in plan.issues)
    assert source.prepare(plan).prepared is None


def test_short_track_header_rejects_unrepresentable_genius_id() -> None:
    source = short_header_library(328)
    original = source.serialize()
    result = source.prepare(source.analyze(source.begin_draft(genius_update=update())))
    assert result.prepared is None
    assert any("Genius" in issue.message for issue in result.issues)
    assert source.serialize() == original


def test_native_verification_rejects_tampered_authored_genius_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def tamper(
        document: DatabaseDocument[MhbdHeader],
        intent: GeniusUpdate | None,
        replaced_ids: frozenset[int],
    ) -> DatabaseDocument[MhbdHeader]:
        result = reconcile_genius_tracks(document, intent, replaced_ids)
        selected = result.find_chunks(MhitHeader)[0]
        return result.replace_chunk(
            selected,
            replace(
                selected.chunk, header=replace(selected.chunk.header, genius_id=999)
            ),
        )

    monkeypatch.setattr(_write_preparation, "reconcile_genius_tracks", tamper)
    source = library()
    result = source.prepare(source.analyze(source.begin_draft(genius_update=update())))
    assert result.prepared is None
    assert any(
        issue.code == "verification.track_native" and issue.field == "genius_id"
        for issue in result.issues
    )


@pytest.mark.parametrize(
    ("sqlite", "preserve_mixes"), ((False, False), (True, False), (True, True))
)
def test_new_track_assignments_and_mix_seeds_follow_allocated_identity(
    sqlite: bool,
    preserve_mixes: bool,
) -> None:
    source = library()
    added = replace(
        source.snapshot.tracks[0],
        track_id=-1,
        title="Added Track",
        ipod=None,
        size_bytes=4,
        metadata=replace(
            source.snapshot.tracks[0].metadata,
            location="iPod_Control/Music/F00/added.mp3",
            sample_rate_hz=44100,
            file_format="MPEG audio file",
        ),
    )
    base = update()
    intent = GeniusUpdate(
        replace(
            base.data,
            metadata=(
                *base.data.metadata,
                GeniusMetadataRow(1003, 2, GeniusMetadata((1, 1003))),
            ),
            similarities=(
                *base.data.similarities,
                GeniusSimilaritiesRow(1003, 2, GeniusSimilarities((1001, 1002))),
            ),
        ),
        (*base.tracks, GeniusTrack(-1, 1003)),
        None
        if preserve_mixes
        else (GeniusMix(900, "New seed", (-1, 1), seed_track_id=-1),)
        if sqlite
        else (),
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(
                replace(source.snapshot, tracks=(*source.snapshot.tracks, added)),
                genius_update=intent,
            ),
            WriteTarget(sqlite_database=sqlite),
        ),
        WriteResources(
            pending_playback_sidecars=False,
            media=(
                PreparedMedia(
                    -1,
                    FileDependency(
                        added.metadata.location, 4, sha256(b"test").hexdigest()
                    ),
                    int.from_bytes(b"MP3 ", "big"),
                    1,
                    0xFFFF,
                    12,
                    0,
                ),
            ),
        ),
    )
    assert result.prepared is not None, result.issues
    output = result.prepared
    assigned = next(
        m.output_id
        for m in output.identities
        if m.subject == "track" and m.draft_id == -1
    )
    new_track = next(t for t in output.snapshot.tracks if t.track_id == assigned)
    assert assigned > 0
    assert new_track.ipod is not None
    assert new_track.ipod.genius_id == 1003
    if sqlite:
        assert output.sqlite is not None
        state = read_sqlite_genius_state(
            output.sqlite.library, output.sqlite.dynamic, output.sqlite.genius
        )
        assert (new_track.ipod.db_track_id, 1003) in state.track_genius_ids
        if preserve_mixes:
            assert state.mixes == ()
        else:
            assert state.mixes[0].item_pids == (new_track.ipod.db_track_id, 101)
            assert state.mixes[0].seed_pids == (new_track.ipod.db_track_id,)


@pytest.mark.parametrize("assignment", ("all", "first", "none"))
def test_graph_only_refresh_preserves_native_mixes_and_prunes_unassigned_seeds(
    assignment: str,
) -> None:
    first = authored(sqlite=True)
    source = IPodLibrary(first.itunes)
    base = update()
    expected_members: tuple[int, ...]
    expected_seed: tuple[int, ...]
    if assignment == "all":
        data = replace(
            base.data,
            configs=(replace(base.data.configs[0], default_num_results=20),),
        )
        tracks = base.tracks
        expected_members = (102, 101)
        expected_seed = (102,)
    elif assignment == "first":
        data = replace(
            base.data,
            metadata=base.data.metadata[:1],
            similarities=(GeniusSimilaritiesRow(1001, 2, GeniusSimilarities(())),),
        )
        tracks = base.tracks[:1]
        expected_members = (101,)
        expected_seed = ()
    else:
        data, tracks = GeniusData(), ()
        expected_members, expected_seed = (), ()
    intent = GeniusUpdate(data, tracks)
    assert intent.mixes is None
    result = source.prepare(
        source.analyze(
            source.begin_draft(genius_update=intent), WriteTarget(sqlite_database=True)
        ),
        retained_resources(first),
    )
    assert result.prepared is not None, result.issues
    output = result.prepared.sqlite
    assert output is not None
    state = read_sqlite_genius_state(output.library, output.dynamic, output.genius)
    assert state.data == data
    assert len(state.mixes) == 1
    assert state.mixes[0].container_id == 900
    assert state.mixes[0].name == "Test Mix"
    assert state.mixes[0].item_pids == expected_members
    assert state.mixes[0].seed_pids == expected_seed


def test_graph_only_generation_does_not_create_native_mixes() -> None:
    source = library()
    base = update()
    result = source.prepare(
        source.analyze(
            source.begin_draft(genius_update=GeniusUpdate(base.data, base.tracks)),
            WriteTarget(sqlite_database=True),
        )
    )
    assert result.prepared is not None, result.issues
    output = result.prepared.sqlite
    assert output is not None
    state = read_sqlite_genius_state(output.library, output.dynamic, output.genius)
    assert state.track_genius_ids == ((101, 1001), (102, 1002))
    assert state.mixes == ()


def test_bulk_genius_assignment_preserves_track_children_and_unrelated_branches() -> (
    None
):
    document = parse_iTunesDB(library().serialize().itunes)
    selection = next(
        row
        for row in document.find_chunks(MhsdHeader)
        if row.chunk.header.dataset_type == 1
    )
    track_list = selection.chunk.children[0]
    template = track_list.child_as(0, MhitHeader)
    total = 2048
    originals = tuple(
        replace(
            template, header=replace(template.header, track_id=i, db_track_id=10000 + i)
        )
        for i in range(1, total + 1)
    )
    document = document.replace_chunk(
        selection,
        replace(selection.chunk, children=(replace(track_list, children=originals),)),
    )
    base = update()
    intent = GeniusUpdate(
        replace(
            base.data,
            metadata=tuple(
                GeniusMetadataRow(i, 2, GeniusMetadata((1, i)))
                for i in range(1, total + 1)
            ),
            similarities=tuple(
                GeniusSimilaritiesRow(i, 2, GeniusSimilarities((1,)))
                for i in range(1, total + 1)
            ),
        ),
        tuple(GeniusTrack(i, i) for i in range(1, total + 1)),
    )
    changed = reconcile_genius_tracks(document, intent, frozenset())
    for original, row in zip(originals, changed.find_chunks(MhitHeader), strict=True):
        assert row.chunk.header.genius_id == original.header.track_id
        assert row.chunk.children is original.children
        assert row.chunk.raw_body is original.raw_body
    assert all(
        left is right
        for left, right in zip(document.children[1:], changed.children[1:], strict=True)
    )
    assert reconcile_genius_tracks(changed, None, frozenset()) is changed
