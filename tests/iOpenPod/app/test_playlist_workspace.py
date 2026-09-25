"""Playlist drafts retain source data and cannot escape one Active iPod session."""

from dataclasses import replace
from sys import getrecursionlimit

import pytest
from tests.iPodDB.library.test_album_write_regressions import album_source

from iOpenPod.app.library_workspace import (
    LibraryWorkspace,
    TrackArtworkEdit,
    TrackUpdate,
)
from iPodDB.library import (
    ArtworkPixels,
    LibrarySnapshot,
    Playlist,
    PlaylistKind,
    PlaylistSortOrder,
    SmartField,
    SmartOperator,
    SmartPlaylist,
    SmartPlaylistReference,
    SmartRule,
    SmartRuleGroup,
    Track,
    TrackFieldEdit,
    UnsupportedSmartRule,
    playlist_entries,
)


def _track(track_id: int) -> Track:
    return Track(track_id, f"Song {track_id}", "An artist", "An album", 120_000)


def test_music_album_edit_preserves_system_podcasts_and_prepares() -> None:
    source = album_source(grouped=True)
    workspace = LibraryWorkspace()
    workspace.load(source.snapshot)
    workspace.apply_track_edits(
        (TrackUpdate(4, (TrackFieldEdit("album", "Renamed music"),)),),
        workspace.edit_revision,
    )
    plan = source.analyze(source.begin_draft(workspace.desired_snapshot()))
    result = source.prepare(plan)
    assert result.prepared is not None, [
        (i.code, i.message, i.detail) for i in result.issues
    ]
    assert workspace.playlists == source.snapshot.playlists
    assert [(c.subject, c.record_id, c.fields) for c in plan.changes] == [
        ("track", 4, ("album",))
    ]
    assert plan.resolution is not None and not plan.resolution.generated_changes


def test_artwork_and_deletions_follow_the_same_workspace_revision() -> None:
    playlist = Playlist(10, "Repeated", entries=playlist_entries((0, 1, 0, 2)))
    workspace = _workspace(playlist)
    original = workspace.snapshot
    pixels = ArtworkPixels(1, 1, b"\xff\0\0")
    revision = workspace.edit_revision
    workspace.set_artwork((0, 1), pixels, revision)
    assert len(workspace.artwork_assets) == 1
    identity = workspace.artwork_assets[0].artwork_id
    assert (
        identity < 0
        and workspace.tracks[0].artwork_id == workspace.tracks[1].artwork_id == identity
    )
    with pytest.raises(ValueError, match="changed"):
        workspace.remove_tracks((0,), revision)
    with pytest.raises(ValueError, match="missing or repeated"):
        workspace.remove_tracks((0, 999), workspace.edit_revision)
    assert len(workspace.tracks) == 3
    workspace.remove_tracks((0,), workspace.edit_revision)
    assert workspace.playlists[0].track_ids == (1, 2)
    assert workspace.playlists[0].entries == (playlist.entries[1], playlist.entries[3])
    assert workspace.delete_omissions and len(workspace.artwork_assets) == 1
    workspace.set_artwork((1,), None, workspace.edit_revision)
    assert not workspace.artwork_assets
    assert original is not None and original.tracks[0].artwork_id == 0
    workspace.reset_changes()
    assert (
        not workspace.delete_omissions
        and not workspace.artwork_assets
        and not workspace.dirty
    )
    workspace.load(original)
    assert (
        not workspace.delete_omissions
        and not workspace.artwork_assets
        and not workspace.dirty
    )


