"""Delegate-backed album cards for the virtualized library grid."""

from PySide6.QtCore import (
    QAbstractItemModel,
    QCoreApplication,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QWidget

from iOpenPod.app.models.album_list_model import AlbumRole, AlbumSummary
from iOpenPod.GUI.presentation.artwork import (
    paint_artwork_pixmap,
    paint_artwork_placeholder,
)
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.i18n.text import track_count_text
from iOpenPod.GUI.presentation.library_card import (
    library_card_size,
    paint_library_card,
)
from iOpenPod.GUI.presentation.selection_checkbox import (
    handle_library_card_check_event,
    paint_library_card_checkbox,
)
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class AlbumCardDelegate(QStyledItemDelegate):
    """Paint album cards on demand; never create a child widget per album."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        _index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return library_card_size(option.font, self._theme_manager.typography)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        summary = index.data(AlbumRole.SUMMARY)
        if not isinstance(summary, AlbumSummary):
            return

        dpr = option.widget.devicePixelRatioF()
        tint = (
            self._artwork_provider.dominant_color(
                summary.artwork_id,
                LAYOUT.album_artwork_size,
                dpr,
            )
            if self._theme_manager.colorful_mode
            else None
        )

        paint_library_card(
            painter,
            option,
            title=summary.title
            or QCoreApplication.translate("LibraryLabels", "Unknown Album"),
            detail=self._detail_text(summary),
            tint=tint,
            tokens=self._theme_manager.tokens,
            typography=self._theme_manager.typography,
            paint_artwork=lambda rect: self._paint_artwork(
                painter,
                rect,
                summary,
                dpr,
            ),
        )
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        if isinstance(state, Qt.CheckState):
            paint_library_card_checkbox(
                painter,
                option,
                state,
                self._theme_manager.tokens,
                self._theme_manager.typography,
            )

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        return handle_library_card_check_event(
            event,
            model,
            option,
            index,
            self._theme_manager.typography,
        )

    def _paint_artwork(
        self,
        painter: QPainter,
        rect: QRectF,
        summary: AlbumSummary,
        device_pixel_ratio: float,
    ) -> None:
        tokens = self._theme_manager.tokens
        pixmap = self._artwork_provider.pixmap(
            summary.artwork_id,
            round(rect.width()),
            device_pixel_ratio,
        )
        if pixmap is None:
            paint_artwork_placeholder(
                painter,
                rect,
                summary.artwork_seed,
                tokens,
                float(LAYOUT.radius_control),
            )
            return
        paint_artwork_pixmap(
            painter,
            rect,
            pixmap,
            tokens,
            float(LAYOUT.radius_control),
        )

    def _detail_text(self, summary: AlbumSummary) -> str:
        artist = summary.artist or QCoreApplication.translate(
            "LibraryLabels", "Unknown Artist"
        )
        parts = [artist]
        if summary.year > 0:
            parts.append(str(summary.year))
        parts.append(track_count_text(summary.track_count))
        return " · ".join(parts)
