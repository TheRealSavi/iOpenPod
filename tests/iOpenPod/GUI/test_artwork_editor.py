"""Track artwork editing keeps decoded images inside bounded RGB contracts."""

from collections.abc import Callable
from time import monotonic

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QListWidget, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.GUI.dialogs.artwork_editor import (
    ArtworkCropDialog,
    ArtworkEditor,
    ConsolidateArtworkDialog,
    artwork_pixels_from_image,
)
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.stylesheet import render_stylesheet
from iOpenPod.GUI.presentation.theme.tokens import (
    DARK_TOKENS,
    LIGHT_TOKENS,
    ORIGINAL_DARK_TOKENS,
    ThemeTokens,
    resolve_typography,
)
from iPodDB.library import ArtworkAsset, ArtworkPixels, Track


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
