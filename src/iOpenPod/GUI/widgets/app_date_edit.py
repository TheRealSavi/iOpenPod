"""Hallmark · component: date picker · preserved iOpenPod theme and native editing.

Compact month/year navigation, rounded days and the application's shared chevron.
Pre-emit critique: P5 H5 E4 S5 R5 V4. No decorative motion or new date semantics.
"""

from PySide6.QtCore import QDate, QEvent, QObject, QPoint, QRect, QSize, Qt
from PySide6.QtGui import (
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QShowEvent,
    QStandardItemModel,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCalendarWidget,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QSpinBox,
    QStyle,
    QStyleOption,
    QStyleOptionComboBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.dropdown_indicator import paint_dropdown_indicator
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    IconButton,
    IconButtonKind,
)


class _DateCalendar(QCalendarWidget):
    """A compact native calendar; Qt retains hit testing and keyboard selection."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("datePickerCalendar")
        self.setNavigationBarVisible(False)
        self.setDateEditEnabled(False)
        self.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self.setHorizontalHeaderFormat(
            QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
        )
        self._hover = QPoint(-1, -1)
        self._view = self.findChild(QTableView, "qt_calendar_calendarview")
        if self._view is not None:
            self._view.setFrameShape(QFrame.Shape.NoFrame)
            self._view.setMouseTracking(True)
            self._view.viewport().installEventFilter(self)
        header = QWidget(self)
        self._month = AppComboBox(header)
        self._month.setObjectName("datePickerMonth")
        self._year = QSpinBox(header)
        self._year.setObjectName("datePickerYear")
        self._year.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._year.setKeyboardTracking(False)
        self._previous = IconButton(
            "chevron-left", "", header, kind=IconButtonKind.QUIET
        )
        self._previous.setObjectName("datePickerPrevious")
        self._next = IconButton("chevron-right", "", header, kind=IconButtonKind.QUIET)
        self._next.setObjectName("datePickerNext")
        navigation = QHBoxLayout(header)
        navigation.setContentsMargins(0, 0, 0, 0)
        navigation.setSpacing(LAYOUT.space_2xs)
        navigation.addWidget(self._month, 1)
        navigation.addWidget(self._year)
        navigation.addWidget(self._previous)
        navigation.addWidget(self._next)
        footer = QWidget(self)
        self._today = ActionButton(parent=footer, kind=ActionButtonKind.QUIET)
        self._today.setObjectName("datePickerToday")
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self._today)
        actions.addStretch(1)
        layout = self.layout()
        assert isinstance(layout, QVBoxLayout)
        layout.setContentsMargins(
            LAYOUT.space_sm, LAYOUT.space_sm, LAYOUT.space_sm, LAYOUT.space_xs
        )
        layout.setSpacing(LAYOUT.space_xs)
        layout.insertWidget(0, header)
        layout.addWidget(footer)
        self._month.currentIndexChanged.connect(self._navigate)
        self._year.valueChanged.connect(self._navigate)
        self._previous.clicked.connect(self.showPreviousMonth)
        self._next.clicked.connect(self.showNextMonth)
        self._today.clicked.connect(self._select_today)
        self.currentPageChanged.connect(self._sync_navigation)
        self._retranslate()
        self._refresh_header()

    def sizeHint(self) -> QSize:
        layout = self.layout()
        assert layout is not None
        return QSize(
            max(LAYOUT.date_picker_width, layout.minimumSize().width()),
            max(LAYOUT.date_picker_height, layout.minimumSize().height()),
        )

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event: QPaintEvent) -> None:
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_Widget, option, painter, self
        )
        painter.end()
        super().paintEvent(event)

    def _navigate(self) -> None:
        first = QDate(self._year.value(), self._month.currentIndex() + 1, 1)
        first = max(self.minimumDate(), min(first, self.maximumDate()))
        self.setCurrentPage(first.year(), first.month())

    def _sync_navigation(self) -> None:
        self._month.blockSignals(True)
        self._year.blockSignals(True)
        self._year.setRange(self.minimumDate().year(), self.maximumDate().year())
        self._year.setValue(self.yearShown())
        self._month.setCurrentIndex(self.monthShown() - 1)
        self._month.blockSignals(False)
        self._year.blockSignals(False)
        first = QDate(self.yearShown(), self.monthShown(), 1)
        self._previous.setEnabled(first > self.minimumDate())
        self._next.setEnabled(first.addMonths(1) <= self.maximumDate())
        self._today.setEnabled(
            self.minimumDate() <= QDate.currentDate() <= self.maximumDate()
        )
        model = self._month.model()
        if isinstance(model, QStandardItemModel):
            for month in range(1, 13):
                row = model.item(month - 1)
                start = QDate(self.yearShown(), month, 1)
                row.setEnabled(
                    start <= self.maximumDate()
                    and start.addMonths(1).addDays(-1) >= self.minimumDate()
                )

    def _select_today(self) -> None:
        today = QDate.currentDate()
        if self.minimumDate() <= today <= self.maximumDate():
            self.setSelectedDate(today)
            self.activated.emit(today)

    def _retranslate(self) -> None:
        self._month.blockSignals(True)
        self._month.clear()
        self._month.addItems(
            [self.locale().standaloneMonthName(month) for month in range(1, 13)]
        )
        self._month.blockSignals(False)
        self._month.setAccessibleName(self.tr("Month"))
        self._year.setAccessibleName(self.tr("Year"))
        self._previous.setAccessibleName(self.tr("Previous month"))
        self._next.setAccessibleName(self.tr("Next month"))
        self._previous.setToolTip(self._previous.accessibleName())
        self._next.setToolTip(self._next.accessibleName())
        self._today.setText(self.tr("Today"))
        self.setAccessibleName(self.tr("Choose date"))
        self.setFirstDayOfWeek(self.locale().firstDayOfWeek())
        self._sync_navigation()

    def _refresh_header(self) -> None:
        header = QTextCharFormat()
        header.setForeground(
            QApplication.palette().brush(QPalette.ColorRole.PlaceholderText)
        )
        header.setBackground(self.palette().brush(QPalette.ColorRole.Base))
        header.setFontWeight(QFont.Weight.Medium)
        self.setHeaderTextFormat(header)
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.setWeekdayTextFormat(day, header)

    def showEvent(self, event: QShowEvent) -> None:
        self._hover = QPoint(-1, -1)
        self._sync_navigation()
        super().showEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            self._refresh_header()
        if hasattr(self, "_month") and event.type() in (
            QEvent.Type.LanguageChange,
            QEvent.Type.LocaleChange,
        ):
            self._retranslate()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if self._view is not None and watched is self._view.viewport():
            if isinstance(event, QMouseEvent) and event.type() == QEvent.Type.MouseMove:
                self._hover = event.position().toPoint()
                self.updateCells()
            elif event.type() == QEvent.Type.Leave:
                self._hover = QPoint(-1, -1)
                self.updateCells()
        return super().eventFilter(watched, event)

    def paintCell(self, painter: QPainter, rect: QRect, date: QDate) -> None:
        painter.save()
        painter.setClipRect(rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(rect, palette.brush(QPalette.ColorRole.Base))
        cell = rect.adjusted(
            LAYOUT.space_3xs, LAYOUT.space_3xs, -LAYOUT.space_3xs, -LAYOUT.space_3xs
        )
        selected = date == self.selectedDate()
        available = self.minimumDate() <= date <= self.maximumDate()
        today = date == QDate.currentDate()
        painter.setPen(Qt.PenStyle.NoPen)
        if selected:
            painter.setBrush(QApplication.palette().brush(QPalette.ColorRole.Highlight))
            painter.drawRoundedRect(cell, LAYOUT.radius_control, LAYOUT.radius_control)
        elif available and rect.contains(self._hover):
            painter.setBrush(palette.brush(QPalette.ColorRole.AlternateBase))
            painter.drawRoundedRect(cell, LAYOUT.radius_control, LAYOUT.radius_control)
        if today and not selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(palette.color(QPalette.ColorRole.Link), 1))
            painter.drawRoundedRect(cell, LAYOUT.radius_control, LAYOUT.radius_control)
        color = (
            QApplication.palette().color(QPalette.ColorRole.HighlightedText)
            if selected
            else palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
            if not available
            else QApplication.palette().color(QPalette.ColorRole.PlaceholderText)
            if date.month() != self.monthShown()
            else palette.color(QPalette.ColorRole.Text)
        )
        painter.setPen(color)
        font = QFont(self.font())
        font.setBold(selected or today)
        painter.setFont(font)
        painter.drawText(
            cell, Qt.AlignmentFlag.AlignCenter, self.locale().toString(date.day())
        )
        if selected and self._view is not None and self._view.hasFocus():
            painter.setPen(QPen(color, 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                cell.adjusted(2, 2, -2, -2),
                LAYOUT.radius_control,
                LAYOUT.radius_control,
            )
        painter.restore()


class AppDateEdit(QDateEdit):
    """Native date input and popup lifecycle with the application's visual language."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("themedDatePicker", True)
        self.setCalendarPopup(True)
        self._calendar = _DateCalendar(self)
        self.setCalendarWidget(self._calendar)
        self._calendar.installEventFilter(self)
        self._popup_date = self.date()
        for child in self._calendar.findChildren(QWidget):
            child.installEventFilter(self)
        popup = self._calendar.parentWidget()
        assert popup is not None
        popup.setObjectName("datePickerPopup")
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        popup.installEventFilter(self)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self.calendarPopup():
            return
        option = QStyleOptionComboBox()
        option.initFrom(self)
        option.editable = True
        rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxArrow,
            self,
        )
        paint_dropdown_indicator(
            self,
            rect,
            expanded=self._calendar.isVisible(),
            enabled=not self.isReadOnly(),
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        calendar = getattr(self, "_calendar", None)
        if calendar is not None:
            if watched is calendar and event.type() in (
                QEvent.Type.Show,
                QEvent.Type.Hide,
            ):
                if event.type() == QEvent.Type.Show:
                    self._popup_date = self.date()
                self.update()
            if (
                isinstance(event, QKeyEvent)
                and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape
                and QApplication.activePopupWidget() is calendar.window()
            ):
                self.setDate(self._popup_date)
                calendar.window().close()
                return True
        return super().eventFilter(watched, event)
