"""An accessible native month calendar with bounded, painted event previews."""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QDate, QEvent, QLocale, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPalette, QPen, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QHBoxLayout,
    QLabel,
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
        self.setObjectName("calendarMonthGrid")
        self.setNavigationBarVisible(False)
        self.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self.setHorizontalHeaderFormat(
            QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
        )
        self.setFirstDayOfWeek(QLocale().firstDayOfWeek())
        self.setDateRange(QDate(100, 1, 1), QDate(9999, 12, 31))
        self._markers: tuple[CalendarMarker, ...] = ()
        self._labels: dict[int, list[str]] = {}
        self._today = today
        self.setSelectedDate(today)
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
        header.setForeground(self.palette().brush(QPalette.ColorRole.PlaceholderText))
        header.setBackground(self.palette().brush(QPalette.ColorRole.Base))
        self.setHeaderTextFormat(header)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, header)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, header)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.LanguageChange):
            self._refresh_header()
            self.updateCells()

    def paintCell(self, painter: QPainter, rect: QRect, date: QDate) -> None:
        painter.save()
        painter.setClipRect(rect)
        palette = self.palette()
        painter.fillRect(rect, palette.brush(QPalette.ColorRole.Base))
        selected = date == self.selectedDate()
        current = date.month() == self.monthShown()
        accent = palette.color(QPalette.ColorRole.Link)
        if selected:
            fill = palette.color(QPalette.ColorRole.Link)
            fill.setAlpha(24)
            painter.fillRect(rect.adjusted(1, 1, -1, -1), fill)
        painter.setPen(palette.color(QPalette.ColorRole.Mid))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomRight())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setBold(selected or date == self._today)
        painter.setFont(font)
        height = QFontMetrics(font).height()
        badge = QRect(
            rect.x() + LAYOUT.space_xs,
            rect.y() + LAYOUT.space_xs,
            height + 10,
            height + 6,
        )
        if date == self._today:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(QRectF(badge), 6, 6)
            painter.setPen(
                QApplication.palette().color(QPalette.ColorRole.HighlightedText)
            )
        else:
            painter.setPen(
                palette.color(
                    QPalette.ColorRole.Text
                    if current
                    else QPalette.ColorRole.PlaceholderText
                )
            )
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(date.day()))
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(accent, 1.5))
            painter.drawRoundedRect(QRectF(rect.adjusted(2, 2, -2, -2)), 6, 6)
            focus = self.focusProxy()
            if self.hasFocus() or (focus is not None and focus.hasFocus()):
                painter.setPen(QPen(accent, 1, Qt.PenStyle.DotLine))
                painter.drawRect(rect.adjusted(5, 5, -5, -5))
        labels = self._labels.get(date.toJulianDay(), [])
        if labels and (rect.width() < 70 or rect.height() < height * 2 + 24):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(rect.right() - 12, rect.top() + 12, 4, 4)
        else:
            font.setBold(False)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            y = badge.bottom() + LAYOUT.space_xs
            available = max(0, (rect.bottom() - y - 3) // (height + 4))
            for index, title in enumerate(labels[:available]):
                if available > 1 and index == available - 1 and len(labels) > available:
                    title = self.tr("+{count} more").format(count=len(labels) - index)
                line = QRect(rect.x() + 8, y, rect.width() - 14, height + 2)
                painter.setPen(
                    accent
                    if current
                    else palette.color(QPalette.ColorRole.PlaceholderText)
                )
                painter.drawText(
                    line,
                    Qt.AlignmentFlag.AlignVCenter,
                    metrics.elidedText(
                        title, Qt.TextElideMode.ElideRight, line.width()
                    ),
                )
                y += height + 4
            if available == 1 and len(labels) > 1:
                painter.setPen(accent)
                painter.drawText(
                    rect.adjusted(8, 8, -8, -8),
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                    f"+{len(labels) - 1}",
                )
        painter.restore()


class CalendarMonth(QWidget):
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
        self._title.setProperty("extrasHeading", True)
        self._previous = IconButton("chevron-left", "", self, kind=IconButtonKind.QUIET)
        self._next = IconButton("chevron-right", "", self, kind=IconButtonKind.QUIET)
        self._today = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
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
        layout.setContentsMargins(0, 0, 0, 0)
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