def test_metadata_and_artwork_publish_as_one_atomic_track_edit() -> None:
    workspace = _workspace()
    pixels = ArtworkPixels(1, 1, b"\xff\0\0")
    revision = workspace.edit_revision

    workspace.apply_track_edits(
        (
            TrackUpdate(0, (TrackFieldEdit("title", "Shared edit"),)),
            TrackUpdate(1, (TrackFieldEdit("title", "Shared edit"),)),
        ),
        revision,
        artwork=TrackArtworkEdit(pixels),
    )

    assert workspace.edit_revision.revision == revision.revision + 1
    assert tuple(track.title for track in workspace.tracks[:2]) == (
        "Shared edit",
        "Shared edit",
    )
    assert len(workspace.artwork_assets) == 1
    artwork_id = workspace.artwork_assets[0].artwork_id
    assert artwork_id < 0
    assert tuple(track.artwork_id for track in workspace.tracks[:2]) == (
        artwork_id,
        artwork_id,
    )

    failed_revision = workspace.edit_revision
    with pytest.raises(ValueError):
        workspace.apply_track_edits(
            (TrackUpdate(2, (TrackFieldEdit("rating", 101),)),),
            failed_revision,
            artwork=TrackArtworkEdit(ArtworkPixels(1, 1, b"\0\xff\0")),
        )
    assert workspace.edit_revision == failed_revision
    assert len(workspace.artwork_assets) == 1
    assert workspace.tracks[2].artwork_id == 0


def test_existing_artwork_can_be_consolidated_without_creating_an_asset() -> None:
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            (
                replace(_track(0), artwork_id=101),
                replace(_track(1), artwork_id=202),
                replace(_track(2), artwork_id=202),
            )
        )
    )
    revision = workspace.edit_revision

    workspace.apply_track_edits(
        tuple(TrackUpdate(track_id, ()) for track_id in (0, 1, 2)),
        revision,
        artwork=TrackArtworkEdit(None, source_artwork_id=101),
    )

    assert workspace.edit_revision.revision == revision.revision + 1
    assert tuple(track.artwork_id for track in workspace.tracks) == (101, 101, 101)
    assert not workspace.artwork_assets

    with pytest.raises(ValueError, match="not part of the Track selection"):
        workspace.apply_track_edits(
            (TrackUpdate(0, ()),),
            workspace.edit_revision,
            artwork=TrackArtworkEdit(None, source_artwork_id=999),
        )


def _workspace(*playlists: Playlist) -> LibraryWorkspace:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(tuple(_track(i) for i in range(3)), playlists))
    return workspace


def test_regular_playlist_tracks_keep_order_and_duplicates_without_source_mutation() -> (
    None
):
    original = Playlist(10, "On the road", entries=playlist_entries((2, 0, 2)))
    workspace = _workspace(original)
    snapshot = workspace.snapshot

    assert tuple(track.track_id for track in workspace.tracks_for(10)) == (2, 0, 2)
    workspace.rename(10, "  Evening drive  ")
    workspace.set_tracks(10, (0, 1, 1, 2))

    assert workspace.dirty
    updated = workspace.playlist(10)
    assert updated is not None and updated.name == "Evening drive"
    assert updated.track_ids == (0, 1, 1, 2)
    assert updated.entries[0].entry_id == original.entries[1].entry_id
    assert updated.entries[-1].entry_id == original.entries[0].entry_id
    assert tuple(entry.position for entry in updated.entries) == (0, 1, 2, 3)
    assert workspace.snapshot is snapshot
    assert snapshot is not None and snapshot.playlists == (original,)
    assert original.track_ids == (2, 0, 2)
    assert tuple(track.track_id for track in workspace.tracks_for(10)) == (0, 1, 1, 2)


def test_smart_playlist_membership_rules_use_current_saved_playlist_entries() -> None:
    regular = Playlist(10, "Source", entries=playlist_entries((0, 2)))
    workspace = _workspace(regular)
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(
                SmartRule(
                    SmartField.PLAYLIST,
                    SmartOperator.IS,
                    SmartPlaylistReference(10),
                ),
            )
        )
    )

    created = workspace.create(PlaylistKind.SMART, "From source", smart=smart)

    assert created.track_ids == (0, 2)
    self_rule = replace(
        smart,
        rules=SmartRuleGroup(
            rules=(
                SmartRule(
                    SmartField.PLAYLIST,
                    SmartOperator.IS,
                    SmartPlaylistReference(created.playlist_id),
                ),
            )
        ),
    )
    with pytest.raises(ValueError, match="own saved membership"):
        workspace.edit_smart(created.playlist_id, self_rule)


