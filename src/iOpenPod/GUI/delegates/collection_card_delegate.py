# Hallmark · component: collection grid card · genre: modern-minimal
# theme: iOpenPod · states: default · hover · focus · selected
# contrast: pass (40-41) · slop: pass (applicable gates)
# pre-emit critique: P5 H4 E5 S4 R5 V4
"""Shared collection cards with collages or a single TV Show cover."""

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

from iOpenPod.app.models.collection_list_model import (
    CollectionKind,
    CollectionRole,
    CollectionSummary,
)
from iOpenPod.GUI.presentation.artwork import (
    paint_artwork_collage,
    paint_artwork_pixmap,
    paint_artwork_placeholder,
)
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.collection_text import collection_summary_text
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


class CollectionCardDelegate(QStyledItemDelegate):
    """Paint collection artwork and captions on demand."""

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
        summary = index.data(CollectionRole.SUMMARY)
        if not isinstance(summary, CollectionSummary):
            return

        dpr = option.widget.devicePixelRatioF()
        tint = (
            self._artwork_provider.dominant_color(
                summary.representative_artwork_id,
                LAYOUT.album_artwork_size
                if summary.kind is CollectionKind.TV_SHOW
                else LAYOUT.album_artwork_size // 2,
                dpr,
            )
            if self._theme_manager.colorful_mode
            else None
        )

        paint_library_card(
            painter,
            option,
            title=str(index.data())
            or QCoreApplication.translate("LibraryLabels", "Unknown Collection"),
            detail=collection_summary_text(summary),
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
                on_ipod=index.data(CollectionRole.ON_IPOD),
            )

    def _paint_artwork(
        self,
        painter: QPainter,
        rect: QRectF,
        summary: CollectionSummary,
        dpr: float,
    ) -> None:
        tokens = self._theme_manager.tokens
        if summary.kind is not CollectionKind.TV_SHOW:
            paint_artwork_collage(
                painter,
                rect,
                summary.artwork_ids,
                summary.artwork_seed,
                tokens,
                self._artwork_provider,
                dpr,
            )
            return
        pixmap = self._artwork_provider.pixmap(
            summary.representative_artwork_id, round(rect.width()), dpr
        )
        if pixmap is None:
            paint_artwork_placeholder(
                painter,
                rect,
                summary.artwork_seed,
                tokens,
                float(LAYOUT.radius_control),
            )
        else:
            paint_artwork_pixmap(
                painter, rect, pixmap, tokens, float(LAYOUT.radius_control)
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


__all__ = ["CollectionCardDelegate"]
