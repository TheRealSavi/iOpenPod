"""An accessible native month calendar with bounded, painted event previews."""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import (
    QDate,
    QEasingCurve,
    QEvent,
    QLocale,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QFont,
    QFontMetrics,
    QHideEvent,
    QPainter,
    QPalette,
    QPen,
    QResizeEvent,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStyle,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    IconButton,
    IconButtonKind,
)


@dataclass(frozen=True, slots=True)
class CalendarMarker:
    """An inclusive display range; recurrence expansion belongs to no widget."""

    first: QDate
    last: QDate
    title: str


class MonthGrid(QCalendarWidget):
    """Retain Qt keyboard navigation and date accessibility while painting previews."""

    def __init__(self, parent: QWidget | None = None, *, today: QDate) -> None:
        super().__init__(parent)
        self._calendar_view = self.findChild(QTableView, "qt_calendar_calendarview")
        self.setObjectName("calendarMonthGrid")
        self.setNavigationBarVisible(False)
        self.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self.setHorizontalHeaderFormat(
            QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
        )
        if self._calendar_view is not None:
            # Qt models the weekday headings as the first row of the date table.
            self._calendar_view.verticalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.Fixed
            )
            self._resize_weekday_row()
        self.setFirstDayOfWeek(QLocale().firstDayOfWeek())
        self.setDateRange(QDate(100, 1, 1), QDate(9999, 12, 31))
        self._markers: tuple[CalendarMarker, ...] = ()
        self._labels: dict[int, list[str]] = {}
        self._today = today
        self.setSelectedDate(today)
        self._selection_weights = {today.toJulianDay(): 1.0}
        self._selection_from = self._selection_weights.copy()
        self._selection_target = today.toJulianDay()
        self._selection_fade = QVariantAnimation(self)
        self._selection_fade.setObjectName("calendarDaySelectionFade")
        self._selection_fade.setDuration(LAYOUT.selection_group_animation_ms)
        self._selection_fade.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._selection_fade.setStartValue(0.0)
        self._selection_fade.setEndValue(1.0)
        self._selection_fade.valueChanged.connect(self._advance_selection)
        self._selection_fade.finished.connect(self._finish_selection)
        self.selectionChanged.connect(self._selection_changed)
        self.currentPageChanged.connect(self._index_month)
        self._refresh_header()

    def sizeHint(self) -> QSize:
        return QSize(640, 480)

    def minimumSizeHint(self) -> QSize:
        return QSize(280, 280)

    def set_markers(self, markers: tuple[CalendarMarker, ...]) -> None:
        self._markers = markers
        self._index_month()

    def set_today(self, today: QDate) -> None:
        self._today = today
        self.updateCells()

    def _selection_changed(self) -> None:
        self._selection_fade.stop()
        if not self.isVisible() or not self.style().styleHint(
            QStyle.StyleHint.SH_Widget_Animate, None, self
        ):
            self._finish_selection()
            return
        # Retarget from every currently visible highlight, including a partly
        # faded date, so repeated clicks and keyboard steps never flash.
        self._selection_from = self._selection_weights.copy()
        self._selection_target = self.selectedDate().toJulianDay()
        self._selection_fade.start()

    def _advance_selection(self, value: object) -> None:
        if not isinstance(value, (int, float)):
            return
        progress = float(value)
        self._selection_weights = {
            day: weight * (1.0 - progress)
            for day, weight in self._selection_from.items()
        }
        self._selection_weights[self._selection_target] = (
            self._selection_weights.get(self._selection_target, 0.0) + progress
        )
        for day in self._selection_weights:
            self.updateCell(QDate.fromJulianDay(day))

    def _finish_selection(self) -> None:
        self._selection_fade.stop()
        self._selection_weights = {self.selectedDate().toJulianDay(): 1.0}
        self._selection_from = self._selection_weights.copy()
        self.updateCells()

    def hideEvent(self, event: QHideEvent) -> None:
        self._finish_selection()
        super().hideEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._finish_selection()
        super().resizeEvent(event)

    def _index_month(self) -> None:
        first = QDate(self.yearShown(), self.monthShown(), 1)
        offset = (first.dayOfWeek() - self.firstDayOfWeek().value) % 7
        # Qt shows the preceding week when the month starts on the first weekday.
        first = first.addDays(-(offset or 7))
        last = first.addDays(41)
        self._labels = {}
        for marker in self._markers:
            day = max(first, marker.first)
            end = min(last, marker.last)
            while day <= end:
                self._labels.setdefault(day.toJulianDay(), []).append(marker.title)
                day = day.addDays(1)
        self.updateCells()

    def _refresh_header(self) -> None:
        header = QTextCharFormat()
        header.setForeground(
            QApplication.palette().brush(QPalette.ColorRole.PlaceholderText)
        )
        header.setBackground(self.palette().brush(QPalette.ColorRole.Base))
        header.setFontWeight(QFont.Weight.Medium)
        self.setHeaderTextFormat(header)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, header)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, header)

    def _resize_weekday_row(self) -> None:
        if self._calendar_view is not None:
            self._calendar_view.verticalHeader().resizeSection(
                0, self.fontMetrics().height() + 2 * LAYOUT.space_xs
            )

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.LanguageChange):
            self._refresh_header()
            self.updateCells()
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._resize_weekday_row()
        if hasattr(self, "_selection_fade") and event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.StyleChange,
            QEvent.Type.FontChange,
        ):
            self._finish_selection()

    def paintCell(self, painter: QPainter, rect: QRect, date: QDate) -> None:
        painter.save()
        painter.setClipRect(rect)
        palette = self.palette()
        secondary = QApplication.palette().color(QPalette.ColorRole.PlaceholderText)
        painter.fillRect(rect, palette.brush(QPalette.ColorRole.Base))
        selected = date == self.selectedDate()
        selection_weight = self._selection_weights.get(date.toJulianDay(), 0.0)
        current = date.month() == self.monthShown()
        accent = palette.color(QPalette.ColorRole.Link)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cell = QRectF(rect.adjusted(2, 2, -2, -2))
        painter.setPen(Qt.PenStyle.NoPen)
        if selection_weight:
            painter.setOpacity(selection_weight)
            painter.setBrush(palette.brush(QPalette.ColorRole.Highlight))
            painter.drawRoundedRect(cell, LAYOUT.radius_control, LAYOUT.radius_control)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(accent, 1.5))
            painter.drawRoundedRect(cell, LAYOUT.radius_control, LAYOUT.radius_control)
        if selection_weight < 1.0:
            painter.setOpacity(1.0 - selection_weight)
            painter.setPen(palette.color(QPalette.ColorRole.Mid))
            painter.drawLine(
                rect.bottomLeft() + QPoint(LAYOUT.space_2xs, 0),
                rect.bottomRight() - QPoint(LAYOUT.space_2xs, 0),
            )
        painter.setOpacity(1.0)
        font = QFont(self.font())
        font.setBold(selected or date == self._today)
        painter.setFont(font)
        height = QFontMetrics(font).height()
        badge = QRect(
            rect.x() + LAYOUT.space_xs,
            rect.y() + LAYOUT.space_xs,
            height + LAYOUT.space_sm,
            height + LAYOUT.space_xs,
        )
        if date == self._today:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(
                QRectF(badge), LAYOUT.radius_control, LAYOUT.radius_control
            )
            painter.setPen(
                QApplication.palette().color(QPalette.ColorRole.HighlightedText)
            )
        else:
            painter.setPen(
                palette.color(QPalette.ColorRole.Text) if current else secondary
            )
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(date.day()))
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            focus = self.focusProxy()
            if self.hasFocus() or (focus is not None and focus.hasFocus()):
                painter.setPen(QPen(accent, 1, Qt.PenStyle.DotLine))
                painter.drawRoundedRect(
                    cell.adjusted(3, 3, -3, -3),
                    LAYOUT.radius_control,
                    LAYOUT.radius_control,
                )
        labels = self._labels.get(date.toJulianDay(), [])
        line_height = height + LAYOUT.space_xs
        y = badge.bottom() + LAYOUT.space_xs
        available = max(
            0,
            (rect.bottom() - y - LAYOUT.space_2xs) // (line_height + LAYOUT.space_2xs),
        )
        if labels and (rect.width() < 70 or not available):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(rect.right() - 12, rect.top() + 12, 4, 4)
        else:
            font.setBold(False)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            for index, title in enumerate(labels[:available]):
                overflow = (
                    available > 1 and index == available - 1 and len(labels) > available
                )
                if overflow:
                    title = self.tr("+{count} more").format(count=len(labels) - index)
                line = QRect(
                    rect.x() + LAYOUT.space_xs,
                    y,
                    rect.width() - 2 * LAYOUT.space_xs,
                    line_height,
                )
                if not overflow:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(
                        QApplication.palette().brush(QPalette.ColorRole.AlternateBase)
                    )
                    painter.drawRoundedRect(
                        QRectF(line), LAYOUT.space_2xs, LAYOUT.space_2xs
                    )
                painter.setPen(
                    palette.color(QPalette.ColorRole.Text)
                    if current and not overflow
                    else secondary
                )
                text_rect = line.adjusted(LAYOUT.space_xs, 0, -LAYOUT.space_xs, 0)
                painter.drawText(
                    text_rect,
                    Qt.AlignmentFlag.AlignVCenter,
                    metrics.elidedText(
                        title, Qt.TextElideMode.ElideRight, text_rect.width()
                    ),
                )
                y += line_height + LAYOUT.space_2xs
            if available == 1 and len(labels) > 1:
                painter.setPen(accent)
                painter.drawText(
                    rect.adjusted(8, 8, -8, -8),
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                    f"+{len(labels) - 1}",
                )
        painter.restore()


