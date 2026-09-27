"""Delegate-backed cards for the virtualized Photo grid."""

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

from iOpenPod.app.models.photo_list_model import PhotoRole
from iOpenPod.GUI.presentation.artwork import paint_artwork_placeholder
from iOpenPod.GUI.presentation.library_card import (
    library_card_size,
    paint_library_card,
)
from iOpenPod.GUI.presentation.photo import paint_photo_pixmap
from iOpenPod.GUI.presentation.photo_provider import PhotoPixmapProvider
from iOpenPod.GUI.presentation.selection_checkbox import (
    handle_library_card_check_event,
    paint_library_card_checkbox,
)
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iPodDB.library import Photo


class PhotoCardDelegate(QStyledItemDelegate):
    """Paint Photo cards on demand without allocating one widget per Photo."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        photo_provider: PhotoPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._photo_provider = photo_provider

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
        photo = index.data(PhotoRole.PHOTO)
        if not isinstance(photo, Photo):
            return
        title = QCoreApplication.translate("LibraryLabels", "Photo %1").replace(
            "%1", str(photo.photo_id)
        )
        count = len(photo.representations)
        detail = (
            self.tr("%n format", None, count)
            if count == 1
            else self.tr("%n formats", None, count)
        )
        dpr = option.widget.devicePixelRatioF()
        paint_library_card(
            painter,
            option,
            title=title,
            detail=detail,
            tint=None,
            tokens=self._theme_manager.tokens,
            typography=self._theme_manager.typography,
            paint_artwork=lambda rect: self._paint_photo(
                painter,
                rect,
                photo.photo_id,
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

    def _paint_photo(
        self,
        painter: QPainter,
        rect: QRectF,
        photo_id: int,
        device_pixel_ratio: float,
    ) -> None:
        pixmap = self._photo_provider.pixmap(
            photo_id,
            round(rect.width()),
            device_pixel_ratio,
        )
        if pixmap is None:
            paint_artwork_placeholder(
                painter,
                rect,
                photo_id,
                self._theme_manager.tokens,
                float(LAYOUT.radius_control),
            )
            return
        paint_photo_pixmap(
            painter,
            rect,
            pixmap,
            self._theme_manager.tokens,
            float(LAYOUT.radius_control),
        )


__all__ = ["PhotoCardDelegate"]
