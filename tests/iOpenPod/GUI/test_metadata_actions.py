"""The same metadata actions apply to explicit table and grid selections."""

import subprocess
import sys
from dataclasses import replace
from time import monotonic, sleep

import pytest
from PySide6.QtCore import QItemSelectionModel, QPoint, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QToolButton,
    QWidget,
    QWidgetAction,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iOpenPod.lyrics_test_support import (
    WORDS,
    MemorySource,
    SourceProvider,
    media,
)

from iOpenPod.app.models.track_table_model import TrackColumn
from iOpenPod.app.tag_normalization_controller import TagNormalizationController
from iOpenPod.app.tag_normalizer import TagProfile
from iOpenPod.GUI.dialogs.artwork_editor import ArtworkEditor
from iOpenPod.GUI.dialogs.metadata_editor import MetadataEditorDialog
from iOpenPod.GUI.dialogs.playlist_editor import PlaylistEditorDialog
from iOpenPod.GUI.dialogs.tag_normalizer import TagNormalizerDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.pages.playlist_page import PlaylistPage
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.collection_grid import CollectionGridView
from iOpenPod.GUI.widgets.sidebar import DeviceCard
from iOpenPod.GUI.widgets.track_actions import TrackActions, TrackSelection
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import (
    ArtworkPixels,
    ContentAdvisory,
    LibrarySnapshot,
    MediaType,
    Playlist,
    Track,
    TrackMetadata,
    playlist_entries,
)

_TRACKS = (
    Track(
        1, "One", "Artist A", "First", 120_000, metadata=TrackMetadata(compilation=True)
    ),
    Track(2, "Two", "Artist A", "First", 130_000),
    Track(3, "Three", "Artist B", "Second", 150_000),
)


def test_editor_lazily_displays_file_lyrics_without_editing_the_library() -> None:
    context = build_context()
    track = replace(
        _TRACKS[0], metadata=TrackMetadata(lyrics="Database words", has_lyrics=True)
    )
    workspace = context.library_workspace
    workspace.load(LibrarySnapshot((track,)))
    provider = SourceProvider({track.track_id: MemorySource(media())})
    dialog = MetadataEditorDialog(
        workspace, (track.track_id,), lyrics_provider=provider
    )
    try:
        assert provider.opened == []
        dialog.show()
        assert QThreadPool.globalInstance().waitForDone(5000)
        APPLICATION.processEvents()
        row = dialog.rows["metadata.lyrics"]
        assert isinstance(row.editor, QPlainTextEdit)
        assert row.editor.toPlainText() == WORDS
        assert not row.is_modified()
        assert not workspace.dirty

        row.editor.setPlainText("Edited words")
        dialog.accept()
        edited = workspace.track(track.track_id)
        assert edited is not None and edited.metadata.lyrics == "Edited words"
    finally:
        dialog.close()
        context.shutdown()


def test_track_actions_import_is_safe_before_qapplication() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-X",
            "faulthandler",
            "-c",
            "import iOpenPod.GUI.widgets.track_actions",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr


def test_context_menu_omits_clear_artwork_and_remove_is_a_reversible_draft_edit() -> (
    None
):
    context = build_context()
    tracks = tuple(replace(t, artwork_id=7) for t in _TRACKS)
    source = LibrarySnapshot(
        tracks, (Playlist(10, "Repeated", entries=playlist_entries((1, 2, 1, 3))),)
    )
    workspace = context.library_workspace
    workspace.load(source)
    context.track_model.replace_tracks(tracks)
    window = MainWindow(context, auto_discover=False)
    try:
        actions = window.findChild(TrackActions)
        assert actions is not None
        selection = TrackSelection(tracks[:2], workspace.edit_revision)
        exported: list[tuple[Track, ...]] = []
        actions.trackExportRequested.disconnect()
        actions.trackExportRequested.connect(exported.append)
        menu = actions.build_menu(selection)
        assert "Clear Artwork" not in tuple(action.text() for action in menu.actions())
        next(a for a in menu.actions() if a.text() == "Export…").trigger()
        assert exported == [tracks[:2]]
        menu = actions.build_menu(selection)
        next(
            a for a in menu.actions() if a.text() == "Remove 2 Tracks from iPod"
        ).trigger()
        assert workspace.tracks == tracks[2:] and workspace.delete_omissions
        assert workspace.playlists[0].track_ids == (3,)
        assert context.track_model.tracks == tracks[2:]
        assert workspace.snapshot is source
        workspace.reset_changes()
        assert workspace.tracks == tracks and not workspace.delete_omissions
    finally:
        window.close()
        context.shutdown()


