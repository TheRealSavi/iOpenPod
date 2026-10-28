"""Track artwork editing keeps decoded images inside bounded RGB contracts."""

from collections.abc import Callable
from pathlib import Path
from threading import Event
from time import monotonic

import pytest
from PySide6.QtCore import QEvent, QLocale, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QPushButton,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app import artwork_import
from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.artwork_import import ArtworkImportController
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.GUI.dialogs.artwork_editor import (
    ArtworkCropDialog,
    ArtworkEditor,
    ConsolidateArtworkDialog,
    artwork_pixels_from_image,
)
from iOpenPod.GUI.dialogs.metadata_editor import MetadataEditorDialog
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.stylesheet import render_stylesheet
from iOpenPod.GUI.presentation.theme.tokens import (
    DARK_TOKENS,
    LIGHT_TOKENS,
    ORIGINAL_DARK_TOKENS,
    ThemeTokens,
    resolve_typography,
)
from iPodDB.library import (
    ArtworkAsset,
    ArtworkGroupReference,
    ArtworkPixels,
    LibrarySnapshot,
    TimedArtworkAsset,
    TimedArtworkFrame,
    Track,
    TrackChapter,
    TrackMetadata,
)
from storage import HostPath


def test_rgb888_copy_removes_qimage_row_padding() -> None:
    image = QImage(1, 2, QImage.Format.Format_RGB888)
    image.setPixelColor(0, 0, QColor(1, 2, 3))
    image.setPixelColor(0, 1, QColor(4, 5, 6))
    assert image.bytesPerLine() > image.width() * 3

    pixels = artwork_pixels_from_image(image)

    assert (pixels.width, pixels.height) == (1, 2)
    assert pixels.rgb888 == b"\x01\x02\x03\x04\x05\x06"


def test_crop_produces_bounded_owned_square() -> None:
    image = QImage(2400, 1600, QImage.Format.Format_RGB888)
    image.fill(QColor(12, 34, 56))

    dialog = ArtworkCropDialog(image)
    try:
        dialog.show()
        APPLICATION.processEvents()
        pixels = dialog.pixels()
        assert (pixels.width, pixels.height) == (1200, 1200)
        assert len(pixels.rgb888) == 1200 * 1200 * 3
    finally:
        dialog.close()


@pytest.mark.parametrize("tokens", (LIGHT_TOKENS, DARK_TOKENS, ORIGINAL_DARK_TOKENS))
def test_crop_dialog_uses_active_theme_surface(tokens: ThemeTokens) -> None:
    original_stylesheet = APPLICATION.styleSheet()
    APPLICATION.setStyleSheet(render_stylesheet(tokens, resolve_typography()))
    image = QImage(4, 4, QImage.Format.Format_RGB888)
    image.fill(QColor(12, 34, 56))
    dialog = ArtworkCropDialog(image)
    try:
        dialog.show()
        dialog.ensurePolished()
        APPLICATION.processEvents()
        assert dialog.grab().toImage().pixelColor(2, 2) == QColor(tokens.window)
    finally:
        dialog.close()
        APPLICATION.setStyleSheet(original_stylesheet)


class _MatchingArtworkLoader:
    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage:
        return ArtworkImage(
            cache_key=f"matching:{request.artwork_id}:{request.target_px}",
            artwork_id=request.artwork_id,
            format_id=1061,
            width=2,
            height=2,
            rgb888=bytes((12, 34, 56)) * 4,
        )


class _UniqueArtworkLoader:
    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage:
        color = (12, 34, 56) if request.artwork_id in (101, 202) else (90, 80, 70)
        return ArtworkImage(
            cache_key=f"unique:{request.artwork_id}:{request.target_px}",
            artwork_id=request.artwork_id,
            format_id=1061,
            width=2,
            height=2,
            rgb888=bytes(color) * 4,
        )


