"""Artwork and title cards for individual Tracks."""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QWidget

from iOpenPod.app.models.track_table_model import TrackRole
from iOpenPod.GUI.presentation.artwork import (
    paint_artwork_pixmap,
    paint_artwork_placeholder,
)
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.library_card import library_card_size, paint_library_card
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iPodDB.library import Track


class TrackCardDelegate(QStyledItemDelegate):
    """Reuse Library card states without secondary metadata or inline details."""

    def __init__(
        self,
        theme: ThemeManager,
        artwork: ArtworkPixmapProvider,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._artwork = artwork

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        _index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return library_card_size(option.font, self._theme.typography)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        track = index.data(TrackRole.TRACK)
        if not isinstance(track, Track):
            return
        ratio = option.widget.devicePixelRatioF()
        seed = index.data(TrackRole.ARTWORK_SEED)

        def paint_artwork(rect: QRectF) -> None:
            pixmap = self._artwork.pixmap(track.artwork_id, round(rect.width()), ratio)
            if pixmap is None:
                paint_artwork_placeholder(
                    painter,
                    rect,
                    seed if isinstance(seed, int) else 0,
                    self._theme.tokens,
                    float(LAYOUT.radius_control),
                )
            else:
                paint_artwork_pixmap(
                    painter,
                    rect,
                    pixmap,
                    self._theme.tokens,
                    float(LAYOUT.radius_control),
                )

        paint_library_card(
            painter,
            option,
            title=str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
            detail="",
            tint=(
                self._artwork.dominant_color(
                    track.artwork_id, LAYOUT.album_artwork_size, ratio
                )
                if self._theme.colorful_mode
                else None
            ),
            tokens=self._theme.tokens,
            typography=self._theme.typography,
            paint_artwork=paint_artwork,
        )