def test_context_menu_converts_tracks_to_podcasts_and_requires_album_for_chapters() -> (
    None
):
    context = build_context()
    track = Track(1, "Episode", "Host", "", 120_000)
    context.library_workspace.load(LibrarySnapshot((track,)))
    context.track_model.replace_tracks((track,))
    window = MainWindow(context, auto_discover=False)
    try:
        actions = window.findChild(TrackActions)
        assert actions is not None
        selection = TrackSelection((track,), context.library_workspace.edit_revision)
        menu = actions.build_menu(selection)
        convert = next(a for a in menu.actions() if a.text() == "Convert to Podcast")
        chaptered = next(
            a
            for a in menu.actions()
            if a.text() == "Convert to a single chaptered track"
        )
        assert convert.isEnabled()
        assert not chaptered.isEnabled()

        convert.trigger()

        converted = context.library_workspace.tracks[0]
        assert converted.media_types == (MediaType.PODCAST,)
        assert converted.album == converted.show == "Host"
        assert converted.genre == converted.metadata.category == "Podcast"
        assert converted.metadata.podcast
        assert converted.metadata.skip_shuffle
        assert converted.metadata.remember_position
        assert context.track_model.tracks == (converted,)
        refreshed = TrackSelection(
            (converted,), context.library_workspace.edit_revision
        )
        convert = next(
            a
            for a in actions.build_menu(refreshed).actions()
            if a.text() == "Convert to Podcast"
        )
        assert not convert.isEnabled()
    finally:
        window.close()
        context.shutdown()


def test_chaptered_action_requests_the_complete_album() -> None:
    context = build_context()
    tracks = tuple(
        replace(
            track,
            metadata=replace(
                track.metadata, location=f"iPod_Control/Music/F00/{track.track_id}.m4a"
            ),
        )
        for track in _TRACKS
    )
    workspace = context.library_workspace
    workspace.load(LibrarySnapshot(tracks))
    parent = QWidget()
    actions = TrackActions(workspace, context.playback_controller, parent)
    requested: list[tuple[Track, ...]] = []
    actions.chapteredConversionRequested.connect(requested.append)
    try:
        selection = TrackSelection(tracks[:2], workspace.edit_revision)
        menu = actions.build_menu(selection)
        action = next(
            item
            for item in menu.actions()
            if item.text() == "Convert to a single chaptered track"
        )
        assert action.isEnabled()
        action.trigger()
        assert requested == [tracks[:2]]
        assert workspace.tracks == tracks
    finally:
        parent.close()
        context.shutdown()


@pytest.mark.parametrize("media_type", (MediaType.PODCAST, MediaType.VIDEO))
@pytest.mark.parametrize("saved_value", (False, True))
def test_track_playback_flags_show_saved_values_in_editor_and_context_menu(
    media_type: MediaType,
    saved_value: bool,
) -> None:
    context = build_context()
    track = Track(
        1,
        "Episode",
        "Host",
        "Show",
        120_000,
        media_types=(media_type,),
        metadata=TrackMetadata(skip_shuffle=saved_value, remember_position=saved_value),
    )
    workspace = context.library_workspace
    workspace.load(LibrarySnapshot((track,)))
    parent = QWidget()
    actions = TrackActions(workspace, context.playback_controller, parent)
    dialog = MetadataEditorDialog(workspace, (track.track_id,))
    try:
        menu = actions.build_menu(TrackSelection((track,), workspace.edit_revision))
        for field, label in (
            ("metadata.skip_shuffle", "Skip When Shuffling"),
            ("metadata.remember_position", "Remember Playback Position"),
        ):
            editor = dialog.rows[field].editor
            assert isinstance(editor, AppComboBox)
            assert editor.currentData() is saved_value
            action = next(action for action in menu.actions() if action.text() == label)
            assert action.isCheckable()
            assert action.isChecked() is saved_value
            assert action.isEnabled() is not saved_value
            assert editor.isEnabled() is not saved_value
            choices = editor.model()
            assert isinstance(choices, QStandardItemModel)
            no = choices.item(editor.findData(False))
            assert not no.isEnabled()
        if not saved_value:
            assert not workspace.dirty
            for path in ("metadata.skip_shuffle", "metadata.remember_position"):
                editor = dialog.rows[path].editor
                assert isinstance(editor, AppComboBox)
                editor.setCurrentIndex(editor.findData(True))
                assert not editor.isEnabled()
            dialog.accept()
            assert workspace.tracks[0].metadata.skip_shuffle
            assert workspace.tracks[0].metadata.remember_position
    finally:
        dialog.close()
        parent.close()
        context.shutdown()


def test_editor_stages_required_flags_and_updates_guard_after_each_media_change() -> (
    None
):
    context = build_context()
    workspace = context.library_workspace
    workspace.load(
        LibrarySnapshot(
            (Track(1, "Audio", "", "", 1000, media_types=(MediaType.AUDIO,)),)
        )
    )
    dialog = MetadataEditorDialog(workspace, (1,))
    try:
        media = dialog.rows["media_types"].editor
        assert isinstance(media, AppComboBox)
        flags = tuple(
            dialog.rows[path].editor
            for path in ("metadata.skip_shuffle", "metadata.remember_position")
        )
        for editor in flags:
            assert isinstance(editor, AppComboBox)
            assert editor.currentData() is False and editor.isEnabled()
        media.setCurrentIndex(media.findData(MediaType.PODCAST))
        for editor in flags:
            assert isinstance(editor, AppComboBox)
            assert editor.currentData() is True and not editor.isEnabled()
        media.setCurrentIndex(media.findData(MediaType.AUDIO))
        for editor in flags:
            assert isinstance(editor, AppComboBox)
            assert editor.isEnabled()
            editor.setCurrentIndex(editor.findData(False))
        media.setCurrentIndex(media.findData(MediaType.PODCAST))
        for editor in flags:
            assert isinstance(editor, AppComboBox)
            assert editor.currentData() is True and not editor.isEnabled()
        dialog.accept()
        assert workspace.tracks[0].metadata.skip_shuffle
        assert workspace.tracks[0].metadata.remember_position
    finally:
        dialog.close()
        context.shutdown()