def test_distinct_artwork_ids_with_identical_pixels_show_one_image() -> None:
    controller = ArtworkController(_MatchingArtworkLoader())
    provider = ArtworkPixmapProvider(controller)
    editor = ArtworkEditor(
        (
            Track(1, "One", "Artist", "Album", 1, artwork_id=101),
            Track(2, "Two", "Artist", "Album", 1, artwork_id=202),
        ),
        (),
        provider,
    )
    try:
        editor.show()
        preview = editor.findChild(QLabel, "metadataArtworkImage")
        status = editor.findChild(QLabel, "metadataArtworkStatus")
        consolidate = editor.findChild(QPushButton, "consolidateTrackArtwork")
        assert preview is not None and status is not None and consolidate is not None
        _wait_until(
            lambda: (
                not preview.pixmap().isNull()
                and status.text() == "Current artwork shared by all selected Tracks."
            )
        )
        assert preview.text() == ""
        assert consolidate.isHidden()
    finally:
        editor.shutdown()
        editor.close()
        provider.shutdown()
        controller.shutdown()


def test_consolidation_grid_combines_identical_pixels_and_returns_one_identity() -> (
    None
):
    controller = ArtworkController(_UniqueArtworkLoader())
    provider = ArtworkPixmapProvider(controller)
    dialog = ConsolidateArtworkDialog((101, 202, 303), (), provider)
    try:
        dialog.show()
        grid = dialog.findChild(QListWidget, "artworkConsolidationGrid")
        assert grid is not None
        _wait_until(
            lambda: (
                grid.count() == 2
                and all(not grid.item(index).icon().isNull() for index in range(2))
            )
        )
        assert grid.item(0).data(Qt.ItemDataRole.UserRole) == 101
        assert grid.item(0).text() == "Used by 2 Tracks"

        rect = grid.visualItemRect(grid.item(0))
        QTest.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())

        assert dialog.result() == dialog.DialogCode.Accepted
        assert dialog.selected_artwork_id == 101
    finally:
        dialog.close()
        provider.shutdown()
        controller.shutdown()


def test_consolidation_refreshes_retained_sources_of_negative_draft_timelines() -> None:
    controller = ArtworkController(_TimedArtworkLoader())
    provider = ArtworkPixmapProvider(controller)
    assets = tuple(
        TimedArtworkAsset(
            draft_id,
            (
                TimedArtworkFrame(0, ArtworkGroupReference(source_id, 0)),
                TimedArtworkFrame(10_000, ArtworkGroupReference(source_id, 10_000)),
            ),
        )
        for draft_id, source_id in ((-1, 101), (-2, 202))
    )
    dialog = ConsolidateArtworkDialog((-1, -2), assets, provider)
    try:
        grid = dialog.findChild(QListWidget, "artworkConsolidationGrid")
        assert grid is not None and grid.count() == 2
        assert all(grid.item(index).icon().isNull() for index in range(2))
        _wait_until(
            lambda: all(not grid.item(index).icon().isNull() for index in range(2))
        )
        assert grid.count() == 2
        assert [
            grid.item(index).data(Qt.ItemDataRole.UserRole) for index in range(2)
        ] == [
            -1,
            -2,
        ]
    finally:
        dialog.close()
        provider.shutdown()
        controller.shutdown()


def test_consolidate_action_only_appears_for_multiple_artwork_values() -> None:
    red = ArtworkPixels(1, 1, b"\xff\0\0")
    blue = ArtworkPixels(1, 1, b"\0\0\xff")
    mixed = ArtworkEditor(
        (
            Track(1, "One", "Artist", "Album", 1, artwork_id=101),
            Track(2, "Two", "Artist", "Album", 1, artwork_id=202),
        ),
        (ArtworkAsset(101, red), ArtworkAsset(202, blue)),
    )
    shared = ArtworkEditor(
        (
            Track(1, "One", "Artist", "Album", 1, artwork_id=101),
            Track(2, "Two", "Artist", "Album", 1, artwork_id=101),
        ),
        (),
    )
    try:
        mixed_button = mixed.findChild(QPushButton, "consolidateTrackArtwork")
        shared_button = shared.findChild(QPushButton, "consolidateTrackArtwork")
        assert mixed_button is not None and not mixed_button.isHidden()
        assert shared_button is not None and shared_button.isHidden()
    finally:
        mixed.shutdown()
        mixed.close()
        shared.shutdown()
        shared.close()


def _wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(10)
    APPLICATION.processEvents()
    assert predicate(), "Timed out waiting for artwork preview"


class _TimedArtworkLoader:
    def __init__(self) -> None:
        self.requests: list[ArtworkRequest] = []

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage:
        self.requests.append(request)
        color = (255, 0, 0) if request.display_time_ms == 0 else (0, 0, 255)
        return ArtworkImage(
            cache_key=f"timed:{request.artwork_id}:{request.display_time_ms}:{request.target_px}",
            artwork_id=request.artwork_id,
            format_id=1029,
            width=2,
            height=2,
            rgb888=bytes(color) * 4,
            display_time_ms=request.display_time_ms,
        )


