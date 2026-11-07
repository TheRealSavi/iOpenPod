"""Chapter metadata and artwork share a cancellable editor draft."""

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QListWidget, QTableWidgetItem, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.GUI.dialogs.artwork_editor import ArtworkEditor
from iOpenPod.GUI.dialogs.metadata_editor import MetadataEditorDialog
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.metadata_field_editor import ChapterEditor
from iPodDB.library import (
    ArtworkPixels,
    LibrarySnapshot,
    TimedArtworkAsset,
    Track,
    TrackChapter,
    TrackMetadata,
)

_CHAPTERS = (TrackChapter("Opening", 0), TrackChapter("Interview", 1000))
_TRACK = Track(
    1, "Episode", "Host", "Series", 10_000, metadata=TrackMetadata(chapters=_CHAPTERS)
)
_RED = ArtworkPixels(1, 1, b"\xff\x00\x00")
_BLUE = ArtworkPixels(1, 1, b"\x00\x00\xff")


def _cell(editor: ChapterEditor, row: int, column: int) -> QTableWidgetItem:
    item = editor.table.item(row, column)
    assert item is not None
    return item


def test_chapter_names_and_times_update_artwork_choices_without_retiming_images() -> (
    None
):
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot((_TRACK,)))
    dialog = MetadataEditorDialog(workspace, (1,))
    try:
        chapters = dialog.rows["metadata.chapters"].editor
        artwork = dialog.findChild(ArtworkEditor)
        assert isinstance(chapters, ChapterEditor) and artwork is not None
        entries = artwork.findChild(AppComboBox, "metadataArtworkEntries")
        assert entries is not None
        artwork.set_pending_artwork(_RED)
        artwork.add_pending_artwork(_BLUE, 1000)
        _cell(chapters, 1, 1).setText("Guest")
        assert "Guest" in entries.itemText(entries.findData(1000))
        _cell(chapters, 1, 1).setText("Guest interview")
        assert "Guest interview" in entries.itemText(entries.findData(1000))
        _cell(chapters, 1, 0).setText("2000")
        assert "Guest interview" in entries.itemText(entries.findData(2000))
        assert entries.findData(1000) >= 0
        assert artwork.frame_source(1000) == _BLUE
        assert artwork.frame_source(2000) is None
        dialog.accept()
        track = workspace.track(1)
        assert track is not None
        assert track.metadata.chapters == (
            _CHAPTERS[0],
            TrackChapter("Guest interview", 2000),
        )
        asset = next(
            asset
            for asset in workspace.artwork_assets
            if asset.artwork_id == track.artwork_id
        )
        assert isinstance(asset, TimedArtworkAsset)
        assert tuple(frame.display_time_ms for frame in asset.frames) == (0, 1000)
    finally:
        dialog.close()


def test_chapter_thumbnail_cell_opens_its_artwork_slot_and_cancel_discards_both() -> (
    None
):
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot((_TRACK,)))
    dialog = MetadataEditorDialog(workspace, (1,))
    try:
        chapters = dialog.rows["metadata.chapters"].editor
        artwork = dialog.findChild(ArtworkEditor)
        nav = dialog.findChild(QListWidget, "metadataSectionNav")
        assert (
            isinstance(chapters, ChapterEditor)
            and artwork is not None
            and nav is not None
        )
        artwork.set_pending_artwork(_RED)
        artwork.add_pending_artwork(_BLUE, 1000)
        changes = QSignalSpy(chapters.chaptersChanged)
        chapters.refresh_artwork()
        assert changes.count() == 0
        assert chapters.table.columnCount() == 3
        assert not _cell(chapters, 1, 2).flags() & Qt.ItemFlag.ItemIsEditable
        nav.setCurrentItem(nav.findItems("Chapters", Qt.MatchFlag.MatchExactly)[0])
        dialog.show()
        APPLICATION.processEvents()
        QTest.mouseClick(
            chapters.table.viewport(),
            Qt.MouseButton.LeftButton,
            pos=chapters.table.visualItemRect(_cell(chapters, 1, 2)).center(),
        )
        assert nav.currentItem().text() == "Artwork"
        entries = artwork.findChild(AppComboBox, "metadataArtworkEntries")
        assert entries is not None and entries.currentData() == 1000
        pixmap = artwork.chapter_pixmap(1000, 40, 1.0)
        assert pixmap is not None and pixmap.toImage().pixelColor(0, 0).blue() == 255
        _cell(chapters, 1, 1).setText("Draft title")
        dialog.reject()
        assert workspace.track(1) == _TRACK
        assert not workspace.artwork_assets
        assert not workspace.dirty
    finally:
        dialog.close()


def test_mixed_chapter_selection_and_reset_keep_original_chapter_lists() -> None:
    workspace = LibraryWorkspace()
    second = replace(
        _TRACK, track_id=2, metadata=TrackMetadata(chapters=(TrackChapter("Other", 0),))
    )
    workspace.load(LibrarySnapshot((_TRACK, second)))
    dialog = MetadataEditorDialog(workspace, (1, 2))
    try:
        row = dialog.rows["metadata.chapters"]
        chapters = row.editor
        artwork = dialog.findChild(ArtworkEditor)
        assert isinstance(chapters, ChapterEditor) and artwork is not None
        assert row.mixed and not row.is_modified()
        assert not artwork.select_chapter(1000)
        chapters.set_chapters(_CHAPTERS)
        assert row.is_modified() and artwork.select_chapter(1000)
        row.reset()
        assert not row.is_modified() and not artwork.select_chapter(1000)
        dialog.accept()
        assert workspace.track(1) == _TRACK and workspace.track(2) == second
    finally:
        dialog.close()


def test_chapter_table_requests_only_visible_thumbnail_cells_without_metadata_edits() -> (
    None
):
    parent = QWidget()
    editor = ChapterEditor(
        tuple(TrackChapter(str(i), i * 1000) for i in range(100)), parent
    )
    calls: list[int] = []

    def preview(start_ms: int, _size: int, _ratio: float) -> QPixmap | None:
        calls.append(start_ms)
        return None

    editor.set_artwork_preview(preview)
    changed = QSignalSpy(editor.chaptersChanged)
    parent.resize(600, 300)
    editor.resize(600, 300)
    try:
        assert not calls
        parent.show()
        APPLICATION.processEvents()
        assert calls and len(set(calls)) < 10
        assert changed.count() == 0
        calls.clear()
        editor.table.scrollToBottom()
        APPLICATION.processEvents()
        assert 99_000 in calls and 0 not in calls
        assert changed.count() == 0
    finally:
        parent.close()