def test_mixed_music_and_podcast_flags_still_allow_music_edits() -> None:
    context = build_context()
    tracks = tuple(
        Track(
            identity,
            media_type.value,
            "",
            "",
            1000,
            media_types=(media_type,),
            metadata=TrackMetadata(skip_shuffle=True, remember_position=True),
        )
        for identity, media_type in ((1, MediaType.PODCAST), (2, MediaType.AUDIO))
    )
    workspace = context.library_workspace
    workspace.load(LibrarySnapshot(tracks))
    parent = QWidget()
    actions = TrackActions(workspace, context.playback_controller, parent)
    dialog = MetadataEditorDialog(workspace, (1, 2))
    try:
        menu = actions.build_menu(TrackSelection(tracks, workspace.edit_revision))
        shuffle = next(a for a in menu.actions() if a.text() == "Skip When Shuffling")
        assert shuffle.isEnabled() and shuffle.isChecked()
        for path in ("metadata.skip_shuffle", "metadata.remember_position"):
            editor = dialog.rows[path].editor
            assert isinstance(editor, AppComboBox)
            assert editor.isEnabled()
            choices = editor.model()
            assert isinstance(choices, QStandardItemModel)
            no = choices.item(editor.findData(False))
            assert no.isEnabled()
            editor.setCurrentIndex(editor.findData(False))
        dialog.accept()
        assert workspace.tracks[0].metadata.skip_shuffle
        assert workspace.tracks[0].metadata.remember_position
        assert not workspace.tracks[1].metadata.skip_shuffle
        assert not workspace.tracks[1].metadata.remember_position
    finally:
        dialog.close()
        parent.close()
        context.shutdown()


def test_external_device_tracks_use_the_current_shared_track_menu() -> None:
    context = build_context()
    stale_track = Track(1, "Before", "Host", "Show", 120_000)
    context.library_workspace.load(LibrarySnapshot((stale_track,)))
    window = MainWindow(context, auto_discover=False)
    try:
        actions = window.findChild(TrackActions)
        assert actions is not None
        actions.apply(
            TrackSelection(
                (stale_track,),
                context.library_workspace.edit_revision,
            ),
            "title",
            "After",
        )

        menu = actions.build_menu_for_tracks(
            (stale_track, stale_track, Track(999, "Missing", "", "", 1))
        )

        assert menu is not None
        remove = next(
            action for action in menu.actions() if action.text().startswith("Remove ")
        )
        assert remove.text() == "Remove 1 Track from iPod"
        next(
            action for action in menu.actions() if action.text() == "Copy as Text"
        ).trigger()
        assert APPLICATION.clipboard().text() == "After\tHost\tShow"
    finally:
        window.close()
        context.shutdown()


def test_context_menu_volume_adjustment_uses_original_slider_behavior() -> None:
    context = build_context()
    value = 64 / 255 * 100
    tracks = tuple(
        replace(
            track, metadata=replace(track.metadata, volume_adjustment_percent=value)
        )
        for track in _TRACKS[:2]
    )
    context.library_workspace.load(LibrarySnapshot(tracks))
    window = MainWindow(context, auto_discover=False)
    try:
        actions = window.findChild(TrackActions)
        assert actions is not None
        selection = TrackSelection(tracks, context.library_workspace.edit_revision)
        menu = actions.build_menu(selection)
        volume_menu_action = next(
            action for action in menu.actions() if action.text() == "Volume Adjustment"
        )
        volume_menu = volume_menu_action.menu()
        assert isinstance(volume_menu, QMenu)
        slider_action = volume_menu.actions()[0]
        assert isinstance(slider_action, QWidgetAction)
        widget = slider_action.defaultWidget()
        slider = widget.findChild(QSlider, "volumeAdjustmentSlider")
        label = widget.findChild(QLabel, "volumeAdjustmentValueLabel")
        assert slider is not None and label is not None
        assert (slider.minimum(), slider.maximum(), slider.value()) == (-255, 255, 64)
        assert label.text() == "+25%"

        slider.setValue(8)
        assert slider.value() == 0
        assert label.text() == "No adjustment (0%)"
        assert all(
            track.metadata.volume_adjustment_percent == 0
            for track in context.library_workspace.tracks
        )
        slider.setValue(13)
        assert label.text() == "+5%"
        assert all(
            track.metadata.volume_adjustment_percent == 13 / 255 * 100
            for track in context.library_workspace.tracks
        )
    finally:
        window.close()
        context.shutdown()