def test_chapter_selection_reads_exact_group_without_retiming_after_chapter_edit() -> (
    None
):
    loader = _TimedArtworkLoader()
    controller = ArtworkController(loader, display_times=lambda _id: (0, 10_000))
    provider = ArtworkPixmapProvider(controller)
    editor = ArtworkEditor(
        (
            Track(
                1,
                "One",
                "Artist",
                "Album",
                30_000,
                artwork_id=101,
                metadata=TrackMetadata(
                    chapters=(TrackChapter("Opening", 1), TrackChapter("Next", 10_000))
                ),
            ),
        ),
        (),
        provider,
    )
    try:
        entries = editor.findChild(QComboBox, "metadataArtworkEntries")
        assert editor.findChild(QDoubleSpinBox, "metadataArtworkTime") is None
        preview = editor.findChild(QLabel, "metadataArtworkImage")
        remove = editor.findChild(QPushButton, "removeTimedArtwork")
        assert entries is not None and preview is not None and remove is not None
        assert entries.count() == 2 and not remove.isEnabled()
        assert [entries.itemText(index) for index in range(2)] == [
            "1. Opening",
            "2. Next",
        ]
        _wait_until(lambda: not preview.pixmap().isNull())
        assert [request.display_time_ms for request in loader.requests] == [0]
        assert not editor.is_modified()

        entries.setCurrentIndex(1)
        _wait_until(
            lambda: (
                not preview.pixmap().isNull()
                and preview.pixmap().toImage().pixelColor(0, 0).blue() == 255
            )
        )
        assert [request.display_time_ms for request in loader.requests] == [0, 10_000]
        assert not editor.is_modified()
        editor.set_chapters(
            (TrackChapter("Opening", 1), TrackChapter("Renamed", 12_345))
        )
        assert editor.edit() is None
        assert entries.currentData() == 10_000
        assert entries.currentText() == "Unassigned artwork — 10.000 seconds"
        assert editor.frame_source(12_345) is None
        assert editor.frame_source(10_000) == ArtworkGroupReference(101, 10_000)
        assert [request.display_time_ms for request in loader.requests] == [0, 10_000]
        signals = QSignalSpy(editor.modifiedChanged)
        APPLICATION.sendEvent(editor, QEvent(QEvent.Type.LanguageChange))
        assert signals.count() == 0 and editor.edit() is None
        assert entries.currentData() == 10_000
        assert editor.select_chapter(12_345)
        editor.set_pending_artwork(ArtworkPixels(1, 1, b"\0\xff\0"))
        editor.reset()
        assert not editor.is_modified() and entries.currentData() == 0
        assert entries.itemData(1) == 12_345
        assert entries.itemData(2) == 10_000
    finally:
        editor.shutdown()
        editor.close()
        provider.shutdown()
        controller.shutdown()


def test_late_previous_frame_does_not_replace_selected_preview_or_create_an_edit() -> (
    None
):
    class Loader(_TimedArtworkLoader):
        def __init__(self) -> None:
            super().__init__()
            self.release_cover = Event()

        def load_artwork(self, request: ArtworkRequest) -> ArtworkImage:
            if request.display_time_ms == 0:
                assert self.release_cover.wait(3)
            return super().load_artwork(request)

    loader = Loader()
    controller = ArtworkController(loader, display_times=lambda _id: (0, 10_000))
    provider = ArtworkPixmapProvider(controller)
    editor = ArtworkEditor(
        (Track(1, "One", "Artist", "Album", 30_000, artwork_id=101),), (), provider
    )
    try:
        entries = editor.findChild(QComboBox, "metadataArtworkEntries")
        preview = editor.findChild(QLabel, "metadataArtworkImage")
        assert entries is not None and preview is not None
        entries.setCurrentIndex(1)
        _wait_until(lambda: not preview.pixmap().isNull())
        assert preview.pixmap().toImage().pixelColor(0, 0).blue() == 255
        loader.release_cover.set()
        _wait_until(lambda: controller.pending_count == 0)
        assert entries.currentData() == 10_000
        assert preview.pixmap().toImage().pixelColor(0, 0).blue() == 255
        assert editor.edit() is None
    finally:
        loader.release_cover.set()
        editor.shutdown()
        editor.close()
        provider.shutdown()
        controller.shutdown()


