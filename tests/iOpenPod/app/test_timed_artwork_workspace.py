"""Timed artwork participates in the same atomic, reversible Track edits."""

import pytest

from iOpenPod.app.library_workspace import (
    LibraryWorkspace,
    TrackArtworkEdit,
    TrackUpdate,
)
from iPodDB.library import (
    ArtworkGroupReference,
    ArtworkPixels,
    LibrarySnapshot,
    TimedArtworkAsset,
    TimedArtworkFrame,
    Track,
    TrackFieldEdit,
)

RED = ArtworkPixels(1, 1, b"\xff\0\0")
BLUE = ArtworkPixels(1, 1, b"\0\0\xff")


def workspace() -> LibraryWorkspace:
    result = LibraryWorkspace()
    result.load(
        LibrarySnapshot(
            (
                Track(1, "One", "Artist", "Album", 30_000, artwork_id=101),
                Track(2, "Two", "Artist", "Album", 30_000, artwork_id=202),
            )
        )
    )
    return result


def test_sequence_and_metadata_apply_once_to_selection_and_reset_together() -> None:
    draft = workspace()
    original = draft.snapshot
    revision = draft.edit_revision
    frames = (TimedArtworkFrame(10_000, BLUE), TimedArtworkFrame(0, RED))

    draft.apply_track_edits(
        tuple(TrackUpdate(i, (TrackFieldEdit("album", "New"),)) for i in (1, 2)),
        revision,
        artwork=TrackArtworkEdit(None, frames=frames),
    )

    assert draft.revision == revision.revision + 1
    assert len(draft.artwork_assets) == 1
    asset = draft.artwork_assets[0]
    assert isinstance(asset, TimedArtworkAsset)
    assert asset.frames == tuple(reversed(frames))
    assert asset.artwork_id < 0
    assert all(
        t.artwork_id == asset.artwork_id and t.album == "New" for t in draft.tracks
    )
    assert original is not None and original.tracks[0].artwork_id == 101
    with pytest.raises(ValueError, match="changed"):
        draft.set_artwork((1,), None, revision)
    draft.reset_changes()
    assert not draft.artwork_assets and not draft.dirty
    assert draft.tracks == original.tracks


def test_retained_references_survive_reediting_a_draft_but_reject_unselected_sources() -> (
    None
):
    draft = workspace()
    zero = TimedArtworkFrame(0, ArtworkGroupReference(101, 0))
    later = TimedArtworkFrame(10_000, ArtworkGroupReference(101, 5_000))
    draft.apply_track_edits(
        (TrackUpdate(1, ()),),
        draft.edit_revision,
        artwork=TrackArtworkEdit(None, frames=(zero, later)),
    )
    draft.apply_track_edits(
        (TrackUpdate(1, ()),),
        draft.edit_revision,
        artwork=TrackArtworkEdit(
            None, frames=(zero, TimedArtworkFrame(20_000, later.source))
        ),
    )
    asset = draft.artwork_assets[0]
    assert isinstance(asset, TimedArtworkAsset)
    assert asset.frames[1].source == ArtworkGroupReference(101, 5_000)
    assert asset.frames[1].display_time_ms == 20_000
    revision = draft.edit_revision
    with pytest.raises(ValueError, match="not part of the Track selection"):
        draft.apply_track_edits(
            (TrackUpdate(1, ()),),
            revision,
            artwork=TrackArtworkEdit(
                None, frames=(TimedArtworkFrame(0, ArtworkGroupReference(202, 0)),)
            ),
        )
    assert draft.edit_revision == revision and draft.artwork_assets == (asset,)