def test_context_menu_shortcuts_are_visible_and_use_native_platform_text() -> None:
    context = build_context()
    context.library_workspace.load(LibrarySnapshot(_TRACKS))
    window = MainWindow(context, auto_discover=False)
    try:
        actions = window.findChild(TrackActions)
        assert actions is not None
        selection = TrackSelection(
            _TRACKS[:2],
            context.library_workspace.edit_revision,
            playlist_id=10,
            entry_ids=("one", "two"),
            reorderable=True,
        )
        menu = actions.build_menu(selection)

        expected = {
            "Edit Metadata…": "Ctrl+E",
            "Play Next": "Ctrl+Shift+Q",
            "Add to Queue": "Ctrl+Q",
            "Move Up": "Ctrl+Up",
            "Move Down": "Ctrl+Down",
            "Copy as Text": "Ctrl+C",
        }
        for text, portable in expected.items():
            action = next(a for a in menu.actions() if a.text() == text)
            assert isinstance(action, QAction)
            assert action.isShortcutVisibleInContextMenu()
            assert (
                action.shortcut().toString(QKeySequence.SequenceFormat.PortableText)
                == portable
            )
            native = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            if sys.platform == "darwin":
                assert "⌘" in native
                assert "Ctrl" not in native
            else:
                assert "Ctrl" in native

        installed = {
            shortcut.property("trackAction")
            for shortcut in window.findChildren(QShortcut)
        }
        assert {
            "edit",
            "copy",
            "enqueue",
            "play_next",
            "move_up",
            "move_down",
        } <= installed
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize("page_id", ("tracks", "albums"))
@pytest.mark.parametrize("prepend", (False, True))
def test_queue_shortcuts_use_focused_selection_and_preserve_track_order(
    page_id: str, prepend: bool
) -> None:
    context = build_context()
    context.library_workspace.load(LibrarySnapshot(_TRACKS))
    context.track_model.replace_tracks(_TRACKS)
    window = MainWindow(context, auto_discover=False)
    playback = context.playback_controller
    try:
        window.show()
        navigation = next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == page_id
        )
        navigation.click()
        APPLICATION.processEvents()
        view = (
            window.findChild(TrackTable, "tracksTrackTable")
            if page_id == "tracks"
            else window.findChild(AlbumGridView, "albumGrid")
        )
        assert view is not None
        view.clearSelection()
        # Table selection order must follow visible rows, regardless of click order.
        for row in (1, 0) if page_id == "tracks" else (0,):
            view.selectionModel().select(
                view.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        playback.enqueue(_TRACKS[2])
        playback.enqueue(_TRACKS[2])
        current_entry_id = playback.current_entry_id
        modifiers = Qt.KeyboardModifier.ControlModifier
        if prepend:
            modifiers |= Qt.KeyboardModifier.ShiftModifier
        view.setFocus()
        APPLICATION.processEvents()

        QTest.keyClick(view, Qt.Key.Key_Q, modifiers)

        expected = (
            (_TRACKS[0], _TRACKS[1], _TRACKS[2])
            if prepend
            else (_TRACKS[2], _TRACKS[0], _TRACKS[1])
        )
        assert tuple(entry.track for entry in playback.queue_model.entries) == expected
        assert playback.current_entry_id == current_entry_id

        navigation.setFocus()
        APPLICATION.processEvents()
        QTest.keyClick(navigation, Qt.Key.Key_Q, modifiers)
        assert tuple(entry.track for entry in playback.queue_model.entries) == expected

        view.clearSelection()
        view.setFocus()
        APPLICATION.processEvents()
        QTest.keyClick(view, Qt.Key.Key_Q, modifiers)
        assert tuple(entry.track for entry in playback.queue_model.entries) == expected
        assert playback.current_entry_id == current_entry_id
    finally:
        window.close()
        context.shutdown()


def test_action_connections_do_not_retain_closed_windows() -> None:
    # Exercise collection in a fresh Qt process, independent of other tests'
    # deferred QObject destruction and global application signal connections.
    probe = """
import gc
import weakref
from tests.iOpenPod.GUI.application_shell_test_support import build_context
from iOpenPod.GUI.main_window import MainWindow
context = build_context()
window = MainWindow(context, auto_discover=False)
reference = weakref.ref(window)
window.close()
context.shutdown()
del window, context
gc.collect()
assert reference() is None
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, completed.stderr


def test_mixed_editor_only_applies_explicit_fields_and_updates_shared_models() -> None:
    context = build_context()
    source = LibrarySnapshot(_TRACKS)
    context.library_workspace.load(source)
    context.track_model.replace_tracks(_TRACKS)
    dialog = MetadataEditorDialog(context.library_workspace, (1, 2))
    try:
        dialog.show()
        APPLICATION.processEvents()
        title = dialog.rows["title"]
        assert title.mixed and not title.is_modified()
        assert isinstance(title.editor, QLineEdit)
        assert title.editor.text() == ""
        artist = dialog.rows["artist"]
        assert isinstance(artist.editor, QLineEdit)
        artist.editor.selectAll()
        QTest.keyClicks(artist.editor, "Edited artist")
        assert artist.is_modified()
        summary = dialog.findChild(QLabel, "metadataChangeSummary")
        assert summary is not None and summary.text() == "1 changed field"
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert tuple(t.title for t in context.track_model.tracks) == (
            "One",
            "Two",
            "Three",
        )
        assert tuple(t.artist for t in context.track_model.tracks) == (
            "Edited artist",
            "Edited artist",
            "Artist B",
        )
        assert source == LibrarySnapshot(_TRACKS)
        context.library_workspace.reset_changes()
        assert context.track_model.tracks == _TRACKS
    finally:
        dialog.close()
        context.shutdown()


def test_metadata_editor_applies_metadata_and_one_shared_artwork_crop() -> None:
    context = build_context()
    workspace = context.library_workspace
    workspace.load(LibrarySnapshot(_TRACKS))
    dialog = MetadataEditorDialog(workspace, (1, 2))
    try:
        artwork = dialog.findChild(ArtworkEditor)
        summary = dialog.findChild(QLabel, "metadataChangeSummary")
        assert artwork is not None and summary is not None
        artwork.set_pending_artwork(ArtworkPixels(1, 1, b"\x12\x34\x56"), "cover.png")
        album = dialog.rows["album"].editor
        assert isinstance(album, QLineEdit)
        album.setText("New album")
        assert summary.text() == "1 changed field + artwork"
        revision = workspace.edit_revision

        dialog.accept()

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert workspace.edit_revision.revision == revision.revision + 1
        assert tuple(track.album for track in workspace.tracks[:2]) == (
            "New album",
            "New album",
        )
        assert len(workspace.artwork_assets) == 1
        artwork_id = workspace.artwork_assets[0].artwork_id
        assert tuple(track.artwork_id for track in workspace.tracks) == (
            artwork_id,
            artwork_id,
            0,
        )
    finally:
        dialog.close()
        context.shutdown()


def test_metadata_editor_consolidates_to_an_existing_selected_artwork() -> None:
    context = build_context()
    workspace = context.library_workspace
    workspace.load(
        LibrarySnapshot(
            (
                replace(_TRACKS[0], artwork_id=101),
                replace(_TRACKS[1], artwork_id=202),
            )
        )
    )
    dialog = MetadataEditorDialog(workspace, (1, 2))
    try:
        artwork = dialog.findChild(ArtworkEditor)
        assert artwork is not None
        artwork.set_pending_artwork_id(202)

        dialog.accept()

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert tuple(track.artwork_id for track in workspace.tracks) == (202, 202)
        assert not workspace.artwork_assets
    finally:
        dialog.close()
        context.shutdown()


def test_editor_clear_reset_invalid_and_stale_apply_are_explicit() -> None:
    context = build_context()
    workspace = context.library_workspace
    workspace.load(LibrarySnapshot(_TRACKS))
    dialog = MetadataEditorDialog(workspace, (1, 2))
    try:
        title = dialog.rows["title"]
        assert isinstance(title.editor, QLineEdit)
        title.editor.setText("temporary")
        title.editor.clear()
        assert title.is_modified()
        rating = dialog.rows["rating"]
        assert isinstance(rating.editor, QLineEdit)
        rating.editor.setText("101")
        assert rating.is_modified()
        dialog.accept()
        assert not workspace.dirty
        error = dialog.findChild(QLabel, "metadataEditError")
        assert error is not None and "Rating" in error.text()
        rating.reset()
        dialog.accept()
        assert workspace.tracks[0].title == workspace.tracks[1].title == ""
        assert workspace.tracks[2] == _TRACKS[2]
        stale = MetadataEditorDialog(workspace, (1,))
        workspace.reset_changes()
        stale.accept()
        assert stale.result() != QDialog.DialogCode.Accepted and not workspace.dirty
        stale.close()
    finally:
        dialog.close()
        context.shutdown()


def test_metadata_editor_uses_original_style_direct_editing_layout() -> None:
    context = build_context()
    context.library_workspace.load(LibrarySnapshot(_TRACKS))
    dialog = MetadataEditorDialog(context.library_workspace, (1, 2))
    try:
        assert dialog.windowTitle() == "Edit 2 Tracks"
        assert dialog.findChildren(QCheckBox) == []
        assert dialog.findChild(QFrame, "metadataEditorHeader") is not None
        assert dialog.findChild(QFrame, "metadataPageHeader") is not None
        assert dialog.findChild(QFrame, "metadataSectionPanel") is not None
        navigation = dialog.findChild(QListWidget, "metadataSectionNav")
        assert navigation is not None
        assert [
            navigation.item(index).text() for index in range(navigation.count())
        ] == [
            "Metadata",
            "Sorting",
            "Playback",
            "Options",
            "Video",
            "Podcast",
            "Dates",
            "Chapters",
            "Store",
            "Artwork",
            "Technical details",
        ]
        reset = dialog.findChild(QPushButton, "resetMetadataChanges")
        assert reset is not None and not reset.isEnabled()
        artist = dialog.rows["artist"]
        assert isinstance(artist.editor, QLineEdit)
        artist.editor.setText("Replacement")
        assert artist.is_modified() and artist.reset_button.isVisibleTo(dialog)
        assert reset.isEnabled()
        reset.click()
        assert not artist.is_modified() and not reset.isEnabled()
    finally:
        dialog.close()
        context.shutdown()


def test_metadata_editor_reclassifies_video_and_edits_show_in_one_revision() -> None:
    context = build_context()
    workspace = context.library_workspace
    tracks = (
        replace(_TRACKS[0], media_types=(MediaType.VIDEO,)),
        replace(_TRACKS[1], media_types=(MediaType.MUSIC_VIDEO,)),
        _TRACKS[2],
    )
    source = LibrarySnapshot(tracks)
    workspace.load(source)
    dialog = MetadataEditorDialog(workspace, (1, 2))
    try:
        row = dialog.rows["media_types"]
        editor = row.editor
        assert isinstance(editor, AppComboBox)
        assert editor.currentText() == "Mixed values"
        assert not row.is_modified()
        assert editor.findData(MediaType.AUDIO) == -1
        editor.setCurrentIndex(editor.findData(MediaType.TV_SHOW))
        assert row.is_modified()
        row.reset()
        assert editor.currentText() == "Mixed values" and not row.is_modified()
        editor.setCurrentIndex(editor.findData(MediaType.TV_SHOW))
        show = dialog.rows["show"].editor
        assert isinstance(show, QLineEdit)
        show.setText("Series")
        revision = workspace.revision

        dialog.accept()

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert workspace.revision == revision + 1
        assert all(
            track
            == replace(
                prior,
                media_types=(MediaType.TV_SHOW,),
                show="Series",
                metadata=replace(
                    prior.metadata, skip_shuffle=True, remember_position=True
                ),
            )
            for track, prior in zip(workspace.tracks[:2], tracks[:2], strict=True)
        )
        assert workspace.tracks[2] == tracks[2]
        assert workspace.snapshot is source
        assert context.track_model.tracks == workspace.tracks
    finally:
        dialog.close()
        context.shutdown()


@pytest.mark.parametrize(
    "types",
    [
        (MediaType.VIDEO,),
        (MediaType.VIDEO, MediaType.PODCAST),
        (MediaType.EPUB_BOOK,),
        (),
    ],
)
def test_media_type_selector_preserves_current_values_until_changed(
    types: tuple[MediaType, ...],
) -> None:
    context = build_context()
    workspace = context.library_workspace
    track = replace(_TRACKS[0], media_types=types)
    workspace.load(LibrarySnapshot((track,)))
    dialog = MetadataEditorDialog(workspace, (1,))
    try:
        row = dialog.rows["media_types"]
        editor = row.editor
        assert isinstance(editor, AppComboBox)
        assert editor.currentIndex() == 0
        assert not row.is_modified()
        if editor.isEnabled():
            editor.setCurrentIndex(editor.findData(MediaType.TV_SHOW))
            assert row.is_modified()
            row.reset()
            assert editor.currentIndex() == 0 and not row.is_modified()
        title = dialog.rows["title"].editor
        assert isinstance(title, QLineEdit)
        title.setText("New title")

        dialog.accept()

        expected_metadata = (
            replace(
                track.metadata,
                skip_shuffle=True,
                remember_position=True,
                podcast=MediaType.PODCAST in types,
            )
            if MediaType.VIDEO in types
            else track.metadata
        )
        assert workspace.tracks == (
            replace(track, title="New title", metadata=expected_metadata),
        )
    finally:
        dialog.close()
        context.shutdown()


def test_mixed_audio_and_video_keep_classification_while_editing_other_fields() -> None:
    context = build_context()
    workspace = context.library_workspace
    tracks = (_TRACKS[0], replace(_TRACKS[1], media_types=(MediaType.VIDEO,)))
    workspace.load(LibrarySnapshot(tracks))
    dialog = MetadataEditorDialog(workspace, (1, 2))
    try:
        row = dialog.rows["media_types"]
        editor = row.editor
        assert isinstance(editor, AppComboBox)
        assert not editor.isEnabled()
        assert editor.currentText() == "Mixed values" and not row.is_modified()
        title = dialog.rows["title"].editor
        assert isinstance(title, QLineEdit)
        title.setText("New title")

        dialog.accept()

        assert workspace.tracks == (
            replace(tracks[0], title="New title"),
            replace(
                tracks[1],
                title="New title",
                metadata=replace(
                    tracks[1].metadata, skip_shuffle=True, remember_position=True
                ),
            ),
        )
    finally:
        dialog.close()
        context.shutdown()


def test_artwork_editor_keeps_text_and_actions_outside_the_preview() -> None:
    context = build_context()
    tracks = tuple(
        replace(
            _TRACKS[index % len(_TRACKS)],
            track_id=index + 1,
            artwork_id=1 + index % 2,
        )
        for index in range(9)
    )
    context.library_workspace.load(LibrarySnapshot(tracks))
    dialog = MetadataEditorDialog(
        context.library_workspace,
        tuple(range(1, 10)),
    )
    try:
        navigation = dialog.findChild(QListWidget, "metadataSectionNav")
        assert navigation is not None
        navigation.setCurrentRow(
            next(
                index
                for index in range(navigation.count())
                if navigation.item(index).text() == "Artwork"
            )
        )
        dialog.show()
        APPLICATION.processEvents()

        preview = dialog.findChild(QLabel, "metadataArtworkImage")
        status = dialog.findChild(QLabel, "metadataArtworkStatus")
        note = dialog.findChild(QLabel, "metadataArtworkNote")
        choose = dialog.findChild(QPushButton, "chooseTrackArtwork")
        assert preview is not None and status is not None
        assert note is None and choose is not None

        def vertical_bounds(widget: QLabel | QPushButton) -> tuple[int, int]:
            top = widget.mapTo(dialog, QPoint()).y()
            return top, top + widget.height()

        preview_top, preview_bottom = vertical_bounds(preview)
        status_top, status_bottom = vertical_bounds(status)
        choose_top, _choose_bottom = vertical_bounds(choose)
        assert preview_top < preview_bottom
        assert status_top - preview_bottom >= LAYOUT.space_xs
        assert choose_top - status_bottom >= LAYOUT.space_sm
    finally:
        dialog.close()
        context.shutdown()


def test_inline_device_name_commits_on_return_and_cancels_on_escape() -> None:
    context = build_context()
    workspace = context.library_workspace
    workspace.load(LibrarySnapshot(_TRACKS, device_name="Original"))
    card = DeviceCard()
    card.set_workspace(workspace)
    try:
        card.show()
        rename = card.findChild(QPushButton, "deviceName")
        assert rename is not None and rename.isEnabled()
        rename.click()
        editor = card.findChild(QLineEdit, "renameIPod")
        apply = card.findChild(QToolButton, "renameIPodApply")
        cancel = card.findChild(QToolButton, "renameIPodCancel")
        assert editor is not None
        assert apply is not None and cancel is not None
        assert editor.isVisible() and editor.selectedText() == "Original"
        QTest.keyClicks(editor, "New name")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        assert workspace.device_name == "New name"
        card.start_rename()
        QTest.keyClicks(editor, "Discard")
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        assert workspace.device_name == "New name"
        card.start_rename()
        QTest.keyClicks(editor, "Applied name")
        apply.click()
        assert workspace.device_name == "Applied name"
        card.start_rename()
        QTest.keyClicks(editor, "Discard")
        cancel.click()
        assert workspace.device_name == "Applied name"
        card.start_rename()
        editor.clear()
        QTest.keyClick(editor, Qt.Key.Key_Return)
        feedback = card.findChild(QLabel, "renameIPodFeedback")
        assert feedback is not None and "Enter a name" in feedback.text()
        assert editor.isVisible() and editor.property("error") is True
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        card.start_rename()
        workspace.load(LibrarySnapshot(device_name="Another iPod"))
        QTest.keyClick(editor, Qt.Key.Key_Return)
        assert workspace.device_name == "Another iPod"
    finally:
        card.close()
        context.shutdown()


def test_table_and_grid_menus_resolve_full_selection_and_keep_playlist_occurrences() -> (
    None
):
    context = build_context()
    playlist = Playlist(10, "Duplicates", entries=playlist_entries((1, 2, 1)))
    context.library_workspace.load(LibrarySnapshot(_TRACKS, (playlist,)))
    context.track_model.replace_tracks(_TRACKS)
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        APPLICATION.processEvents()
        actions = window.findChild(TrackActions)
        table = window.findChild(TrackTable, "tracksTrackTable")
        grid = window.findChild(AlbumGridView, "albumGrid")
        assert actions is not None and table is not None and grid is not None
        for row in (0, 1):
            table.selectionModel().select(
                table.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        selection = actions.selection(table)
        assert selection.track_ids == (1, 2)
        grid.selectionModel().select(
            grid.model().index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect
        )
        album_selection = actions.selection(grid)
        assert album_selection.track_ids == (1, 2)
        assert [a.text() for a in actions.build_menu(selection).actions()] == [
            a.text() for a in actions.build_menu(album_selection).actions()
        ]
        menu = actions.build_menu(album_selection)
        ratings = next(a.menu() for a in menu.actions() if a.text() == "Rating")
        assert isinstance(ratings, QMenu)
        next(a for a in ratings.actions() if a.text() == "★★★★").trigger()
        assert tuple(t.rating for t in context.library_workspace.tracks) == (80, 80, 0)
        assert tuple(t.rating for t in context.track_model.tracks) == (80, 80, 0)
        # An artist card acts on all its Tracks, regardless of the table's filter.
        artist_grid = next(
            g
            for g in window.findChildren(CollectionGridView)
            if g.objectName() == "artistsCollectionGrid"
        )
        artist_grid.setCurrentIndex(artist_grid.model().index(0, 0))
        assert actions.selection(artist_grid).track_ids == (1, 2)
        actions.add_to_playlist(actions.selection(grid), 10)
        updated = context.library_workspace.playlist(10)
        assert updated is not None and updated.track_ids == (1, 2, 1, 1, 2)
        assert updated.entries[:3] == playlist.entries
    finally:
        window.close()
        context.shutdown()


def test_context_signal_shortcuts_and_new_playlist_use_current_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context()
    workspace = context.library_workspace
    workspace.load(LibrarySnapshot(_TRACKS))
    context.track_model.replace_tracks(_TRACKS)
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        APPLICATION.processEvents()
        actions = window.findChild(TrackActions)
        table = window.findChild(TrackTable, "tracksTrackTable")
        page = window.findChild(PlaylistPage)
        assert actions is not None and table is not None and page is not None
        table.selectRow(1)
        shortcuts = table.findChildren(QShortcut)
        next(
            s for s in shortcuts if s.property("trackAction") == "copy"
        ).activated.emit()
        assert APPLICATION.clipboard().text() == "Two\tArtist A\tFirst"
        next(
            s for s in shortcuts if s.property("trackAction") == "edit"
        ).activated.emit()
        dialog = window.findChild(MetadataEditorDialog)
        assert dialog is not None and dialog.isVisible()
        advisory = dialog.rows["metadata.content_advisory"].editor
        assert isinstance(advisory, AppComboBox)
        advisory.setCurrentIndex(advisory.findData(ContentAdvisory.EXPLICIT))
        dialog.accept()
        assert workspace.tracks[1].metadata.content_advisory is ContentAdvisory.EXPLICIT
        opened: list[bool] = []

        def close_menu() -> None:
            menu = window.findChild(QMenu, "trackContextMenu")
            opened.append(menu is not None and menu.isVisible())
            if menu is not None:
                menu.close()

        QTimer.singleShot(0, close_menu)
        table.customContextMenuRequested.emit(
            table.visualRect(table.model().index(0, 0)).center()
        )
        assert opened == [True]
        assert actions.selection(table).track_ids == (1,)

        def create_playlist(dialog: PlaylistEditorDialog) -> int:
            dialog.name.setText("Selected tracks")
            dialog.description.setText("Created from the Track menu")
            dialog.accept()
            return dialog.result()

        monkeypatch.setattr(PlaylistEditorDialog, "exec", create_playlist)
        revision = workspace.revision
        actions.new_playlist(actions.selection(table))
        assert workspace.revision == revision + 1
        assert workspace.playlists[0].track_ids == (1,)
        assert workspace.playlists[0].description == "Created from the Track menu"
        assert page.selected_playlist_id == workspace.playlists[0].playlist_id
    finally:
        window.close()
        context.shutdown()


def test_sorted_duplicate_occurrences_with_dangling_tracks_remove_the_exact_row() -> (
    None
):
    context = build_context()
    workspace = context.library_workspace
    playlist = Playlist(10, "Occurrences", entries=playlist_entries((999, 1, 2, 1)))
    workspace.load(LibrarySnapshot(_TRACKS, (playlist,)))
    context.track_model.replace_tracks(_TRACKS)
    window = MainWindow(context, auto_discover=False)
    try:
        page = window.findChild(PlaylistPage)
        actions = window.findChild(TrackActions)
        assert page is not None and actions is not None
        page.select_playlist(10)
        table = page.findChild(TrackTable)
        assert table is not None
        table.sortByColumn(TrackColumn.TITLE, Qt.SortOrder.AscendingOrder)
        table.selectRow(1)  # Second "One" occurrence after sorting.
        selection = actions.selection(table)
        assert selection.entry_ids == (playlist.entries[3].entry_id,)
        assert not selection.reorderable
        actions.entries(selection, "remove")
        updated = workspace.playlist(10)
        assert updated is not None and updated.entries == playlist.entries[:3]
    finally:
        window.close()
        context.shutdown()


def test_normalization_preview_filters_do_not_change_the_applied_batch() -> None:
    context = build_context()
    workspace = context.library_workspace
    source = LibrarySnapshot((Track(1, " Song ", "The Artist", "Album", 100),))
    workspace.load(source)
    controller = TagNormalizationController(workspace)
    dialog = TagNormalizerDialog(controller)
    try:
        assert isinstance(dialog._fields, AppComboBox)  # pyright: ignore[reportPrivateUsage]
        dialog.start(TagProfile())
        until = monotonic() + 5
        while controller.scanning and monotonic() < until:
            APPLICATION.processEvents()
            sleep(0.005)
        assert not controller.scanning and dialog.model.rowCount() == 3
        search = dialog.findChild(QLineEdit)
        apply = dialog.findChild(QPushButton, "applyNormalization")
        assert search is not None and apply is not None and apply.isEnabled()
        search.setText("Sort Artist")
        assert dialog.model.rowCount() == 1 and not workspace.dirty
        apply.click()
        assert workspace.tracks[0].title == "Song"
        assert workspace.tracks[0].metadata.sort_artist == "Artist, The"
        assert workspace.snapshot is source
        assert not apply.isEnabled()
    finally:
        dialog.close()
        controller.shutdown()
        context.shutdown()