def test_timed_editor_adds_sorts_replaces_and_removes_only_selected_entry() -> None:
    red = ArtworkPixels(1, 1, b"\xff\0\0")
    blue = ArtworkPixels(1, 1, b"\0\0\xff")
    green = ArtworkPixels(1, 1, b"\0\xff\0")
    asset = TimedArtworkAsset(
        -1, (TimedArtworkFrame(0, red), TimedArtworkFrame(10_000, blue))
    )
    editor = ArtworkEditor(
        (Track(1, "One", "Artist", "Album", 30_000, artwork_id=-1),), (asset,)
    )
    try:
        entries = editor.findChild(QComboBox, "metadataArtworkEntries")
        assert entries is not None
        editor.add_pending_artwork(green, 5_000)
        edit = editor.edit()
        assert edit is not None and edit.frames is not None
        assert tuple(frame.display_time_ms for frame in edit.frames) == (
            0,
            5_000,
            10_000,
        )
        assert entries.currentData() == 5_000
        with pytest.raises(ValueError, match="different display time"):
            editor.add_pending_artwork(red, 5_000)
        assert editor.edit() == edit

        entries.setCurrentIndex(entries.findData(10_000))
        editor.set_pending_artwork(green)
        replaced = editor.edit()
        assert replaced is not None and replaced.frames == (
            TimedArtworkFrame(0, red),
            TimedArtworkFrame(5_000, green),
            TimedArtworkFrame(10_000, green),
        )
        editor.remove_selected_entry()
        removed = editor.edit()
        assert removed is not None and removed.frames == (
            TimedArtworkFrame(0, red),
            TimedArtworkFrame(5_000, green),
        )
        entries.setCurrentIndex(entries.findData(5_000))
        editor.remove_selected_entry()
        editor.set_pending_artwork(blue)
        single = editor.edit()
        assert single is not None and single.frames == (TimedArtworkFrame(0, blue),)
        editor.clear_artwork()
        cleared = editor.edit()
        assert cleared is not None and cleared.frames is None
        assert entries.count() == 1 and entries.currentText() == "Cover"
        editor.reset()
        assert entries.count() == 2 and not editor.is_modified()
        assert asset.frames[1].source == blue
    finally:
        editor.shutdown()
        editor.close()


def test_timed_sequences_with_matching_covers_remain_distinct_in_consolidation() -> (
    None
):
    red = ArtworkPixels(1, 1, b"\xff\0\0")
    blue = ArtworkPixels(1, 1, b"\0\0\xff")
    assets = (
        TimedArtworkAsset(
            -1, (TimedArtworkFrame(0, red), TimedArtworkFrame(10_000, blue))
        ),
        TimedArtworkAsset(
            -2, (TimedArtworkFrame(0, red), TimedArtworkFrame(20_000, blue))
        ),
    )
    editor = ArtworkEditor(
        (
            Track(1, "One", "Artist", "Album", 30_000, artwork_id=-1),
            Track(2, "Two", "Artist", "Album", 30_000, artwork_id=-2),
        ),
        assets,
    )
    dialog = ConsolidateArtworkDialog((-1, -2), assets)
    try:
        grid = dialog.findChild(QListWidget, "artworkConsolidationGrid")
        choose = editor.findChild(QPushButton, "chooseTrackArtwork")
        consolidate = editor.findChild(QPushButton, "consolidateTrackArtwork")
        assert grid is not None and grid.count() == 2
        assert choose is not None and choose.isEnabled()
        assert consolidate is not None and not consolidate.isHidden()
        editor.set_pending_artwork(red)
        replacement = editor.edit()
        assert replacement is not None and replacement.frames == (
            TimedArtworkFrame(0, red),
        )
        editor.reset()
        editor.set_pending_artwork_id(-2)
        entries = editor.findChild(QComboBox, "metadataArtworkEntries")
        assert entries is not None and entries.itemData(1) == 20_000
        assert choose.isEnabled()
        selected = editor.edit()
        assert selected is not None and selected.source_artwork_id == -2
        editor.clear_artwork()
        editor.set_pending_artwork(blue)
        after_clear = editor.edit()
        assert after_clear is not None and after_clear.frames == (
            TimedArtworkFrame(0, blue),
        )
    finally:
        dialog.close()
        editor.shutdown()
        editor.close()