def test_evaluate_smart_refreshes_only_its_saved_membership() -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.TITLE, SmartOperator.IS, "Song 1"),)
        )
    )
    original = Playlist(
        10,
        "Current matches",
        PlaylistKind.SMART,
        entries=playlist_entries((2, 1)),
        smart=smart,
        sort_order=PlaylistSortOrder.TITLE,
    )
    unrelated = Playlist(11, "Unrelated", entries=playlist_entries((0,)))
    workspace = _workspace(original, unrelated)
    revision = workspace.revision

    updated = workspace.evaluate_smart(original.playlist_id)

    assert updated.smart is smart
    assert updated.track_ids == (1,)
    assert updated.entries[0].entry_id == original.entries[1].entry_id
    assert updated.entries[0].position == 0
    assert workspace.playlist(unrelated.playlist_id) is unrelated
    assert workspace.revision == revision + 1

    assert workspace.evaluate_smart(original.playlist_id) == updated
    assert workspace.playlist(original.playlist_id) is updated
    assert workspace.revision == revision + 1


@pytest.mark.parametrize(
    "playlist",
    (
        Playlist(10, "Regular"),
        Playlist(
            10,
            "Read only",
            PlaylistKind.SMART,
            smart=SmartPlaylist(editable=False),
        ),
    ),
)
def test_only_supported_smart_playlists_can_be_evaluated(playlist: Playlist) -> None:
    workspace = _workspace(playlist)
    revision = workspace.revision

    with pytest.raises(ValueError, match=r"Smart Playlist|read-only"):
        workspace.evaluate_smart(playlist.playlist_id)

    assert workspace.playlist(playlist.playlist_id) is playlist
    assert workspace.revision == revision


def test_sort_order_change_stably_reorders_occurrences_and_refreshes_positions() -> (
    None
):
    original = Playlist(
        10,
        "Out of order",
        entries=playlist_entries((2, 0, 2, 1)),
        sort_order=PlaylistSortOrder.MANUAL,
    )
    workspace = _workspace(original)

    updated = workspace.update(10, sort_order=PlaylistSortOrder.TITLE)

    assert updated.sort_order is PlaylistSortOrder.TITLE
    assert updated.track_ids == (0, 1, 2, 2)
    assert tuple(entry.position for entry in updated.entries) == (0, 1, 2, 3)
    assert {entry.entry_id for entry in updated.entries} == {
        entry.entry_id for entry in original.entries
    }
    assert original.track_ids == (2, 0, 2, 1)


def test_manual_moves_are_rejected_for_a_field_sorted_playlist() -> None:
    playlist = Playlist(
        10,
        "Sorted",
        entries=playlist_entries((0, 1)),
        sort_order=PlaylistSortOrder.TITLE,
    )
    workspace = _workspace(playlist)

    with pytest.raises(ValueError, match="Manual Playlist sort order"):
        workspace.edit_entries(
            10,
            (playlist.entries[1].entry_id,),
            "up",
            workspace.edit_revision,
        )


def test_track_sort_key_edits_keep_field_sorted_playlist_positions_coherent() -> None:
    playlist = Playlist(
        10,
        "Sorted",
        entries=playlist_entries((0, 1, 2)),
        sort_order=PlaylistSortOrder.TITLE,
    )
    workspace = _workspace(playlist)

    workspace.apply_track_edits(
        (TrackUpdate(2, (TrackFieldEdit("title", "A first song"),)),),
        workspace.edit_revision,
    )

    updated = workspace.playlist(10)
    assert updated is not None
    assert updated.track_ids == (2, 0, 1)
    assert tuple(entry.position for entry in updated.entries) == (0, 1, 2)


