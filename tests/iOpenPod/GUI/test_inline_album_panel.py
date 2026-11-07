"""Compact Album contents retain Track identity, order, and readable geometry."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QLabel, QToolButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.context import AppContext
from iOpenPod.app.core.settings.definitions import AppearanceMode
from iOpenPod.app.models.album_list_model import AlbumRole, AlbumSummary
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.app.models.track_table_model import TrackRole
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.dynamic import colorful_card_fill
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.inline_album_panel import InlineAlbumPanel
from iPodDB.library import Track, TrackMetadata


@pytest.fixture
def context() -> Iterator[AppContext]:
    context = build_context()
    context.track_model.reset_tracks(
        tuple(
            Track(
                number,
                f"Song {number}",
                "Artist",
                "Album",
                181_000,
                track_number=((number - 1) % 10) + 1,
                rating=80,
                metadata=TrackMetadata(disc_number=1 if number <= 10 else 2),
            )
            for number in reversed(range(1, 18))
        )
    )
    yield context
    context.shutdown()


def _panel(context: AppContext, width: int) -> InlineAlbumPanel:
    proxy = TrackFilterProxyModel(context.track_model)
    provider = ArtworkPixmapProvider(context.artwork_controller)
    panel = InlineAlbumPanel(proxy, context.theme_manager, provider)
    proxy.setParent(panel)
    provider.setParent(panel)
    summary = context.album_model.index(0, 0).data(AlbumRole.SUMMARY)
    assert isinstance(summary, AlbumSummary)
    proxy.set_album_key(summary.key)
    panel.set_context(summary)
    panel.resize(width, panel.preferred_height(width))
    panel.show()
    APPLICATION.processEvents()
    return panel


def _ids(panel: InlineAlbumPanel) -> list[int]:
    model = panel.track_view.model()
    return [
        value
        for column in range(model.columnCount())
        for row in range(model.rowCount())
        if isinstance(value := model.index(row, column).data(TrackRole.TRACK_ID), int)
    ]


def test_column_reflow_preserves_disc_order_identity_and_selection(
    context: AppContext,
) -> None:
    panel = _panel(context, 1200)
    view = panel.track_view
    assert view.model().columnCount() == 2
    assert _ids(panel) == list(range(1, 18))
    view.setCurrentIndex(view.model().index(1, 1))
    selected = panel.selected_tracks()
    assert tuple(track.track_id for track in selected) == (11,)
    cover = panel.findChild(ArtworkView)
    assert cover is not None and cover.x() > view.geometry().right()
    panel.resize(420, panel.preferred_height(420))
    APPLICATION.processEvents()
    assert view.model().columnCount() == 1
    assert _ids(panel) == list(range(1, 18))
    assert panel.selected_tracks() == selected
    assert view.currentIndex().data(TrackRole.TRACK_ID) == 11
    assert view.geometry().right() <= panel.width()
    assert cover.geometry().bottom() <= view.y()
    assert view.verticalScrollBar().maximum() > 0
    panel.close()


def test_activation_selection_and_escape_use_existing_track_identities(
    context: AppContext,
) -> None:
    panel = _panel(context, 1100)
    view = panel.track_view
    current = QSignalSpy(panel.currentTrackChanged)
    activated = QSignalSpy(panel.trackActivated)
    double_clicked = QSignalSpy(view.doubleClicked)
    closed = QSignalSpy(panel.closeRequested)
    index = view.model().index(2, 0)
    view.setCurrentIndex(index)
    assert current.count() == 1 and current.at(0)[0].track_id == 3
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert activated.count() == 1 and activated.at(0)[0].track_id == 3
    assert double_clicked.count() == 1
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert closed.count() == 1
    assert view.model().flags(view.model().index(8, 1)) == Qt.ItemFlag.NoItemFlags
    assert view.model().data(QModelIndex(), TrackRole.TRACK) is None
    panel.close()


def test_album_and_tracks_have_no_hover_tooltips(context: AppContext) -> None:
    panel = _panel(context, 1100)
    try:
        labels = panel.findChildren(QLabel)
        assert len(labels) == 2
        assert all(label.toolTip() == "" for label in labels)
        assert all(label.accessibleName() for label in labels)
        assert panel.track_view.toolTip() == ""
        index = panel.track_view.model().index(0, 0)
        assert index.data(Qt.ItemDataRole.ToolTipRole) is None
        assert "Song 1" in str(index.data(Qt.ItemDataRole.AccessibleTextRole))
        # Resizing and retranslation must not restore the removed tooltips.
        panel.resize(420, panel.preferred_height(420))
        panel.retranslate_ui()
        assert all(label.toolTip() == "" for label in labels)
    finally:
        panel.close()


@pytest.mark.parametrize("width", (420, 660, 1100))
def test_album_buttons_stay_above_artwork_and_clear_of_labels(
    context: AppContext, width: int
) -> None:
    panel = _panel(context, width)
    try:
        cover = panel.findChild(ArtworkView)
        assert cover is not None
        previous_right = 0
        for name in ("inlineAlbumPlay", "inlineAlbumPlayNext", "inlineAlbumQueue"):
            button = panel.findChild(QToolButton, name)
            assert button is not None
            assert not button.icon().isNull() and button.text() == ""
            assert button.accessibleName() and button.toolTip()
            assert button.geometry().bottom() < cover.geometry().top()
            assert button.x() > previous_right
            previous_right = button.geometry().right()
            assert panel.rect().contains(button.geometry())
            assert all(
                not button.geometry().intersects(label.geometry())
                for label in panel.findChildren(QLabel)
            )
        assert previous_right == cover.geometry().right()
        context.track_model.reset_tracks(())
        APPLICATION.processEvents()
        assert all(
            not button.isEnabled()
            for button in panel.findChildren(QToolButton)
            if button.objectName() != "inlineAlbumClose"
        )
    finally:
        panel.close()


def test_inline_controls_use_positive_point_sizes_for_native_qt(
    context: AppContext,
) -> None:
    panel = _panel(context, 1100)
    try:
        close = panel.findChild(QToolButton, "inlineAlbumClose")
        assert close is not None
        controls = (close, panel.track_view, *panel.findChildren(QLabel))
        for control in controls:
            assert control.font().pointSizeF() > 0, (
                f"{control.objectName()} exposes invalid point size "
                f"{control.font().pointSizeF()} to native Qt"
            )
        panel.resize(420, panel.preferred_height(420))
        panel.retranslate_ui()
        assert close.font().pointSizeF() > 0
    finally:
        panel.close()


@pytest.mark.parametrize(
    "color",
    [
        (15, 86, 81),
        (245, 230, 161),
        (0, 0, 0),
        (255, 255, 255),
        (100, 216, 0),
        (255, 0, 255),
        (255, 0, 0),
        (0, 0, 255),
    ],
)
@pytest.mark.parametrize("mode", (AppearanceMode.LIGHT, AppearanceMode.DARK))
def test_artwork_color_is_opaque_and_text_keeps_contrast(
    context: AppContext,
    monkeypatch: pytest.MonkeyPatch,
    color: tuple[int, int, int],
    mode: AppearanceMode,
) -> None:
    context.theme_manager.set_mode(mode)
    panel = _panel(context, 1100)
    provider = panel.findChild(ArtworkPixmapProvider)
    assert provider is not None

    def dominant_color(
        _artwork_id: int, _logical_size: int, _device_pixel_ratio: float
    ) -> tuple[int, int, int]:
        return color

    monkeypatch.setattr(provider, "dominant_color", dominant_color)
    provider.cleared.emit()
    APPLICATION.processEvents()
    rendered = panel.grab().toImage()
    fill = rendered.pixelColor(panel.width() // 2, panel.height() - 4)
    tokens = context.theme_manager.tokens
    assert fill == colorful_card_fill(color, tokens, emphasized=True)
    assert fill != QColor(*color) and fill.alpha() == 255
    assert panel.ink == QColor(tokens.text)
    assert _contrast(fill, panel.ink) >= 4.5
    assert _contrast(fill, QColor(tokens.text_secondary)) >= 4.5
    panel.close()


def _contrast(first: QColor, second: QColor) -> float:
    def luminance(color: QColor) -> float:
        channels = tuple(
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in (color.redF(), color.greenF(), color.blueF())
        )
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    values = (luminance(first), luminance(second))
    return (max(values) + 0.05) / (min(values) + 0.05)