def test_cancelled_crop_keeps_original_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    red = ArtworkPixels(1, 1, b"\xff\0\0")
    asset = TimedArtworkAsset(
        -1, (TimedArtworkFrame(0, red), TimedArtworkFrame(10_000, red))
    )
    editor = ArtworkEditor(
        (Track(1, "One", "Artist", "Album", 30_000, artwork_id=-1),), (asset,)
    )
    opened: list[ArtworkCropDialog] = []

    def reject_crop(dialog: ArtworkCropDialog) -> int:
        opened.append(dialog)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(ArtworkCropDialog, "exec", reject_crop)
    try:
        importer = editor.findChild(ArtworkImportController)
        assert importer is not None
        importer.finished.emit(red, "ignored.png")
        assert len(opened) == 1
        assert not editor.is_modified()
        entries = editor.findChild(QComboBox, "metadataArtworkEntries")
        assert entries is not None and entries.count() == 2
    finally:
        editor.shutdown()
        editor.close()


def test_metadata_dialog_applies_one_shared_timeline_and_reopens_its_entries() -> None:
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            (
                Track(1, "One", "Artist", "Album", 30_000),
                Track(2, "Two", "Artist", "Album", 30_000),
                Track(3, "Three", "Artist", "Album", 30_000),
            )
        )
    )
    dialog = MetadataEditorDialog(workspace, (1, 2))
    reopened: MetadataEditorDialog | None = None
    try:
        editor = dialog.findChild(ArtworkEditor)
        assert editor is not None
        red = ArtworkPixels(1, 1, b"\xff\0\0")
        blue = ArtworkPixels(1, 1, b"\0\0\xff")
        editor.set_pending_artwork(red)
        editor.add_pending_artwork(blue, 10_000)
        revision = workspace.edit_revision.revision
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert workspace.edit_revision.revision == revision + 1
        assert workspace.tracks[0].artwork_id == workspace.tracks[1].artwork_id != 0
        assert workspace.tracks[2].artwork_id == 0
        asset = workspace.artwork_assets[0]
        assert isinstance(asset, TimedArtworkAsset)
        assert asset.frames == (
            TimedArtworkFrame(0, red),
            TimedArtworkFrame(10_000, blue),
        )
        reopened = MetadataEditorDialog(workspace, (1,))
        entries = reopened.findChild(QComboBox, "metadataArtworkEntries")
        preview = reopened.findChild(QLabel, "metadataArtworkImage")
        assert entries is not None and preview is not None
        assert entries.count() == 2
        entries.setCurrentIndex(1)
        assert preview.pixmap().toImage().pixelColor(0, 0).blue() == 255
    finally:
        if reopened is not None:
            reopened.close()
        dialog.close()


@pytest.mark.parametrize("locale_name", ("de_DE", "es_ES"))
@pytest.mark.parametrize(
    "time_ms,number", ((10_000, "10,000"), (1_234_567, "1234,567"))
)
def test_unassigned_entry_caption_uses_locale_without_changing_milliseconds(
    locale_name: str, time_ms: int, number: str
) -> None:
    red = ArtworkPixels(1, 1, b"\xff\0\0")
    asset = TimedArtworkAsset(
        -1, (TimedArtworkFrame(0, red), TimedArtworkFrame(time_ms, red))
    )
    editor = ArtworkEditor(
        (Track(1, "One", "Artist", "Album", 3_000_000, artwork_id=-1),), (asset,)
    )
    try:
        entries = editor.findChild(QComboBox, "metadataArtworkEntries")
        assert entries is not None
        entries.setCurrentIndex(1)
        modified = QSignalSpy(editor.modifiedChanged)
        editor.setLocale(QLocale(locale_name))
        assert entries.currentText() == f"Unassigned artwork — {number} seconds"
        assert entries.currentData() == time_ms
        assert modified.count() == 0 and not editor.is_modified()
    finally:
        editor.shutdown()
        editor.close()