def test_reset_changes_restores_original_records_and_draft_ids_are_never_reused() -> (
    None
):
    original = Playlist(10, "Original")
    workspace = _workspace(original)
    generation = workspace.generation
    first = workspace.create(PlaylistKind.PLAYLIST, "New")
    workspace.rename(10, "Renamed")

    workspace.reset_changes()

    assert not workspace.dirty
    assert workspace.playlists == (original,)
    assert workspace.playlist(10) is original
    assert workspace.generation == generation
    second = workspace.create(PlaylistKind.PLAYLIST, "Another")
    assert first.playlist_id != second.playlist_id
    with pytest.raises(ValueError, match="no longer"):
        workspace.rename(first.playlist_id, "An obsolete edit")


def test_nested_folders_move_to_other_folders_and_root_without_cycles() -> None:
    outer = Playlist(10, "Outer", PlaylistKind.FOLDER)
    inner = Playlist(11, "Inner", PlaylistKind.FOLDER, 10)
    playlist = Playlist(12, "Mix", parent_id=11)
    workspace = _workspace(outer, inner, playlist)

    assert workspace.children_of() == (outer,)
    assert workspace.children_of(10) == (inner,)
    assert not workspace.can_move(10, 11)
    assert not workspace.can_move(10, 10)
    assert not workspace.can_move(10, 12)
    assert not workspace.can_move(10, 999)
    assert not workspace.can_move(999, None)
    with pytest.raises(ValueError, match="outside"):
        workspace.move(10, 11)
    assert workspace.move(12, 10)
    assert workspace.playlist(12) == replace(playlist, parent_id=10)
    assert workspace.move(11, None)
    assert workspace.children_of() == (outer, replace(inner, parent_id=None))
    assert workspace.can_move(10, 11)
    assert workspace.move(10, 11)
    assert not workspace.can_move(11, 10)
    assert not workspace.move(10, 11)


def test_remove_folder_removes_all_descendants_and_authorizes_their_omission() -> None:
    outer = Playlist(10, "Outer", PlaylistKind.FOLDER)
    removed = Playlist(11, "Removed", PlaylistKind.FOLDER, parent_id=10)
    child_folder = Playlist(12, "Child folder", PlaylistKind.FOLDER, parent_id=11)
    child_playlist = Playlist(13, "Child playlist", parent_id=11)
    grandchild = Playlist(14, "Grandchild", parent_id=12)
    workspace = _workspace(outer, removed, child_folder, child_playlist, grandchild)

    result = workspace.remove_playlist(11, workspace.edit_revision)

    assert result is removed
    assert workspace.playlist(11) is None
    assert workspace.children_of(10) == ()
    assert all(workspace.playlist(item_id) is None for item_id in (12, 13, 14))
    assert workspace.playlists == (outer,)
    assert workspace.delete_omissions
    assert workspace.dirty


def test_removing_a_new_playlist_can_restore_a_clean_draft_without_deletion() -> None:
    system = Playlist(20, "Podcasts", system_managed=True)
    workspace = _workspace(system)
    created = workspace.create(PlaylistKind.PLAYLIST, "Temporary")
    revision = workspace.edit_revision

    workspace.remove_playlist(created.playlist_id, revision)

    assert not workspace.dirty
    assert not workspace.delete_omissions
    with pytest.raises(ValueError, match="managed by the iPod"):
        workspace.remove_playlist(system.playlist_id, workspace.edit_revision)
    with pytest.raises(ValueError, match="changed"):
        workspace.remove_playlist(system.playlist_id, revision)


