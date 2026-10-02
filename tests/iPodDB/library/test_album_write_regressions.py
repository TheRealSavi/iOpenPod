"""Album edits through retained, dataset-aware Library preparation."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_playlist_datasets import podcast_source, rows
from tests.iPodDB.library.test_write_artwork import with_shared_artwork

from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.device_time import TimeConversion
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    PlaylistEntry,
    PlaylistSortOrder,
    _write_preparation,
)
from iPodDB.library._artwork_writing import reconcile_artwork
from iPodDB.library._reconcile import reconcile
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library.writing import (
    IdentityMapping,
    PreparedFile,
    WriteIssue,
    WriteResources,
    WriteTarget,
)
from iPodDB.shared.chunk import DatabaseDocument


def album_source(*, grouped: bool = False) -> IPodLibrary:
    source = podcast_source()
    document = parse_iTunesDB(source.serialize().itunes)
    track = document.find_chunks(MhitHeader)[0].chunk
    third = replace(track, header=replace(track.header, track_id=3, db_track_id=103))
    music = replace(
        track, header=replace(track.header, track_id=4, db_track_id=104, media_type=1)
    )
    dataset = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 1
    )
    container = dataset.chunk.children[0]
    document = document.replace_chunk(
        dataset,
        replace(
            dataset.chunk,
            children=(
                replace(container, children=(*container.children, third, music)),
            ),
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    initial = replace(
        source.snapshot,
        tracks=tuple(
            replace(
                t,
                title=f"Track {t.track_id}",
                album="1" if grouped and t.track_id == 3 else str(t.track_id),
            )
            for t in source.snapshot.tracks
        ),
        playlists=(
            replace(
                source.snapshot.playlists[0],
                sort_order=PlaylistSortOrder.TITLE,
                entries=tuple(PlaylistEntry(str(i), i) for i in (1, 2, 3)),
            ),
        ),
    )
    ready = source.prepare(source.analyze(source.begin_draft(initial)))
    assert ready.prepared is not None, ready.issues
    return IPodLibrary(ready.prepared.itunes)


def test_album_merge_regroups_podcasts_with_valid_flat_mirror_positions() -> None:
    source = album_source()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, album="1") if t.track_id == 3 else t
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, [
        (i.code, i.message, i.detail) for i in result.issues
    ]
    assert result.prepared.snapshot.playlists[0].track_ids == (1, 3, 2)
    checked = parse_iTunesDB(result.prepared.itunes)
    for dataset in (2, 3):
        episodes = [
            s.chunk
            for s in rows(checked, dataset)[1].find_chunks(MhipHeader)
            if s.chunk.header.track_id
        ]
        assert tuple(c.header.track_id for c in episodes) == (1, 3, 2)
        assert [
            next(
                c.prefix.position
                for c in item.children
                if isinstance(c.prefix, MhodPlaylistPositionPrefix)
            )
            for item in episodes
        ] == (
            list(range(3))
            if dataset == 2
            else [item.header.group_id for item in episodes]
        )


@pytest.mark.parametrize("dataset", [2, 3])
def test_verifier_rejects_bad_positions_with_occurrence_context(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, dataset: int
) -> None:
    source = album_source()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, album="1") if t.track_id == 3 else t
            for t in source.snapshot.tracks
        ),
    )

    def corrupt(
        document: DatabaseDocument[MhbdHeader],
        resolved: ResolvedWrite,
        resources: WriteResources,
        issues: list[WriteIssue],
        device_time: TimeConversion = 0,
    ) -> tuple[DatabaseDocument[MhbdHeader], tuple[IdentityMapping, ...]]:
        candidate, mappings = reconcile(
            document, resolved, resources, issues, device_time
        )
        episode = next(
            s
            for s in rows(candidate, dataset)[1].find_chunks(MhipHeader)
            if s.chunk.header.track_id
        )
        position = next(
            c
            for c in episode.chunk.children
            if isinstance(c.prefix, MhodPlaylistPositionPrefix)
        )
        assert isinstance(position.prefix, MhodPlaylistPositionPrefix)
        bad = replace(position, prefix=replace(position.prefix, position=999))
        children = (
            (*episode.chunk.children, bad)
            if dataset == 3
            else tuple(bad if c is position else c for c in episode.chunk.children)
        )
        candidate = candidate.replace_chunk(
            episode, replace(episode.chunk, children=children)
        )
        return candidate, mappings

    monkeypatch.setattr(_write_preparation, "reconcile", corrupt)
    caplog.set_level("DEBUG")
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    code = (
        "verification.playlist_position"
        if dataset == 2
        else "verification.podcast_position"
    )
    issue = next(i for i in result.issues if i.code == code)
    assert issue.artifact == "iTunesDB" and issue.offset is not None
    assert f"Dataset {dataset}" in issue.detail and "999" in issue.detail
    assert "expected position" in issue.detail and "actual positions" in issue.detail
    assert code in caplog.text and issue.detail in caplog.text


def test_album_rename_preserves_shared_artwork_bytes_ranges_and_native_links() -> None:
    source, _ = with_shared_artwork()
    before = source.serialize()
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, album="Renamed album") for t in source.snapshot.tracks),
    )
    plan = source.analyze(source.begin_draft(desired))
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    assert not plan.required_artwork and not plan.requires_artwork_inventory
    assert result.prepared.artwork == before.artwork
    assert not result.prepared.artwork_files
    assert result.prepared.retained_artwork
    old_tracks = parse_iTunesDB(before.itunes).find_chunks(MhitHeader)
    new_tracks = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)
    for old, new in zip(old_tracks, new_tracks, strict=True):
        assert (
            replace(old.chunk.header, child_count=new.chunk.header.child_count)
            == new.chunk.header
        )
    assert source.serialize() == before


def test_album_rename_rejects_unrequested_artwork_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader

    source, _ = with_shared_artwork()
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, album="Renamed") for t in source.snapshot.tracks),
    )

    def corrupt(
        itunes: DatabaseDocument[MhbdHeader],
        artwork: DatabaseDocument[MhfdHeader] | None,
        resolved: ResolvedWrite,
        mappings: tuple[IdentityMapping, ...],
        target: WriteTarget,
        resources: WriteResources,
    ) -> tuple[
        DatabaseDocument[MhbdHeader],
        DatabaseDocument[MhfdHeader] | None,
        tuple[PreparedFile, ...],
        tuple[IdentityMapping, ...],
    ]:
        itunes, artwork, files, mappings = reconcile_artwork(
            itunes, artwork, resolved, mappings, target, resources
        )
        assert artwork is not None
        row = artwork.find_chunks(MhiiHeader)[0]
        artwork = artwork.replace_chunk(
            row,
            replace(row.chunk, header=replace(row.chunk.header, source_image_size=999)),
        )
        return itunes, artwork, files, mappings

    monkeypatch.setattr(_write_preparation, "reconcile_artwork", corrupt)
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(i.code == "verification.unrequested_artwork" for i in result.issues)