def test_legacy_special_entry_is_viewable_and_can_be_retained_after_adding_zero() -> (
    None
):
    loader = _TimedArtworkLoader()
    controller = ArtworkController(loader, display_times=lambda _id: (0xFFFFFFFF,))
    provider = ArtworkPixmapProvider(controller)
    editor = ArtworkEditor(
        (Track(1, "One", "Artist", "Album", 30_000, artwork_id=101),), (), provider
    )
    try:
        entries = editor.findChild(QComboBox, "metadataArtworkEntries")
        choose = editor.findChild(QPushButton, "chooseTrackArtwork")
        assert entries is not None and choose is not None
        assert entries.currentData() == 0 and choose.isEnabled()
        entries.setCurrentIndex(entries.findData(0xFFFFFFFF))
        assert entries.currentText() == "Preserved special entry"
        assert not choose.isEnabled()
        assert not editor.is_modified()
        red = ArtworkPixels(1, 1, b"\xff\0\0")
        entries.setCurrentIndex(entries.findData(0))
        editor.set_pending_artwork(red)
        edit = editor.edit()
        assert edit is not None and edit.frames == (
            TimedArtworkFrame(0, red),
            TimedArtworkFrame(0xFFFFFFFF, ArtworkGroupReference(101, 0xFFFFFFFF)),
        )
    finally:
        editor.shutdown()
        editor.close()
        provider.shutdown()
        controller.shutdown()


