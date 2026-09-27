"""Collection cards for managing selected-Photo album membership."""

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRectF,
    QSize,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from iOpenPod.app.models.photo_album_membership_model import (
    PhotoAlbumMembershipRole,
    PhotoAlbumMembershipSummary,
)
from iOpenPod.GUI.presentation.artwork import paint_artwork_placeholder
from iOpenPod.GUI.presentation.i18n.text import photo_count_text
from iOpenPod.GUI.presentation.library_card import (
    library_card_size,
    paint_library_card,
)
from iOpenPod.GUI.presentation.photo import paint_photo_pixmap
from iOpenPod.GUI.presentation.photo_provider import PhotoPixmapProvider
from iOpenPod.GUI.presentation.selection_checkbox import (
    handle_library_card_check_event,
    library_card_checkbox_rect,
    paint_library_card_checkbox,
)
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT, TypographyTokens


def photo_album_checkbox_rect(
    option: QStyleOptionViewItem,
    typography: TypographyTokens,
) -> QRectF:
    """Place the circular membership control over the collage's top-right."""

    return library_card_checkbox_rect(option, typography)


class PhotoAlbumMembershipDelegate(QStyledItemDelegate):
    """Paint four-Photo album collages with an overlaid circular checkbox."""

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
        summary = index.data(PhotoAlbumMembershipRole.SUMMARY)
        if not isinstance(summary, PhotoAlbumMembershipSummary):
            return
        count = summary.photo_count
        detail = photo_count_text(count)
        card_option = QStyleOptionViewItem(option)
        card_option.state = option.state & ~QStyle.StateFlag.State_HasFocus
        paint_library_card(
            painter,
            card_option,
            title=summary.name,
            detail=detail,
            tint=None,
            tokens=self._theme_manager.tokens,
            typography=self._theme_manager.typography,
            paint_artwork=lambda rect: self._paint_collage(
                painter,
                option,
                rect,
                summary,
            ),
        )
        paint_library_card_checkbox(
            painter,
            option,
            summary.check_state,
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
            checkbox_only=False,
        )

    def _paint_collage(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        rect: QRectF,
        summary: PhotoAlbumMembershipSummary,
    ) -> None:
        gap = float(LAYOUT.space_2xs)
        tile_size = (rect.width() - gap) / 2.0
        dpr = option.widget.devicePixelRatioF()
        for position, photo_id in enumerate(summary.preview_photo_ids):
            column = position % 2
            row = position // 2
            tile_rect = QRectF(
                rect.left() + column * (tile_size + gap),
                rect.top() + row * (tile_size + gap),
                tile_size,
                tile_size,
            )
            if photo_id <= 0:
                painter.setPen(QPen(QColor(self._theme_manager.tokens.border)))
                painter.setBrush(QColor(self._theme_manager.tokens.surface_alt))
                painter.drawRoundedRect(tile_rect, 2.0, 2.0)
                continue
            pixmap = self._photo_provider.pixmap(
                photo_id,
                round(tile_size),
                dpr,
            )
            if pixmap is None:
                paint_artwork_placeholder(
                    painter,
                    tile_rect,
                    photo_id,
                    self._theme_manager.tokens,
                    2.0,
                )
            else:
                paint_photo_pixmap(
                    painter,
                    tile_rect,
                    pixmap,
                    self._theme_manager.tokens,
                    2.0,
                )


__all__ = ["PhotoAlbumMembershipDelegate", "photo_album_checkbox_rect"]
