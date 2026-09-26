"""Requested edits, derived consequences, and verification through Library writing."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_lyrics_writing import lyrics_resource, lyrics_source
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_jump_table_mhod import (
    MhodLibraryJumpTablePayload,
)
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    MediaType,
    Playlist,
    PlaylistEntry,
    PlaylistKind,
    WritePhase,
    WriteResources,
    _write_preparation,
)
from iPodDB.library._field_policy import unclassified_fields
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk


@pytest.mark.parametrize("corruption", ["permutation", "jump_letter", "missing"])
def test_verification_rejects_plausible_but_wrong_browse_indexes(
    monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    source = library(mirrored=True)
    original = source.serialize()
    desired = replace(source.snapshot, tracks=tuple(reversed(source.snapshot.tracks)))

    def corrupt(document: DatabaseDocument[MhbdHeader]) -> bytes:
        if corruption == "missing":
            from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader

            for master in document.find_chunks(MhypHeader):
                document = document.replace_chunk(
                    master,
                    replace(
                        master.chunk,
                        children=tuple(
                            c
                            for c in master.chunk.children
                            if not isinstance(
                                c.payload,
                                MhodLibraryIndexPayload | MhodLibraryJumpTablePayload,
                            )
                        ),
                    ),
                )
        for selection in document.find_chunks(MhodHeader):
            chunk = selection.chunk
            payload = chunk.payload
            if corruption == "permutation" and isinstance(
                payload, MhodLibraryIndexPayload
            ):
                document = document.replace_chunk(
                    selection,
                    replace(
                        chunk,
                        payload=replace(
                            payload, indices=tuple(range(len(payload.indices)))
                        ),
                    ),
                )
            elif corruption == "jump_letter" and isinstance(
                payload, MhodLibraryJumpTablePayload
            ):
                document = document.replace_chunk(
                    selection,
                    replace(
                        chunk,
                        payload=replace(
                            payload,
                            entries=tuple(
                                replace(e, letter_code=ord("Z"))
                                for e in payload.entries
                            ),
                        ),
                    ),
                )
        return write_iTunesDB(document)

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is None
    assert any(i.code == "verification.playlist_index" for i in result.issues)
    assert source.serialize() == original


def test_every_library_field_has_exactly_one_ownership_policy() -> None:
    assert unclassified_fields() == ()


def test_new_unclassified_model_field_blocks_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iPodDB.library import _field_policy

    monkeypatch.setattr(
        _field_policy,
        "TRACK_POLICY",
        tuple(p for p in _field_policy.TRACK_POLICY if p.path != "rating"),
    )
    source = library()
    result = source.prepare(source.analyze(source.begin_draft()))
    assert result.prepared is None
    assert any(
        i.code == "draft.unclassified_field" and i.field == "track.rating"
        for i in result.issues
    )


def test_analysis_explains_generated_podcasts_and_ignores_forged_resolution() -> None:
    source = library(mirrored=True)
    original = source.serialize()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, podcast=t.track_id == 1))
            for t in source.snapshot.tracks
        ),
    )
    plan = source.analyze(source.begin_draft(desired))
    assert plan.changes[0].fields == ("metadata.podcast",)
    resolution = plan.resolution
    assert resolution is not None
    podcasts = next(p for p in resolution.snapshot.playlists if p.name == "Podcasts")
    assert podcasts.track_ids == (1,)
    assert any(
        c.record_id == podcasts.playlist_id and c.action == "add"
        for c in resolution.generated_changes
    )
    assert all(
        e.causes and all(0 <= i < len(plan.changes) for i in e.causes)
        for e in resolution.effects
    )
    assert any(e.code == "playlist.podcast_groups" for e in resolution.effects)
    forged = replace(
        plan,
        resolution=replace(
            resolution, snapshot=desired, effects=(), generated_changes=()
        ),
    )
    result = source.prepare(forged)
    assert result.prepared is not None, result.issues
    assert any(
        p.name == "Podcasts" and p.track_ids == (1,)
        for p in result.prepared.snapshot.playlists
    )
    assert source.serialize() == original
    assert len(desired.playlists) == len(source.snapshot.playlists)


def test_podcast_reclassification_does_not_require_replacing_media() -> None:
    source = library(mirrored=True)
    track = source.snapshot.tracks[0]
    converted = replace(
        track,
        media_types=(MediaType.PODCAST,),
        metadata=replace(
            track.metadata,
            podcast=True,
            skip_shuffle=True,
            remember_position=True,
        ),
    )
    desired = replace(
        source.snapshot,
        tracks=(converted, *source.snapshot.tracks[1:]),
    )

    plan = source.analyze(source.begin_draft(desired))

    assert plan.required_media == ()
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    reparsed = IPodLibrary(result.prepared.itunes)
    assert reparsed.snapshot.tracks[0].media_types == (MediaType.PODCAST,)


def test_resolution_exposes_derived_flags_and_quantization_before_writing() -> None:
    source = lyrics_source()
    track = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(
            replace(
                track,
                play_count=1,
                metadata=replace(
                    track.metadata, lyrics="Words", volume_adjustment_percent=1.0
                ),
            ),
            source.snapshot.tracks[1],
        ),
    )
    plan = source.analyze(source.begin_draft(desired))
    assert plan.resolution is not None
    resolved = plan.resolution.snapshot.tracks[0]
    assert resolved.metadata.has_lyrics and resolved.metadata.played
    assert resolved.metadata.volume_adjustment_percent == 3 / 255 * 100
    assert set(plan.resolution.generated_changes[0].fields) == {
        "metadata.has_lyrics",
        "metadata.played",
        "metadata.volume_adjustment_percent",
    }
    result = source.prepare(plan, WriteResources(lyrics=(lyrics_resource(resolved),)))
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks[0].metadata == resolved.metadata
    assert sum(i.code == "track.quantized" for i in result.issues) == 1


def test_normalization_gain_quantization_is_not_reported_as_a_warning() -> None:
    source = library()
    track = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(
            replace(
                track,
                metadata=replace(track.metadata, normalization_gain_db=-11.1),
            ),
            source.snapshot.tracks[1],
        ),
    )

    result = source.prepare(source.analyze(source.begin_draft(desired)))

    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks[
        0
    ].metadata.normalization_gain_db == pytest.approx(-11.0998, abs=1e-4)
    assert not any(
        issue.code == "track.quantized"
        and issue.field == "metadata.normalization_gain_db"
        for issue in result.issues
    )


def test_noop_has_no_generated_consequences_and_measures_only_entered_stages() -> None:
    source = library()
    plan = source.analyze(source.begin_draft())
    assert plan.resolution is not None
    assert plan.resolution.effects == ()
    assert plan.resolution.generated_changes == ()
    result = source.prepare(plan)
    assert result.prepared is not None
    assert [m.phase.value for m in result.measurements] == [
        "validation",
        "resources",
        "serialization",
    ]
    assert all(m.elapsed_ms >= 0 for m in result.measurements)
    assert result == source.prepare(plan)


def test_retained_index_bytes_are_rechecked_when_their_sort_inputs_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = library(mirrored=True)
    output = source.prepare(
        source.analyze(
            source.begin_draft(
                replace(source.snapshot, tracks=tuple(reversed(source.snapshot.tracks)))
            )
        ),
        WriteResources(pending_playback_sidecars=False),
    )
    assert output.prepared is not None
    source = IPodLibrary(output.prepared.itunes)
    baseline = next(
        s.chunk
        for s in parse_iTunesDB(output.prepared.itunes).find_chunks(MhodHeader)
        if isinstance(s.chunk.payload, MhodLibraryIndexPayload)
        and isinstance(s.chunk.prefix, MhodLibraryIndexPrefix)
        and s.chunk.prefix.sort_type == 3
    )

    def stale(document: DatabaseDocument[MhbdHeader]) -> bytes:
        for selection in document.find_chunks(MhodHeader):
            if (
                isinstance(selection.chunk.payload, MhodLibraryIndexPayload)
                and selection.chunk.prefix == baseline.prefix
            ):
                document = document.replace_chunk(
                    selection, replace(selection.chunk, payload=baseline.payload)
                )
        return write_iTunesDB(document)

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", stale)
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], title="AAA"),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(i.code == "verification.playlist_index" for i in result.issues)


def test_independent_folder_constraints_are_collected_before_reconciliation() -> None:
    from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
        MhodSmartNumericRuleData,
        MhodSmartRulesPayload,
    )
    from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader

    source = library(mirrored=True)
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(-1, "First folder", PlaylistKind.FOLDER),
            Playlist(-2, "Second folder", PlaylistKind.FOLDER),
            Playlist(
                -3, "First child", parent_id=-1, entries=(PlaylistEntry("first", 1),)
            ),
            Playlist(
                -4, "Second child", parent_id=-2, entries=(PlaylistEntry("second", 1),)
            ),
        ),
    )
    output = source.prepare(source.analyze(source.begin_draft(desired)))
    assert output.prepared is not None, output.issues
    document = parse_iTunesDB(output.prepared.itunes)
    for selection in document.find_chunks(MhypHeader):
        if not selection.chunk.header.playlist_kind_flags & 0x100:
            continue
        children: list[ParsedChunk[ChunkHeader]] = []
        for child in selection.chunk.children:
            if isinstance(child.payload, MhodSmartRulesPayload):
                child = replace(
                    child,
                    payload=replace(
                        child.payload,
                        rules=tuple(
                            replace(rule, data=replace(rule.data, from_value=0))
                            if isinstance(rule.data, MhodSmartNumericRuleData)
                            else rule
                            for rule in child.payload.rules
                        ),
                    ),
                )
            children.append(child)
        document = document.replace_chunk(
            selection, replace(selection.chunk, children=tuple(children))
        )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        playlists=tuple(
            replace(p, entries=(*p.entries, PlaylistEntry("added", 2)))
            if p.name.endswith("child")
            else p
            for p in source.snapshot.playlists
        ),
    )
    plan = source.analyze(source.begin_draft(desired))
    failures = [i for i in plan.issues if i.code == "playlist.folder_relationship"]
    assert len(failures) == 4  # Both folders, independently in each dataset.
    assert len({i.record_id for i in failures}) == 2
    assert all(i.field == "entries" and i.offset is not None for i in failures)
    phases: list[WritePhase] = []
    result = source.prepare(plan, progress=phases.append)
    assert result.prepared is None
    assert all(p.value != "reconciliation" for p in phases)