def test_folder_contents_follow_deep_hierarchy_and_draft_moves_without_recursion() -> (
    None
):
    depth = getrecursionlimit() + 100
    folders = tuple(
        Playlist(
            10 + index,
            f"Folder {index}",
            PlaylistKind.FOLDER,
            None if index == 0 else 9 + index,
        )
        for index in range(depth)
    )
    first = Playlist(
        10 + depth, "First", parent_id=9 + depth, entries=playlist_entries((2, 0, 2))
    )
    second = Playlist(
        11 + depth, "Second", parent_id=9 + depth, entries=playlist_entries((1, 2))
    )
    workspace = _workspace(*folders, first, second)

    assert tuple(track.track_id for track in workspace.tracks_for(10)) == (2, 0, 1)
    assert not workspace.can_move(10, 9 + depth)
    assert workspace.can_move(first.playlist_id, 9 + depth)
    assert workspace.move(first.playlist_id, None)
    assert tuple(track.track_id for track in workspace.tracks_for(10)) == (1, 2)
    assert tuple(
        track.track_id for track in workspace.tracks_for(first.playlist_id)
    ) == (
        2,
        0,
        2,
    )


def test_create_all_playlist_kinds_and_edit_names_descriptions_and_membership() -> None:
    workspace = _workspace()
    folder = workspace.create(PlaylistKind.FOLDER, "Trips")
    regular = workspace.create(PlaylistKind.PLAYLIST, "Train", folder.playlist_id)
    smart = workspace.create(PlaylistKind.SMART, "All songs", folder.playlist_id)

    workspace.update(folder.playlist_id, name="Travel", description="Across the world")
    workspace.set_tracks(regular.playlist_id, (2, 1))

    assert workspace.dirty
    assert smart.smart is not None
    assert smart.smart == SmartPlaylist()
    assert smart.track_ids == (0, 1, 2)
    assert tuple(t.track_id for t in workspace.preview(smart.smart)) == (0, 1, 2)
    updated_folder = workspace.playlist(folder.playlist_id)
    assert updated_folder is not None
    assert updated_folder.name == "Travel"
    assert updated_folder.description == "Across the world"
    assert len(workspace.children_of(folder.playlist_id)) == 2


def test_imported_smart_membership_is_independent_of_rule_edits_and_preview() -> None:
    rules = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.TITLE, SmartOperator.CONTAINS, "Song"),)
        )
    )
    original = Playlist(
        10, "Smart mix", PlaylistKind.SMART, entries=playlist_entries((2,)), smart=rules
    )
    folder = Playlist(11, "Folder", PlaylistKind.FOLDER)
    workspace = _workspace(original, folder)

    workspace.rename(10, "Renamed smart mix")
    workspace.move(10, 11)

    assert tuple(track.track_id for track in workspace.tracks_for(10)) == (2,)
    assert tuple(track.track_id for track in workspace.preview(rules)) == (0, 1, 2)
    assert workspace.playlist(10) == replace(
        original, name="Renamed smart mix", parent_id=11
    )

    workspace.edit_smart(10, rules)

    assert tuple(track.track_id for track in workspace.tracks_for(10)) == (2,)
    assert workspace.desired_snapshot().playlists[0].entries == original.entries
    assert original.track_ids == (2,)


@pytest.mark.parametrize(
    "smart",
    (
        SmartPlaylist(editable=False),
        SmartPlaylist(rules=SmartRuleGroup(rules=(UnsupportedSmartRule(),))),
    ),
)
def test_unsupported_smart_rules_remain_read_only_but_names_can_change(
    smart: SmartPlaylist,
) -> None:
    original = Playlist(
        10,
        "Imported",
        PlaylistKind.SMART,
        entries=playlist_entries((2, 1)),
        smart=smart,
    )
    workspace = _workspace(original)

    workspace.rename(10, "Renamed")
    with pytest.raises(ValueError, match="read-only"):
        workspace.update(10, name="Should not apply", smart=SmartPlaylist())

    assert workspace.playlist(10) == replace(original, name="Renamed")
    assert tuple(track.track_id for track in workspace.tracks_for(10)) == (2, 1)


