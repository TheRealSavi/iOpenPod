"""Direct contract tests for runtime playback list models."""

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QSignalSpy
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.library_drag import (
    TRACK_MIME_TYPE,
    PlaylistSelectionMimeData,
    TrackSelectionMimeData,
)
from iOpenPod.app.models.playback_models import (
    QUEUE_ENTRY_MIME_TYPE,
    PlaybackEntry,
    PlaybackHistoryModel,
    PlaybackQueueModel,
    PlaybackRole,
)
from iOpenPod.app.models.playlist_tree_model import PlaylistTreeModel
from iOpenPod.app.playback_controller import PlaybackController
from iPodDB.library import LibrarySnapshot, Playlist, Track, playlist_entries


def test_retranslate_invalidates_all_translated_rows() -> None:
    model = PlaybackQueueModel()
    model.append_entry(PlaybackEntry(1, _track()))
    changed = QSignalSpy(model.dataChanged)

    model.retranslate("fr-FR")

    assert changed.count() == 1
    top_left, bottom_right, roles = changed.at(0)
    assert top_left.row() == 0
    assert bottom_right.row() == 0
    assert Qt.ItemDataRole.AccessibleTextRole in roles
    assert Qt.ItemDataRole.AccessibleDescriptionRole in roles


def test_history_cursor_invalidates_its_accessible_description() -> None:
    model = PlaybackHistoryModel()
    first = PlaybackEntry(1, _track())
    second = PlaybackEntry(2, _track(track_id=2))
    model.record(first)
    model.record(second)
    changed = QSignalSpy(model.dataChanged)

    model.set_current_entry(first.entry_id)

    changed_roles = [roles for _, _, roles in map(changed.at, range(changed.count()))]
    assert all(
        Qt.ItemDataRole.AccessibleDescriptionRole in roles for roles in changed_roles
    )
    assert (
        model.data(
            model.index(1, 0),
            Qt.ItemDataRole.AccessibleDescriptionRole,
        )
        == "Current Playback History entry"
    )


def test_playback_rows_expose_artist_and_album_as_distinct_lines() -> None:
    model = PlaybackQueueModel()
    model.append_entry(PlaybackEntry(1, _track()))
    index = model.index(0, 0)

    assert index.data(Qt.ItemDataRole.DisplayRole) == "Title"
    assert index.data(PlaybackRole.ARTIST) == "Artist"
    assert index.data(PlaybackRole.ALBUM) == "Album"


def test_queue_rejects_malformed_internal_drag_data() -> None:
    model = PlaybackQueueModel()
    data = model.mimeData([QModelIndex()])
    data.setData(model.mimeTypes()[0], b"\xff")

    accepted = model.dropMimeData(
        data,
        Qt.DropAction.MoveAction,
        0,
        0,
        QModelIndex(),
    )

    assert not accepted


def test_table_track_drag_inserts_at_the_dropped_queue_position() -> None:
    tracks = tuple(_track(track_id=track_id) for track_id in range(1, 5))
    workspace = _workspace(tracks)
    controller = PlaybackController(FakePlaybackBackend(), workspace=workspace)
    controller.enqueue(tracks[0])
    controller.enqueue(tracks[1])
    controller.enqueue(tracks[2])

    accepted = controller.queue_model.dropMimeData(
        TrackSelectionMimeData(workspace, (tracks[3].track_id,)),
        Qt.DropAction.CopyAction,
        1,
        0,
        QModelIndex(),
    )

    assert accepted
    assert tuple(entry.track for entry in controller.queue_model.entries) == (
        tracks[1],
        tracks[3],
        tracks[2],
    )


def test_queue_drag_is_the_same_track_payload_accepted_by_a_playlist() -> None:
    tracks = (_track(track_id=1), _track(track_id=2))
    playlist = Playlist(10, "Regular")
    workspace = _workspace(tracks, playlists=(playlist,))
    controller = PlaybackController(FakePlaybackBackend(), workspace=workspace)
    controller.enqueue(tracks[0])
    controller.enqueue(tracks[1])
    data = controller.queue_model.mimeData([controller.queue_model.index(0, 0)])
    playlist_model = PlaylistTreeModel(workspace)

    assert isinstance(data, TrackSelectionMimeData)
    assert playlist_model.dropMimeData(
        data,
        Qt.DropAction.CopyAction,
        -1,
        0,
        playlist_model.index_for_id(playlist.playlist_id),
    )
    updated = workspace.playlist(playlist.playlist_id)
    assert updated is not None and updated.track_ids == (tracks[1].track_id,)