def test_empty_chapter_slot_assigns_selected_start_and_preserves_other_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    red = ArtworkPixels(1, 1, b"\xff\0\0")
    blue = ArtworkPixels(1, 1, b"\0\0\xff")
    editor = ArtworkEditor(
        (Track(1, "Book", "Author", "Album", 60_000, artwork_id=-1),),
        (ArtworkAsset(-1, red),),
    )

    def accept_crop(_dialog: ArtworkCropDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(ArtworkCropDialog, "exec", accept_crop)
    try:
        editor.set_chapters(
            (TrackChapter("Introduction", 1), TrackChapter("A title", 23_456))
        )
        entries = editor.findChild(QComboBox, "metadataArtworkEntries")
        choose = editor.findChild(QPushButton, "chooseTrackArtwork")
        remove = editor.findChild(QPushButton, "removeTimedArtwork")
        preview = editor.findChild(QLabel, "metadataArtworkImage")
        importer = editor.findChild(ArtworkImportController)
        assert entries is not None and choose is not None and remove is not None
        assert preview is not None and importer is not None
        assert editor.select_chapter(23_456)
        assert entries.currentText() == "2. A title"
        assert choose.isEnabled() and not remove.isEnabled()
        assert choose.text() == "Choose Artwork…" and preview.pixmap().isNull()
        assert editor.frame_source(23_456) is None
        assert not editor.is_modified()

        modified = QSignalSpy(editor.modifiedChanged)
        previews = QSignalSpy(editor.previewChanged)
        importer.finished.emit(blue, "chapter.png")
        edit = editor.edit()
        assert edit is not None and edit.frames == (
            TimedArtworkFrame(0, red),
            TimedArtworkFrame(23_456, blue),
        )
        assert modified.count() == 1 and previews.count() > 0
        assert editor.frame_source(1) == red
        assert editor.frame_source(23_456) == blue
        assert choose.text() == "Replace Image…" and remove.isEnabled()
        editor.remove_selected_entry()
        assert editor.select_chapter(23_456)
        assert editor.frame_source(23_456) is None and not remove.isEnabled()
        editor.reset()
        assert not editor.is_modified() and editor.frame_source(1) == red
    finally:
        editor.shutdown()
        editor.close()


def test_later_chapter_requires_deliberate_zero_time_cover_before_assignment() -> None:
    editor = ArtworkEditor((Track(1, "Book", "Author", "Album", 60_000),), ())
    pixels = ArtworkPixels(1, 1, b"\xff\0\0")
    try:
        editor.set_chapters((TrackChapter("First section", 5_000),))
        choose = editor.findChild(QPushButton, "chooseTrackArtwork")
        entries = editor.findChild(QComboBox, "metadataArtworkEntries")
        assert choose is not None and entries is not None
        assert entries.itemText(0) == "Cover"
        assert editor.select_chapter(5_000) and not choose.isEnabled()
        with pytest.raises(ValueError, match="cover image"):
            editor.set_pending_artwork(pixels)
        assert editor.edit() is None
        entries.setCurrentIndex(0)
        editor.set_pending_artwork(pixels)
        assert editor.select_chapter(5_000) and choose.isEnabled()
        editor.set_pending_artwork(pixels)
        edit = editor.edit()
        assert edit is not None and edit.frames == (
            TimedArtworkFrame(0, pixels),
            TimedArtworkFrame(5_000, pixels),
        )
    finally:
        editor.shutdown()
        editor.close()


def test_chapter_labels_keep_duplicate_titles_distinct_and_mixed_chapters_explicit() -> (
    None
):
    chapters = (
        TrackChapter("Same", 0),
        TrackChapter("Same", 10_000),
        TrackChapter("", 20_000),
    )
    tracks = (
        Track(
            1,
            "One",
            "Artist",
            "Album",
            30_000,
            metadata=TrackMetadata(chapters=chapters),
        ),
        Track(2, "Two", "Artist", "Album", 30_000),
    )
    editor = ArtworkEditor(tracks, ())
    try:
        entries = editor.findChild(QComboBox, "metadataArtworkEntries")
        assert entries is not None and entries.count() == 1
        assert not editor.select_chapter(10_000)
        editor.set_chapters(chapters)
        assert [entries.itemText(i) for i in range(entries.count())] == [
            "1. Same",
            "2. Same",
            "3. Untitled Chapter",
        ]
        assert editor.select_chapter(10_000)
        assert entries.currentData() == 10_000
        editor.set_chapters(None)
        assert entries.count() == 1 and entries.currentText() == "Cover"
        assert not editor.is_modified()
    finally:
        editor.shutdown()
        editor.close()


def test_chapter_thumbnail_sources_are_metadata_only_and_decode_exact_group_lazily() -> (
    None
):
    loader = _TimedArtworkLoader()
    controller = ArtworkController(loader, display_times=lambda _id: (0, 10_000))
    provider = ArtworkPixmapProvider(controller)
    editor = ArtworkEditor(
        (Track(1, "Book", "Author", "Album", 30_000, artwork_id=101),), (), provider
    )
    try:
        _wait_until(lambda: controller.pending_count == 0)
        assert [request.display_time_ms for request in loader.requests] == [0]
        assert editor.frame_source(10_000) == ArtworkGroupReference(101, 10_000)
        assert editor.frame_source(15_000) is None
        assert [request.display_time_ms for request in loader.requests] == [0]
        preview_signals = QSignalSpy(editor.previewChanged)
        assert editor.chapter_pixmap(10_000, 32, 2.0) is None
        _wait_until(lambda: controller.pending_count == 0)
        thumbnail = editor.chapter_pixmap(10_000, 32, 2.0)
        assert (
            thumbnail is not None and thumbnail.toImage().pixelColor(0, 0).blue() == 255
        )
        assert [(r.display_time_ms, r.target_px) for r in loader.requests] == [
            (0, 256),
            (10_000, 64),
        ]
        assert preview_signals.count() > 0 and editor.edit() is None
    finally:
        editor.shutdown()
        editor.close()
        provider.shutdown()
        controller.shutdown()


def test_staged_chapter_thumbnail_is_scaled_cached_and_invalidated_after_replacement() -> (
    None
):
    red = ArtworkPixels(1, 1, b"\xff\0\0")
    blue = ArtworkPixels(1, 1, b"\0\0\xff")
    editor = ArtworkEditor((Track(1, "One", "Artist", "Album", 30_000),), ())
    try:
        editor.set_pending_artwork(red)
        first = editor.chapter_pixmap(1, 32, 2.0)
        second = editor.chapter_pixmap(1, 32, 2.0)
        assert first is not None and second is not None
        assert first.cacheKey() == second.cacheKey()
        assert first.width() == 64 and first.devicePixelRatio() == 2.0
        assert editor.chapter_pixmap(5_000, 32, 1.0) is None
        editor.set_pending_artwork(blue)
        replaced = editor.chapter_pixmap(0, 32, 2.0)
        assert (
            replaced is not None and replaced.toImage().pixelColor(0, 0).blue() == 255
        )
        editor.reset()
        assert editor.chapter_pixmap(0, 32, 2.0) is None
    finally:
        editor.shutdown()
        editor.close()


@pytest.mark.parametrize(
    "starts", ((0, 1), (10_000, 0), (-1, 10_000), (0, 0xFFFFFFFF), (10_000, 10_000))
)
def test_invalid_chapter_slots_keep_retained_images_accessible_without_authoring(
    starts: tuple[int, int],
) -> None:
    red = ArtworkPixels(1, 1, b"\xff\0\0")
    asset = TimedArtworkAsset(
        -1, (TimedArtworkFrame(0, red), TimedArtworkFrame(10_000, red))
    )
    editor = ArtworkEditor(
        (Track(1, "Book", "Author", "Album", 30_000, artwork_id=-1),), (asset,)
    )
    try:
        editor.set_chapters(
            tuple(TrackChapter(str(i), start) for i, start in enumerate(starts))
        )
        entries = editor.findChild(QComboBox, "metadataArtworkEntries")
        assert entries is not None and entries.count() == 2
        assert entries.itemText(0) == "Cover"
        assert entries.itemText(1) == "Unassigned artwork — 10.000 seconds"
        assert not editor.select_chapter(10_000)
        assert editor.frame_source(10_000) == red and editor.edit() is None
    finally:
        editor.shutdown()
        editor.close()


def test_sequence_note_compares_normalized_ordered_chapters_and_artwork() -> None:
    red = ArtworkPixels(1, 1, b"\xff\0\0")
    asset = TimedArtworkAsset(
        -1, (TimedArtworkFrame(0, red), TimedArtworkFrame(10_000, red))
    )
    editor = ArtworkEditor(
        (Track(1, "Book", "Author", "Album", 30_000, artwork_id=-1),), (asset,)
    )
    try:
        note = editor.findChild(QLabel, "metadataArtworkSequenceNote")
        assert note is not None and note.isHidden()
        editor.set_chapters((TrackChapter("One", 1), TrackChapter("Two", 10_000)))
        assert note.isHidden()
        editor.set_chapters((TrackChapter("One", 1), TrackChapter("Two", 20_000)))
        assert not note.isHidden()
        assert editor.edit() is None
        editor.set_chapters(
            (
                TrackChapter("One", 1),
                TrackChapter("Two", 10_000),
                TrackChapter("Three", 20_000),
            )
        )
        assert not note.isHidden()
        editor.select_chapter(20_000)
        editor.set_pending_artwork(red)
        assert note.isHidden()
    finally:
        editor.shutdown()
        editor.close()


@pytest.mark.parametrize("cancel", (False, True))
def test_pending_import_keeps_original_chapter_or_is_cancelled_when_chapters_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cancel: bool
) -> None:
    red = ArtworkPixels(1, 1, b"\xff\0\0")
    blue = ArtworkPixels(1, 1, b"\0\0\xff")
    release = Event()
    started = Event()

    def load(_source: HostPath, *, checkpoint: Callable[[], None]) -> ArtworkPixels:
        started.set()
        assert release.wait(3)
        checkpoint()
        return blue

    monkeypatch.setattr(artwork_import, "import_artwork", load)

    def choose_file(*_args: object) -> tuple[str, str]:
        return str(tmp_path / "image.png"), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", choose_file)

    def accept_crop(_dialog: ArtworkCropDialog) -> int:
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(ArtworkCropDialog, "exec", accept_crop)
    editor = ArtworkEditor(
        (Track(1, "Book", "Author", "Album", 30_000, artwork_id=-1),),
        (ArtworkAsset(-1, red),),
    )
    try:
        editor.set_chapters((TrackChapter("One", 0), TrackChapter("Two", 10_000)))
        choose = editor.findChild(QPushButton, "chooseTrackArtwork")
        entries = editor.findChild(QComboBox, "metadataArtworkEntries")
        assert choose is not None and entries is not None
        editor.select_chapter(10_000)
        choose.click()
        _wait_until(started.is_set)
        assert editor.busy and not editor.select_chapter(0)
        entries.setCurrentIndex(0)
        assert entries.currentData() == 10_000
        if cancel:
            editor.set_chapters((TrackChapter("One", 0), TrackChapter("Moved", 20_000)))
        release.set()
        if cancel:
            editor.shutdown()
            APPLICATION.processEvents()
            assert editor.edit() is None
            assert editor.frame_source(10_000) is None
        else:
            _wait_until(lambda: editor.edit() is not None)
            edit = editor.edit()
            assert edit is not None and edit.frames == (
                TimedArtworkFrame(0, red),
                TimedArtworkFrame(10_000, blue),
            )
    finally:
        release.set()
        editor.shutdown()
        editor.close()