def test_invalid_edits_are_atomic_and_do_not_publish_state_changes() -> None:
    original = Playlist(10, "Original")
    workspace = _workspace(original)
    changes: list[bool] = []
    workspace.changed.connect(lambda: changes.append(True))

    with pytest.raises(ValueError, match="name"):
        workspace.rename(10, "  \t")
    with pytest.raises(ValueError, match="no longer"):
        workspace.rename(999, "Missing")
    with pytest.raises(ValueError, match="no longer"):
        workspace.set_tracks(10, (0, 999))
    with pytest.raises(ValueError, match="Folder"):
        workspace.create(PlaylistKind.PLAYLIST, "Bad parent", 10)
    with pytest.raises(ValueError, match="Smart Playlist"):
        workspace.update(10, name="Invalid", smart=SmartPlaylist())
    with pytest.raises(ValueError, match="Smart Playlist"):
        workspace.create(PlaylistKind.FOLDER, "Invalid", smart=SmartPlaylist())
    workspace.rename(10, "Original")
    workspace.move(10, None)
    workspace.reset_changes()

    assert workspace.playlists == (original,)
    assert not workspace.dirty
    assert changes == []


def test_disconnection_and_another_snapshot_discard_drafts_and_advance_generation() -> (
    None
):
    workspace = _workspace(Playlist(10, "Original"))
    generation = workspace.generation
    draft = workspace.create(PlaylistKind.PLAYLIST, "A draft")

    workspace.load(None)

    assert workspace.snapshot is None
    assert workspace.generation == generation + 1
    assert workspace.playlists == ()
    assert not workspace.dirty
    assert not workspace.can_move(draft.playlist_id, None)
    with pytest.raises(ValueError, match="Select an iPod"):
        workspace.create(PlaylistKind.PLAYLIST, "Disconnected")
    with pytest.raises(ValueError, match="Select an iPod"):
        workspace.set_tracks(draft.playlist_id, ())

    workspace.load(LibrarySnapshot())
    replacement = workspace.create(PlaylistKind.FOLDER, "New iPod folder")
    assert replacement.playlist_id != draft.playlist_id
    assert workspace.generation == generation + 2
    assert workspace.playlist(draft.playlist_id) is None


def test_regular_membership_cannot_be_applied_to_folders_or_smart_playlists() -> None:
    workspace = _workspace()
    for kind in (PlaylistKind.FOLDER, PlaylistKind.SMART):
        playlist = workspace.create(kind, kind.value)
        with pytest.raises(ValueError, match="only in a Playlist"):
            workspace.set_tracks(playlist.playlist_id, (0, 1))


def test_rule_apply_updates_membership_atomically_and_preserves_surviving_occurrences() -> (
    None
):
    original = Playlist(
        10,
        "Smart",
        PlaylistKind.SMART,
        entries=playlist_entries((2, 0)),
        smart=SmartPlaylist(),
    )
    unrelated = Playlist(
        11,
        "Unrelated",
        PlaylistKind.SMART,
        entries=playlist_entries((1,)),
        smart=SmartPlaylist(),
    )
    workspace = _workspace(original, unrelated)
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.TITLE, SmartOperator.IS, "Song 2"),)
        )
    )
    revision = workspace.revision
    updated = workspace.edit_smart(10, smart)
    assert updated.track_ids == (2,) and updated.entries == original.entries[:1]
    assert workspace.revision == revision + 1
    assert workspace.playlist(11) is unrelated
    with pytest.raises(ValueError):
        workspace.update(
            10,
            name="Do not partially rename",
            smart=SmartPlaylist(
                rules=SmartRuleGroup(
                    rules=(SmartRule(SmartField.YEAR, SmartOperator.IS, "invalid"),)
                )
            ),
        )
    assert workspace.playlist(10) == updated