def test_playlist_drag_inserts_all_occurrences_at_the_queue_position() -> None:
    tracks = tuple(_track(track_id=track_id) for track_id in range(1, 5))
    playlist = Playlist(
        10,
        "Repeated",
        entries=playlist_entries((2, 3, 2)),
    )
    workspace = _workspace(tracks, playlists=(playlist,))
    controller = PlaybackController(FakePlaybackBackend(), workspace=workspace)
    controller.enqueue(tracks[0])
    controller.enqueue(tracks[3])

    accepted = controller.queue_model.dropMimeData(
        PlaylistSelectionMimeData(workspace, playlist.playlist_id),
        Qt.DropAction.CopyAction,
        0,
        0,
        QModelIndex(),
    )

    assert accepted
    assert tuple(entry.track for entry in controller.queue_model.entries) == (
        tracks[1],
        tracks[2],
        tracks[1],
        tracks[3],
    )


def test_history_drag_copies_the_track_into_a_playlist_without_removing_history() -> (
    None
):
    tracks = (_track(track_id=1), _track(track_id=2))
    playlist = Playlist(10, "Regular")
    workspace = _workspace(tracks, playlists=(playlist,))
    controller = PlaybackController(FakePlaybackBackend(), workspace=workspace)
    controller.play_now((tracks[0],))
    controller.play_now((tracks[1],))
    history = controller.history_model
    entries = history.entries
    index = history.index(1, 0)
    data = history.mimeData([index])
    playlists = PlaylistTreeModel(workspace)

    assert history.flags(index) & Qt.ItemFlag.ItemIsDragEnabled
    assert history.supportedDragActions() == Qt.DropAction.CopyAction
    assert isinstance(data, TrackSelectionMimeData)
    assert data.track_ids == (tracks[0].track_id,)
    assert not data.hasFormat(QUEUE_ENTRY_MIME_TYPE)
    assert playlists.dropMimeData(
        data,
        Qt.DropAction.CopyAction,
        -1,
        0,
        playlists.index_for_id(playlist.playlist_id),
    )
    updated = workspace.playlist(playlist.playlist_id)
    assert updated is not None and updated.track_ids == (tracks[0].track_id,)
    assert history.entries == entries
    assert controller.current_track == tracks[1]


def test_history_drag_adds_a_new_queue_occurrence_at_the_drop_position() -> None:
    tracks = tuple(_track(track_id=track_id) for track_id in range(1, 4))
    workspace = _workspace(tracks)
    controller = PlaybackController(FakePlaybackBackend(), workspace=workspace)
    controller.play_now((tracks[0],))
    controller.play_now((tracks[1], tracks[2]))
    history = controller.history_model
    entries = history.entries
    data = history.mimeData([history.index(1, 0)])

    assert controller.queue_model.dropMimeData(
        data, Qt.DropAction.CopyAction, 0, 0, QModelIndex()
    )
    assert tuple(entry.track for entry in controller.queue_model.entries) == (
        tracks[0],
        tracks[2],
    )
    assert controller.queue_model.entries[0].entry_id != entries[1].entry_id
    assert history.entries == entries
    assert controller.current_track == tracks[1]
    assert not history.dropMimeData(data, Qt.DropAction.CopyAction, 0, 0, QModelIndex())


def test_history_drag_is_rejected_after_the_library_changes() -> None:
    track = _track()
    workspace = _workspace((track,))
    controller = PlaybackController(FakePlaybackBackend(), workspace=workspace)
    controller.enqueue(track)
    history = controller.history_model
    data = history.mimeData([history.index(0, 0)])
    assert isinstance(data, TrackSelectionMimeData)
    workspace.load(LibrarySnapshot(tracks=(track,)))

    assert not controller.queue_model.dropMimeData(
        data, Qt.DropAction.CopyAction, 0, 0, QModelIndex()
    )
    assert controller.queue_model.rowCount() == 0


def test_history_without_a_library_or_valid_selection_does_not_export_tracks() -> None:
    model = PlaybackHistoryModel()
    model.record(PlaybackEntry(1, _track()))

    for indexes in ([], [QModelIndex()], [model.index(0, 0)]):
        data = model.mimeData(indexes)
        assert not data.hasFormat(TRACK_MIME_TYPE)


def test_history_does_not_export_invalid_or_foreign_rows() -> None:
    track = _track()
    workspace = _workspace((track,))
    controller = PlaybackController(FakePlaybackBackend(), workspace=workspace)
    controller.play_now((track, track))
    history = controller.history_model

    for indexes in ([], [QModelIndex()], [controller.queue_model.index(0, 0)]):
        assert not history.mimeData(indexes).hasFormat(TRACK_MIME_TYPE)

    workspace.load(LibrarySnapshot())
    assert not history.mimeData([history.index(0, 0)]).hasFormat(TRACK_MIME_TYPE)


def _workspace(
    tracks: tuple[Track, ...],
    *,
    playlists: tuple[Playlist, ...] = (),
) -> LibraryWorkspace:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(tracks=tracks, playlists=playlists))
    return workspace


def _track(*, track_id: int = 1) -> Track:
    return Track(track_id, "Title", "Artist", "Album", 180_000)
