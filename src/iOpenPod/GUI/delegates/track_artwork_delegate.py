"""Reduced, lazily requested artwork cells for the Track table."""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from iOpenPod.app.models.track_table_model import TrackRole
from iOpenPod.GUI.presentation.artwork import (
    paint_artwork_pixmap,
    paint_artwork_placeholder,
)
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class TrackArtworkDelegate(QStyledItemDelegate):
    """Paint one visible Track thumbnail without creating a per-row widget."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        styled.text = ""
        widget = option.widget
        widget.style().drawControl(
            QStyle.ControlElement.CE_ItemViewItem,
            styled,
            painter,
            widget,
        )

        artwork_id = index.data(TrackRole.ARTWORK_ID)
        seed = index.data(TrackRole.ARTWORK_SEED)
        if not isinstance(artwork_id, int):
            artwork_id = 0
        if not isinstance(seed, int):
            seed = 0

        size = min(
            LAYOUT.track_artwork_size,
            max(0, option.rect.width() - (2 * LAYOUT.space_2xs)),
            max(0, option.rect.height() - (2 * LAYOUT.space_2xs)),
        )
        if size <= 0:
            return
        artwork_rect = QRectF(
            option.rect.center().x() - (size / 2.0),
            option.rect.center().y() - (size / 2.0),
            size,
            size,
        )
        # Cache the queue/drag-card size while the row is visible, then scale it
        # down here. A later drag can reuse the exact request without upscaling.
        pixmap = self._artwork_provider.pixmap(
            artwork_id,
            LAYOUT.playback_row_artwork_size,
            widget.devicePixelRatioF(),
        )
        if pixmap is None:
            paint_artwork_placeholder(
                painter,
                artwork_rect,
                seed,
                self._theme_manager.tokens,
                3.0,
            )
            return
        paint_artwork_pixmap(
            painter,
            artwork_rect,
            pixmap,
            self._theme_manager.tokens,
            3.0,
        )


__all__ = ["TrackArtworkDelegate"]
