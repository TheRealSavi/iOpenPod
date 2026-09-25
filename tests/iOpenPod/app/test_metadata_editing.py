"""Typed metadata edits and Original iOpenPod normalization behavior."""

import json
from pathlib import Path
from typing import TypedDict, cast

import pytest

from iOpenPod.app.library_workspace import LibraryWorkspace, TrackUpdate
from iOpenPod.app.metadata_fields import metadata_fields
from iOpenPod.app.tag_normalizer import TagProfile, normalize_tags
from iPodDB.library import (
    LibrarySnapshot,
    Playlist,
    Track,
    TrackEditError,
    TrackFieldEdit,
    TrackMetadata,
    edit_track_metadata,
    editable_track_fields,
    playlist_entries,
)


class Profile(TypedDict):
    label: str
    has_cover_flow: bool
    album_artist_aware: bool


class Case(TypedDict):
    name: str
    tracks: list[dict[str, str | int]]
    profile: Profile
    changes: list[dict[str, str | int]]
    warnings: list[str]


def _cases() -> list[Case]:
    content = json.loads(
        (
            Path(__file__).parents[2] / "fixtures/normalization/original-cases.json"
        ).read_text(encoding="utf-8")
    )
    return cast("list[Case]", content["cases"])


_FIELDS = {
    "title": "Title",
    "artist": "Artist",
    "album": "Album",
    "album_artist": "Album Artist",
    "metadata.composer": "Composer",
    "metadata.compilation": "compilation_flag",
    **{
        "metadata.sort_" + field: "Sort " + label
        for field, label in (
            ("title", "Title"),
            ("artist", "Artist"),
            ("album", "Album"),
            ("album_artist", "Album Artist"),
            ("composer", "Composer"),
            ("show", "Show"),
        )
    },
}


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["name"])
def test_normalization_matches_captured_original_results(case: Case) -> None:
    tracks = tuple(
        Track(
            i,
            str(t.get("Title", "")),
            str(t.get("Artist", "")),
            str(t.get("Album", "")),
            180_000,
            album_artist=str(t.get("Album Artist", "")),
            metadata=TrackMetadata(
                composer=str(t.get("Composer", "")),
                compilation=bool(t.get("compilation_flag", 0)),
                sort_title=str(t.get("Sort Title", "")),
                sort_artist=str(t.get("Sort Artist", "")),
                sort_album=str(t.get("Sort Album", "")),
                sort_album_artist=str(t.get("Sort Album Artist", "")),
                sort_composer=str(t.get("Sort Composer", "")),
                sort_show=str(t.get("Sort Show", "")),
            ),
        )
        for i, t in enumerate(case["tracks"])
    )
    profile = TagProfile(**case["profile"])
    suggestion = normalize_tags(tracks, profile)
    changes = {
        u.track_id: {_FIELDS[e.field]: e.value for e in u.edits}
        for u in suggestion.updates
    }
    assert [changes.get(t.track_id, {}) for t in tracks] == case["changes"]
    assert suggestion.warnings == tuple(case["warnings"])
    edits = {u.track_id: u.edits for u in suggestion.updates}
    resulting = tuple(edit_track_metadata(t, edits.get(t.track_id, ())) for t in tracks)
    assert not normalize_tags(resulting, profile).updates


def test_editor_fields_cover_the_writer_metadata_policy() -> None:
    assert {f.path for f in metadata_fields()} == set(editable_track_fields())


def test_batch_is_atomic_and_stale_edits_cannot_overwrite_drafts() -> None:
    source = LibrarySnapshot(
        (
            Track(1, "One", "Artist", "Album", 100),
            Track(2, "Two", "Artist", "Album", 10),
        )
    )
    workspace = LibraryWorkspace()
    workspace.load(source)
    revision = workspace.edit_revision
    with pytest.raises(TrackEditError):
        workspace.apply_track_edits(
            tuple(
                TrackUpdate(t.track_id, (TrackFieldEdit("metadata.start_time_ms", 50),))
                for t in source.tracks
            ),
            revision,
        )
    assert workspace.desired_snapshot() == source
    assert workspace.edit_revision == revision
    workspace.apply_track_edits(
        (TrackUpdate(1, (TrackFieldEdit("title", "Changed"),)),), revision
    )
    with pytest.raises(ValueError, match="Library changed"):
        workspace.rename_device("Stale", revision)
    assert source.tracks[0].title == "One"
    assert workspace.tracks[0].title == "Changed"
    workspace.reset_changes()
    assert workspace.desired_snapshot() == source and not workspace.dirty


@pytest.mark.parametrize(
    "edit",
    [
        TrackFieldEdit("track_id", 12),
        TrackFieldEdit("length_ms", 30),
        TrackFieldEdit("metadata.has_lyrics", True),
        TrackFieldEdit("title", 42),
        TrackFieldEdit("year", True),
        TrackFieldEdit("year", 0.0),
        TrackFieldEdit("rating", 101),
        TrackFieldEdit("metadata.volume_adjustment_percent", float("nan")),
        TrackFieldEdit("title", "\ud800"),
    ],
)
def test_invalid_metadata_never_escapes(edit: TrackFieldEdit) -> None:
    with pytest.raises(TrackEditError):
        edit_track_metadata(Track(1, "A", "B", "C", 100), (edit,))


def test_occurrence_edits_keep_duplicate_metadata_identity() -> None:
    entries = playlist_entries((1, 2, 1, 2))
    playlist = Playlist(10, "Duplicates", entries=entries)
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            (Track(1, "A", "B", "C", 1), Track(2, "D", "B", "C", 1)), (playlist,)
        )
    )
    workspace.edit_entries(10, (entries[2].entry_id,), "up", workspace.edit_revision)
    changed = workspace.playlist(10)
    assert changed is not None
    assert tuple(entry.entry_id for entry in changed.entries) == (
        entries[0].entry_id,
        entries[2].entry_id,
        entries[1].entry_id,
        entries[3].entry_id,
    )
    assert tuple(entry.position for entry in changed.entries) == (0, 1, 2, 3)
    workspace.edit_entries(
        10, (entries[0].entry_id,), "remove", workspace.edit_revision
    )
    changed = workspace.playlist(10)
    assert changed is not None
    assert tuple(entry.entry_id for entry in changed.entries) == (
        entries[2].entry_id,
        entries[1].entry_id,
        entries[3].entry_id,
    )
    assert tuple(entry.position for entry in changed.entries) == (0, 1, 2)


def test_rename_is_a_reversible_edit_and_saving_locks_all_edits() -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(device_name="Old"))
    workspace.rename_device(" New ", workspace.edit_revision)
    assert workspace.desired_snapshot().device_name == "New"
    assert workspace.snapshot is not None and workspace.snapshot.device_name == "Old"
    workspace.set_locked(True)
    with pytest.raises(ValueError, match="save"):
        workspace.rename_device("Locked", workspace.edit_revision)
    workspace.set_locked(False)
    workspace.reset_changes()
    assert workspace.device_name == "Old"