class CalendarMonth(QFrame):
    """Shared month navigation, today action, and keyboard-selectable day grid."""

    selected = Signal()

    def __init__(
        self, parent: QWidget | None = None, *, today: Callable[[], QDate]
    ) -> None:
        super().__init__(parent)
        self.setObjectName("calendarMonth")
        self._current_date = today
        self.grid = MonthGrid(self, today=today())
        self._title = QLabel(self)
        self._title.setObjectName("calendarMonthTitle")
        self._previous = IconButton("chevron-left", "", self, kind=IconButtonKind.QUIET)
        self._next = IconButton("chevron-right", "", self, kind=IconButtonKind.QUIET)
        self._today = ActionButton(parent=self, kind=ActionButtonKind.SECONDARY)
        self._previous.setObjectName("calendarPreviousMonth")
        self._next.setObjectName("calendarNextMonth")
        self._today.setObjectName("calendarToday")
        for button in (self._previous, self._next):
            button.setFixedWidth(LAYOUT.control_height)
        bar = QHBoxLayout()
        bar.addWidget(self._title, 1)
        bar.addWidget(self._today)
        bar.addWidget(self._previous)
        bar.addWidget(self._next)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_md, LAYOUT.space_md, LAYOUT.space_md, LAYOUT.space_md
        )
        layout.setSpacing(LAYOUT.space_md)
        layout.addLayout(bar)
        layout.addWidget(self.grid, 1)
        self._previous.clicked.connect(self.grid.showPreviousMonth)
        self._next.clicked.connect(self.grid.showNextMonth)
        self._today.clicked.connect(self._select_today)
        self.grid.selectionChanged.connect(self.selected)
        self.grid.currentPageChanged.connect(self._page_changed)
        self._retranslate()

    def _page_changed(self, year: int, month: int) -> None:
        selected = self.grid.selectedDate()
        if (selected.year(), selected.month()) != (year, month):
            self.grid.setSelectedDate(QDate(year, month, 1))
        self._retranslate()

    def _select_today(self) -> None:
        today = self._current_date()
        self.grid.set_today(today)
        self.grid.setSelectedDate(today)
        self.grid.showSelectedDate()

    def _retranslate(self) -> None:
        date = QDate(self.grid.yearShown(), self.grid.monthShown(), 1)
        self._title.setText(QLocale().toString(date, "MMMM yyyy"))
        self._today.setText(self.tr("Today"))
        self._previous.setAccessibleName(self.tr("Previous month"))
        self._next.setAccessibleName(self.tr("Next month"))
        self._previous.setToolTip(self._previous.accessibleName())
        self._next.setToolTip(self._next.accessibleName())
        self.grid.setAccessibleName(self.tr("Calendar month"))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self._retranslate()
