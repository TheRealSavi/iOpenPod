"""Native Genius Playlists remain outside ordinary Playlist editing."""

from collections.abc import Callable

import pytest

from iOpenPod.app.library_workspace import LibraryWorkspace, TrackUpdate
from iOpenPod.app.models.playlist_tree_model import PlaylistTreeModel
from iOpenPod.app.smart_playlist_preview import refresh_smart_playlists
from iPodDB.library import (
    LibrarySnapshot,
    Playlist,
    PlaylistKind,
    PlaylistSortOrder,
    SmartPlaylist,
    Track,
    TrackFieldEdit,
    playlist_entries,
)
from iPodDB.library.genius import GeniusCollection, GeniusCollectionKind


def _workspace() -> LibraryWorkspace:
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            tracks=(Track(1, "Zulu", "", "", 1000), Track(2, "Alpha", "", "", 1000)),
            playlists=(
                Playlist(
                    10,
                    "Genius",
                    PlaylistKind.GENIUS,
                    entries=playlist_entries((1, 2, 1)),
                    smart=SmartPlaylist(),
                    sort_order=PlaylistSortOrder.TITLE,
                ),
                Playlist(11, "Regular"),
            ),
        )
    )
    return workspace


def test_genius_browsing_keeps_occurrences_but_ordinary_tree_excludes_it() -> None:
    workspace = _workspace()
    assert tuple(t.track_id for t in workspace.tracks_for(10)) == (1, 2, 1)
    model = PlaylistTreeModel(workspace)
    assert model.rowCount() == 1
    assert model.index(0, 0).data() == "Regular"
    assert not model.index_for_id(10).isValid()
    assert not workspace.dirty


_GENIUS_MUTATIONS: tuple[Callable[[LibraryWorkspace], object], ...] = (
    lambda w: w.rename(10, "Changed"),
    lambda w: w.remove_playlist(10, w.edit_revision),
    lambda w: w.move(10, None),
    lambda w: w.set_tracks(10, (2,)),
    lambda w: w.evaluate_smart(10),
    lambda w: w.create(PlaylistKind.GENIUS, "New"),
)


@pytest.mark.parametrize("action", _GENIUS_MUTATIONS)
def test_ordinary_actions_cannot_change_native_genius(
    action: Callable[[LibraryWorkspace], object],
) -> None:
    workspace = _workspace()
    with pytest.raises(ValueError):
        action(workspace)
    assert not workspace.dirty
    assert workspace.playlist(10) is not None


def test_refresh_and_unrelated_track_edit_do_not_reorder_genius() -> None:
    workspace = _workspace()
    source = workspace.snapshot
    assert source is not None
    assert refresh_smart_playlists(source).playlists == source.playlists
    workspace.apply_track_edits(
        (TrackUpdate(1, (TrackFieldEdit("title", "Changed"),)),),
        workspace.edit_revision,
    )
    assert workspace.playlist(10) == source.playlists[0]


def test_explicit_genius_removal_stages_canonical_omission_and_can_be_discarded() -> (
    None
):
    workspace = _workspace()
    collection = GeniusCollection(
        "genius-playlist:000000000000000a",
        "Genius",
        GeniusCollectionKind.PLAYLIST,
        (1, 2, 1),
        1,
        10,
    )
    workspace.remove_genius_collection(collection, workspace.edit_revision)
    assert workspace.playlist(10) is None
    assert workspace.genius_collection_removals == (collection.collection_id,)
    assert workspace.delete_omissions
    assert workspace.dirty
    workspace.reset_changes()
    assert workspace.playlist(10) is not None
    assert not workspace.genius_collection_removals
    assert not workspace.dirty