def test_ordinary_cover_refresh_preserves_later_frames_in_a_timed_draft() -> None:
    draft = workspace()
    later = TimedArtworkFrame(10_000, ArtworkGroupReference(101, 10_000))
    draft.apply_track_edits(
        (TrackUpdate(1, ()),),
        draft.edit_revision,
        artwork=TrackArtworkEdit(None, frames=(TimedArtworkFrame(0, RED), later)),
    )
    draft.set_artwork((1,), BLUE, draft.edit_revision)
    assert len(draft.artwork_assets) == 1
    asset = draft.artwork_assets[0]
    assert isinstance(asset, TimedArtworkAsset)
    assert asset.frames == (TimedArtworkFrame(0, BLUE), later)
    draft.apply_track_edits(
        (TrackUpdate(1, ()),),
        draft.edit_revision,
        artwork=TrackArtworkEdit(None, frames=()),
    )
    assert not draft.artwork_assets and draft.tracks[0].artwork_id == 0


def test_invalid_metadata_does_not_publish_partial_timed_artwork() -> None:
    draft = workspace()
    revision = draft.edit_revision
    with pytest.raises(ValueError):
        draft.apply_track_edits(
            (TrackUpdate(1, (TrackFieldEdit("rating", 101),)),),
            revision,
            artwork=TrackArtworkEdit(None, frames=(TimedArtworkFrame(0, RED),)),
        )
    assert draft.edit_revision == revision and not draft.artwork_assets
    assert draft.tracks[0].artwork_id == 101


def test_duplicate_or_reserved_authored_times_are_rejected() -> None:
    with pytest.raises(ValueError):
        TrackArtworkEdit(
            None, frames=(TimedArtworkFrame(0, RED), TimedArtworkFrame(0, BLUE))
        )
    with pytest.raises(ValueError):
        TrackArtworkEdit(
            None,
            frames=(TimedArtworkFrame(0, RED), TimedArtworkFrame(0xFFFFFFFF, BLUE)),
        )
    with pytest.raises(ValueError):
        TrackArtworkEdit(None, frames=(TimedArtworkFrame(10_000, RED),))
    with pytest.raises(ValueError):
        TrackArtworkEdit(RED, frames=(TimedArtworkFrame(0, BLUE),))


def test_cover_refresh_rejects_conflicting_unsaved_sequences_without_losing_frames() -> (
    None
):
    draft = workspace()
    for track_id, time in ((1, 10_000), (2, 20_000)):
        draft.apply_track_edits(
            (TrackUpdate(track_id, ()),),
            draft.edit_revision,
            artwork=TrackArtworkEdit(
                None, frames=(TimedArtworkFrame(0, RED), TimedArtworkFrame(time, BLUE))
            ),
        )
    revision, assets, tracks = draft.edit_revision, draft.artwork_assets, draft.tracks
    with pytest.raises(ValueError, match="different artwork sequences"):
        draft.set_artwork((1, 2), BLUE, revision)
    assert draft.edit_revision == revision
    assert draft.artwork_assets == assets and draft.tracks == tracks


def test_consolidating_an_existing_draft_keeps_its_complete_sequence() -> None:
    draft = workspace()
    zero = TimedArtworkFrame(0, ArtworkGroupReference(101, 0))
    later = TimedArtworkFrame(10_000, BLUE)
    draft.apply_track_edits(
        (TrackUpdate(1, ()),),
        draft.edit_revision,
        artwork=TrackArtworkEdit(None, frames=(zero, later)),
    )
    asset = draft.artwork_assets[0]
    draft.apply_track_edits(
        (TrackUpdate(1, ()), TrackUpdate(2, ())),
        draft.edit_revision,
        artwork=TrackArtworkEdit(None, source_artwork_id=asset.artwork_id),
    )
    assert all(track.artwork_id == asset.artwork_id for track in draft.tracks)
    assert draft.artwork_assets == (asset,)
    draft.apply_track_edits(
        (TrackUpdate(1, ()), TrackUpdate(2, ())),
        draft.edit_revision,
        artwork=TrackArtworkEdit(
            None, frames=(zero, TimedArtworkFrame(5_000, later.source))
        ),
    )
    assert len(draft.artwork_assets) == 1
    updated = draft.artwork_assets[0]
    assert isinstance(updated, TimedArtworkAsset) and updated.frames[0] == zero
