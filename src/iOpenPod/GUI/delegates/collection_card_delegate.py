# Hallmark · component: collection grid card · genre: modern-minimal
# theme: iOpenPod · states: default · hover · focus · selected
# contrast: pass (40-41) · slop: pass (applicable gates)
# pre-emit critique: P5 H4 E5 S4 R5 V4
"""Delegate-backed collection cards with deterministic four-tile artwork."""

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QSize,
    Qt,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QWidget

from iOpenPod.app.models.collection_list_model import (
    CollectionRole,
    CollectionSummary,
)
from iOpenPod.GUI.presentation.artwork import paint_artwork_collage
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
    """Paint a collection card and its fixed 2-by-2 collage on demand."""

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
                LAYOUT.album_artwork_size // 2,
                dpr,
            )
            if self._theme_manager.colorful_mode
            else None
        )

        paint_library_card(
            painter,
            option,
            title=str(index.data()) or self.tr("Unknown Collection"),
            detail=collection_summary_text(summary),
            tint=tint,
            tokens=self._theme_manager.tokens,
            typography=self._theme_manager.typography,
            paint_artwork=lambda rect: paint_artwork_collage(
                painter,
                rect,
                summary.artwork_ids,
                summary.artwork_seed,
                self._theme_manager.tokens,
                self._artwork_provider,
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


__all__ = ["CollectionCardDelegate"]
