import pytest
from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.core.settings.definitions import AppearanceMode
from iOpenPod.app.sync_storage import SyncStorageEstimate
from iOpenPod.GUI.widgets.sync_storage_bar import SyncStorageBar


@pytest.mark.parametrize("mode", [AppearanceMode.LIGHT, AppearanceMode.DARK])
@pytest.mark.parametrize(
    ("incoming", "outgoing", "sample", "color_role"),
    [(200, 0, 0.7, "success"), (0, 200, 0.5, "warning"), (600, 0, 0.8, "danger")],
)
def test_bar_paints_used_change_and_free_segments(
    mode: AppearanceMode, incoming: int, outgoing: int, sample: float, color_role: str
) -> None:
    context = build_context()
    bar = SyncStorageBar(context.theme_manager)
    try:
        context.theme_manager.set_mode(mode)
        bar.set_estimate(SyncStorageEstimate(1_000, 600, incoming, outgoing, 0))
        bar.resize(900, bar.sizeHint().height())
        bar.show()
        APPLICATION.processEvents()
        segments = bar.findChild(QWidget, "syncStorageSegments")
        assert segments is not None and segments.isVisible()
        image = segments.grab().toImage()
        tokens = context.theme_manager.tokens
        assert image.pixelColor(image.width() // 5, image.height() // 2) == QColor(
            tokens.accent
        )
        assert image.pixelColor(
            int(image.width() * sample), image.height() // 2
        ) == QColor(getattr(tokens, color_role))
        if incoming < 600:
            assert image.pixelColor(
                int(image.width() * 0.9), image.height() // 2
            ) == QColor(tokens.surface_alt)
        remaining = bar.findChild(QLabel, "syncStorageRemaining")
        assert remaining is not None
        if incoming == 600:
            assert remaining.text() == "About 200 B over capacity"
            assert remaining.property("status") == "over"
        assert "Converted file sizes may differ after preparation" in (
            segments.accessibleDescription()
        )
    finally:
        bar.close()
        bar.deleteLater()
        APPLICATION.sendPostedEvents(bar, QEvent.Type.DeferredDelete)
        context.shutdown()


def test_missing_capacity_and_partial_estimates_remain_explicit() -> None:
    context = build_context()
    bar = SyncStorageBar(context.theme_manager)
    try:
        bar.set_estimate(SyncStorageEstimate(0, 0, 200, 0, 0))
        segments = bar.findChild(QWidget, "syncStorageSegments")
        remaining = bar.findChild(QLabel, "syncStorageRemaining")
        title = bar.findChild(QLabel, "syncStorageTitle")
        note = bar.findChild(QLabel, "syncStorageNote")
        assert segments is not None and segments.isHidden()
        assert remaining is not None
        assert remaining.text() == "Device capacity unavailable"
        assert title is not None and note is not None

        bar.set_estimate(SyncStorageEstimate(1_000, 600, 200, 0, 2))
        assert not segments.isHidden()
        assert title.text() == "Partial iPod storage estimate"
        assert "2 unresolved items excluded" in note.text()
        assert remaining.property("status") == "partial"
        APPLICATION.sendEvent(bar, QEvent(QEvent.Type.LanguageChange))
        assert "2 unresolved items excluded" in note.text()

        bar.set_estimate(None)
        assert segments.isHidden()
        assert remaining.text() == "Device capacity unavailable"
        assert title.text() == "Estimated iPod storage"
    finally:
        bar.close()
        bar.deleteLater()
        APPLICATION.sendPostedEvents(bar, QEvent.Type.DeferredDelete)
        context.shutdown()
