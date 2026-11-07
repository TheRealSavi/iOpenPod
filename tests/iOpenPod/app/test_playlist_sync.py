"""Playlist choices retain identity, occurrence order, and explicit skip semantics."""

from dataclasses import replace

import pytest

from iOpenPod.app.playlist_sync import (
    PlaylistAssociation,
    PlaylistSyncChoice,
    reconcile_playlist_sync,
)
from iPodDB.library import Playlist, PlaylistKind, playlist_entries


def test_saved_match_survives_title_and_membership_changes() -> None:
    original = Playlist(10, "Old title", entries=playlist_entries((1, 2, 1)))
    host = Playlist(100, "New title", entries=playlist_entries((20, 10, 10)))
    playlists, rows, associations = reconcile_playlist_sync(
        (host,),
        (original,),
        {10: 1, 20: 2},
        selected={10, 20},
        unresolved=set(),
        incomplete=frozenset(),
        associations=(PlaylistAssociation(100, 10),),
    )
    assert len(playlists) == 1
    assert playlists[0].playlist_id == 10
    assert playlists[0].name == "New title"
    assert playlists[0].track_ids == (2, 1, 1)
    assert {entry.entry_id for entry in playlists[0].entries} == {
        entry.entry_id for entry in original.entries
    }
    assert rows[0].change is not None
    assert rows[0].change.renamed and rows[0].change.order_changed
    assert rows[0].match_detail == "Saved match"
    assert associations == (PlaylistAssociation(100, 10),)


def test_unchecking_one_playlist_preserves_it_without_changing_track_mapping() -> None:
    hosts = (Playlist(100, "A"), Playlist(200, "B"))
    original = (Playlist(10, "A", entries=playlist_entries((1,))), Playlist(20, "B"))
    mapping = {1000: 1}
    playlists, rows, applied = reconcile_playlist_sync(
        hosts,
        original,
        mapping,
        selected=set(),
        unresolved=set(),
        incomplete=frozenset(),
        choices=(PlaylistSyncChoice(100, included=False),),
    )
    assert playlists == original
    assert mapping == {1000: 1}
    assert not rows[0].actionable
    assert rows[1].actionable  # Save a first match even with unchanged membership.
    assert applied == (PlaylistAssociation(200, 20),)


@pytest.mark.parametrize("target_id", [None, 10])
def test_explicit_choice_resolves_duplicate_names(target_id: int | None) -> None:
    hosts = (Playlist(100, "Same"), Playlist(200, "Same"))
    original = (Playlist(10, "Same"), Playlist(20, "Same"))
    playlists, rows, applied = reconcile_playlist_sync(
        hosts,
        original,
        {},
        selected=set(),
        unresolved=set(),
        incomplete=frozenset(),
        choices=(
            PlaylistSyncChoice(100, automatic=False, target_id=target_id),
            PlaylistSyncChoice(200, included=False),
        ),
    )
    assert not rows[0].issue_code
    assert rows[1].issue_code == "sync.playlist_ambiguous"
    assert len(playlists) == (3 if target_id is None else 2)
    assert len(applied) == 1
    assert applied[0].ipod_playlist_id == (-1 if target_id is None else 10)


def test_competing_target_blocks_both_until_one_is_unchecked() -> None:
    hosts = (Playlist(100, "A"), Playlist(200, "B"))
    original = (Playlist(10, "A"),)
    choices = (PlaylistSyncChoice(200, automatic=False, target_id=10),)
    playlists, rows, applied = reconcile_playlist_sync(
        hosts,
        original,
        {},
        selected=set(),
        unresolved=set(),
        incomplete=frozenset(),
        choices=choices,
    )
    assert playlists == original and not applied
    assert all(row.issue_code == "sync.playlist_ambiguous" for row in rows)
    playlists, rows, applied = reconcile_playlist_sync(
        hosts,
        original,
        {},
        selected=set(),
        unresolved=set(),
        incomplete=frozenset(),
        choices=(*choices, PlaylistSyncChoice(100, included=False)),
    )
    assert playlists[0].name == "B"
    assert applied == (PlaylistAssociation(200, 10),)


@pytest.mark.parametrize("reason", ["incomplete", "unresolved", "failed", "unselected"])
def test_blocked_playlists_are_visible_and_never_advance_associations(
    reason: str,
) -> None:
    host = Playlist(100, "A", entries=playlist_entries((1000,)))
    original = Playlist(10, "A", entries=playlist_entries((1,)))
    playlists, rows, applied = reconcile_playlist_sync(
        (host,),
        (original,),
        {},
        selected={1000} if reason == "failed" else set(),
        unresolved={1000} if reason == "unresolved" else set(),
        incomplete=frozenset({100}) if reason == "incomplete" else frozenset(),
    )
    assert playlists == (original,)
    assert not applied and not rows[0].actionable
    assert rows[0].issue_code and rows[0].detail


@pytest.mark.parametrize(
    "target",
    [
        None,
        Playlist(10, "A", system_managed=True),
        Playlist(10, "A", kind=PlaylistKind.FOLDER),
    ],
)
def test_saved_match_cannot_fall_back_to_a_different_playlist(
    target: Playlist | None,
) -> None:
    original = (Playlist(20, "A"),) if target is None else (target, Playlist(20, "A"))
    playlists, rows, applied = reconcile_playlist_sync(
        (Playlist(100, "A"),),
        original,
        {},
        selected=set(),
        unresolved=set(),
        incomplete=frozenset(),
        associations=(PlaylistAssociation(100, 10),),
    )
    assert playlists == original and not applied
    assert rows[0].issue_code == "sync.playlist_ambiguous"


def test_explicit_new_playlist_leaves_same_named_device_playlist_untouched() -> None:
    original = Playlist(10, "A", entries=playlist_entries((1,)))
    playlists, rows, applied = reconcile_playlist_sync(
        (Playlist(100, "A"),),
        (original,),
        {},
        selected=set(),
        unresolved=set(),
        incomplete=frozenset(),
        choices=(PlaylistSyncChoice(100, automatic=False),),
    )
    assert playlists[0] == original
    assert playlists[1] == replace(Playlist(-1, "A"), entries=())
    assert rows[0].change is not None and rows[0].change.action == "create"
    assert applied == (PlaylistAssociation(100, -1),)
