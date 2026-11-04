# Hallmark · component: TV season details · theme: iOpenPod / artwork
# pre-emit critique: P5 H4 E4 S5 R5 V4 · contrast: shared theme tokens
"""Season-scoped TV episodes inside the shared expanding Library card row."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QCoreApplication,
    QDate,
    QLocale,
    QModelIndex,
    QPointF,
    QRect,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTabBar

from iOpenPod.app.models.track_columns import TrackColumn, track_column_display_value
from iOpenPod.app.models.track_table_model import TrackRole
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.inline_album_panel import InlineAlbumPanel
from iPodDB.library import Track

if TYPE_CHECKING:
    from PySide6.QtCore import QPersistentModelIndex
    from PySide6.QtWidgets import QWidget

    from iOpenPod.app.models.album_list_model import AlbumSummary
    from iOpenPod.app.models.collection_list_model import CollectionSummary
    from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager


def _episode_label(track: Track) -> str:
    number = track.episode_number or track.track_number
    return (
        QCoreApplication.translate("InlineTVShowPanel", "Episode %1").replace(
            "%1", str(number)
        )
        if number > 0
        else QCoreApplication.translate("InlineTVShowPanel", "Episode")
    )


def _release_date(track: Track) -> str:
    if track.metadata.release_date <= 0:
        return "—"
    try:
        date = datetime.fromtimestamp(track.metadata.release_date, UTC)
    except (OSError, OverflowError, ValueError):
        return "—"
    return QLocale().toString(QDate(date.year, date.month, date.day), "ddd, d MMM yyyy")


def _episode_accessible_text(track: Track) -> str:
    return ", ".join(
        (
            _episode_label(track),
            _release_date(track),
            track_column_display_value(track, TrackColumn.TIME),
            track_column_display_value(track, TrackColumn.TITLE),
        )
    )


def _episode_heading_font(body_font: QFont) -> QFont:
    font = QFont(body_font)
    font.setPointSizeF(body_font.pointSizeF() + 1.0)
    font.setWeight(QFont.Weight.Bold)
    return font


def _paint_description(painter: QPainter, rect: QRect, text: str) -> None:
    """Wrap at most two lines and elide the remaining plain text."""
    text = " ".join(text.split())
    layout = QTextLayout(text, painter.font())
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    metrics = painter.fontMetrics()
    layout.beginLayout()
    for row in range(2):
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(rect.width())
        y = rect.top() + row * metrics.lineSpacing()
        if row == 0:
            line.draw(painter, QPointF(rect.left(), y))
        else:
            # QTextLayout positions are UTF-16 offsets, including non-BMP titles.
            remaining = text.encode("utf-16-le")[2 * line.textStart() :].decode(
                "utf-16-le"
            )
            painter.drawText(
                rect.left(),
                y + metrics.ascent(),
                metrics.elidedText(
                    remaining, Qt.TextElideMode.ElideRight, rect.width()
                ),
            )
    layout.endLayout()


class _EpisodeDelegate(QStyledItemDelegate):
    def __init__(self, panel: InlineTVShowPanel) -> None:
        super().__init__(panel)
        self._panel = panel

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        track = index.data(TrackRole.TRACK)
        if not isinstance(track, Track):
            return
        painter.save()
        painter.setClipRect(option.rect)
        rect = option.rect.adjusted(
            LAYOUT.space_sm, LAYOUT.space_sm, -LAYOUT.space_sm, -LAYOUT.space_sm
        )
        ink = self._panel.ink
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected or option.state & QStyle.StateFlag.State_MouseOver:
            highlight = QColor(ink)
            highlight.setAlpha(42 if selected else 20)
            painter.fillRect(option.rect, highlight)
        painter.setPen(ink)
        line_height = option.fontMetrics.lineSpacing()
        metadata_width = min(
            max(120, option.fontMetrics.horizontalAdvance("Wed, 30 Sep 2000")),
            rect.width() // 3,
        )
        title_left = rect.left() + metadata_width + LAYOUT.space_lg
        title_width = max(1, rect.right() - title_left)
        bold = _episode_heading_font(option.font)
        heading_metrics = QFontMetrics(bold)
        heading_height = heading_metrics.lineSpacing()
        painter.setFont(bold)
        for left, width, text in (
            (rect.left(), metadata_width, _episode_label(track)),
            (
                title_left,
                title_width,
                track_column_display_value(track, TrackColumn.TITLE),
            ),
        ):
            painter.drawText(
                QRect(left, rect.top(), width, heading_height),
                Qt.AlignmentFlag.AlignLeft,
                heading_metrics.elidedText(text, Qt.TextElideMode.ElideRight, width),
            )
        painter.setFont(option.font)
        for row, text in enumerate(
            (_release_date(track), track_column_display_value(track, TrackColumn.TIME)),
        ):
            painter.drawText(
                QRect(
                    rect.left(),
                    rect.top() + heading_height + row * line_height,
                    metadata_width,
                    line_height,
                ),
                Qt.AlignmentFlag.AlignLeft,
                option.fontMetrics.elidedText(
                    text, Qt.TextElideMode.ElideRight, metadata_width
                ),
            )
        _paint_description(
            painter,
            QRect(
                title_left, rect.top() + heading_height, title_width, 2 * line_height
            ),
            track.metadata.description,
        )
        if option.state & QStyle.StateFlag.State_HasFocus:
            pen = QPen(ink)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(option.rect.adjusted(1, 1, -1, -1))
        painter.restore()


class InlineTVShowPanel(InlineAlbumPanel):
    """Keep one show's seasons local to its open detail panel."""

    def __init__(
        self,
        proxy: TrackFilterProxyModel,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        self._show_tracks: tuple[Track, ...] = ()
        self._season: int | None = None
        self._seasons: tuple[int, ...] = ()
        super().__init__(proxy, theme_manager, artwork_provider, parent)
        self.setObjectName("inlineTVShowPanel")
        self._tracks.setObjectName("inlineTVEpisodes")
        self._tracks.setItemDelegate(_EpisodeDelegate(self))
        self._model.show_rating = False
        self._model.accessible_text = _episode_accessible_text
        self._tabs = QTabBar(self)
        self._tabs.setObjectName("tvSeasonTabs")
        self._tabs.setExpanding(False)
        self._tabs.setDrawBase(False)
        self._tabs.setUsesScrollButtons(True)
        self._tabs.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._tabs.installEventFilter(self)
        self._tabs.currentChanged.connect(self._season_changed)
        self.retranslate_ui()
        self._refresh_colors()

    @property
    def artwork_id(self) -> int:
        return (
            next(
                (
                    track.artwork_id
                    for track in self._model.tracks
                    if track.artwork_id > 0
                ),
                0,
            )
            if hasattr(self, "_model")
            else 0
        )

    @property
    def row_height(self) -> int:
        return (
            QFontMetrics(_episode_heading_font(self._tracks.font())).lineSpacing()
            + 2 * self._tracks.fontMetrics().lineSpacing()
            + 2 * LAYOUT.space_md
        )

    def set_context(
        self,
        summary: AlbumSummary | CollectionSummary,
        tracks: tuple[Track, ...] | None = None,
    ) -> None:
        if self._summary is None or self._summary.key != summary.key:
            self._season = None
        super().set_context(summary, tracks)

    def _set_context_tracks(self, tracks: tuple[Track, ...]) -> None:
        self._show_tracks = tuple(
            sorted(
                tracks,
                key=lambda t: (
                    t.season_number,
                    t.episode_number or t.track_number,
                    t.metadata.release_date,
                    t.title.casefold(),
                    t.track_id,
                ),
            )
        )
        seasons = tuple(sorted({track.season_number for track in tracks}))
        if self._season not in seasons:
            self._season = seasons[0] if seasons else None
        if seasons != self._seasons:
            self._seasons = seasons
            self._tabs.blockSignals(True)
            while self._tabs.count():
                self._tabs.removeTab(0)
            for season in seasons:
                index = self._tabs.addTab(self._season_label(season))
                self._tabs.setTabData(index, season)
            self._tabs.blockSignals(False)
        self._tabs.setCurrentIndex(
            seasons.index(self._season) if self._season is not None else -1
        )
        self._show_season()

    def _season_label(self, season: int) -> str:
        return (
            self.tr("Season %1").replace("%1", str(season))
            if season > 0
            else self.tr("Unknown season")
        )

    def _season_changed(self, index: int) -> None:
        value = self._tabs.tabData(index)
        self._season = value if isinstance(value, int) else None
        self._show_season()

    def _show_season(self) -> None:
        self._replace_tracks(
            tuple(t for t in self._show_tracks if t.season_number == self._season), 1
        )
        self._cover.set_artwork_id(self.artwork_id)
        self._tracks.verticalScrollBar().setValue(0)
        self._refresh_colors()
        self.preferredHeightChanged.emit()

    def _context_title(self) -> str:
        return (
            self._summary.title if self._summary is not None else ""
        ) or QCoreApplication.translate("LibraryLabels", "Unknown Show")

    def _context_subtitle(self) -> str:
        if self._season is None:
            return ""
        label = self._season_label(self._season)
        year = next((track.year for track in self._model.tracks if track.year > 0), 0)
        return f"{label} ({year})" if year else label

    def _dimensions(self, width: int) -> tuple[int, int, int, bool]:
        track_width, _, cover, compact = super()._dimensions(width)
        return track_width, 1, cover, compact

    def _tab_height(self) -> int:
        return (
            max(LAYOUT.control_height_compact, self._tabs.sizeHint().height())
            if hasattr(self, "_tabs")
            else LAYOUT.control_height_compact
        )

    def _body_top(self, compact: bool) -> int:
        return super()._body_top(compact) + self._tab_height() + LAYOUT.space_sm

    def preferred_height(self, width: int) -> int:
        _, _, cover, compact = self._dimensions(width)
        body = max(1, min(6, len(self._model.tracks))) * self.row_height
        return (
            self._body_top(compact)
            + max(body, 0 if compact else cover)
            + LAYOUT.space_lg
        )

    def _arrange(self) -> None:
        super()._arrange()
        if not hasattr(self, "_tabs"):
            return
        top = self._title.y()
        offset = self._tab_height() + LAYOUT.space_sm
        self._tabs.setGeometry(
            LAYOUT.space_2xl,
            top,
            max(1, self.width() - LAYOUT.space_2xl - LAYOUT.space_lg),
            self._tab_height(),
        )
        for widget in (
            self._title,
            self._artist,
            self._play,
            self._play_next,
            self._queue,
        ):
            widget.move(widget.x(), widget.y() + offset)
        if self._dimensions(self.width())[3]:
            self._cover.move(self._cover.x(), self._cover.y() + offset)

    def retranslate_ui(self) -> None:
        super().retranslate_ui()
        self._close.setAccessibleName(self.tr("Close show"))
        self._close.setToolTip(self.tr("Close show"))
        self._tracks.setAccessibleName(self.tr("Season episodes"))
        for button, text in (
            (self._play, self.tr("Play season now")),
            (self._play_next, self.tr("Add season to top of queue")),
            (self._queue, self.tr("Add season to bottom of queue")),
        ):
            button.setAccessibleName(text)
            button.setToolTip(text)
        if hasattr(self, "_tabs"):
            self._tabs.setAccessibleName(self.tr("Seasons"))
            for index, season in enumerate(self._seasons):
                self._tabs.setTabText(index, self._season_label(season))
            self._arrange()

    def _refresh_colors(self, *_args: object) -> None:
        super()._refresh_colors()
        if hasattr(self, "_tabs"):
            rgb = f"{self.ink.red()}, {self.ink.green()}, {self.ink.blue()}"
            self._tabs.setStyleSheet(
                f"QTabBar {{ background: transparent; }} QTabBar::tab {{ min-width: 0; min-height: 0; color: {self.ink.name()}; background: transparent; border: 1px solid transparent; border-radius: {LAYOUT.control_height_compact // 2}px; padding: {LAYOUT.space_xs}px {LAYOUT.space_md}px; margin-right: {LAYOUT.space_xs}px; font-weight: 700; }}"
                f"QTabBar::tab:hover {{ background: rgba({rgb}, 20); }} QTabBar::tab:selected {{ background: rgba({rgb}, 42); }} QTabBar::tab:selected:focus {{ border-color: {self.ink.name()}; border-style: dashed; }}"
            )
            self._arrange()


__all__ = ["InlineTVShowPanel"]
