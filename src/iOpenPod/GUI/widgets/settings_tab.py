"""Responsive Settings column and a viewport-anchored, fading example image."""

from functools import partial

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QModelIndex,
    QObject,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QHideEvent,
    QImage,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QGraphicsOpacityEffect,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.settings_illustrations import (
    SettingExample,
    has_setting_image,
    setting_image,
)
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.setting_group import SettingRow

SETTINGS_PREVIEW_BREAKPOINT = 1720
SETTINGS_COLUMN_WIDTH = 960
SETTINGS_VIGNETTE_ENABLED = False


class SettingsExampleImage(QWidget):
    """Render a Settings image and crossfade replacements from the current frame."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._image = QPixmap()
        self._previous = QImage()
        self._progress = 1.0
        self.setMinimumHeight(160)
        self._crossfade = QVariantAnimation(self)
        self._crossfade.setObjectName("settingsImageCrossfade")
        self._crossfade.setDuration(450)
        self._crossfade.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._crossfade.setStartValue(0.0)
        self._crossfade.setEndValue(1.0)
        self._crossfade.valueChanged.connect(self._advance)
        self._crossfade.finished.connect(self._finish_crossfade)

    def set_image(self, image: QPixmap, *, animate: bool) -> None:
        if image.cacheKey() == self._image.cacheKey():
            return
        # Flatten an interrupted blend, retaining exactly the visible composition.
        previous = self.frame() if animate and not self._image.isNull() else QImage()
        self._crossfade.stop()
        self._previous = previous
        self._image = image
        self._progress = 1.0 if previous.isNull() else 0.0
        if not previous.isNull():
            self._crossfade.start()
        self.update()

    def _advance(self, value: object) -> None:
        if isinstance(value, (int, float)):
            self._progress = float(value)
            self.update()

    def _finish_crossfade(self) -> None:
        self._previous = QImage()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(640, 360)

    def frame(self) -> QImage:
        """Compose weighted images without dimming their overlapping opaque pixels."""
        dpr = self.devicePixelRatioF()
        frame = QImage(
            max(1, round(self.width() * dpr)),
            max(1, round(self.height() * dpr)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        frame.setDevicePixelRatio(dpr)
        frame.fill(Qt.GlobalColor.transparent)
        if self._image.isNull():
            return frame
        size = self._image.size().scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio
        )
        rect = QRect(0, 0, size.width(), size.height())
        rect.moveCenter(self.rect().center())
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(rect, self._image)
        if SETTINGS_VIGNETTE_ENABLED:
            self._soften_edges(painter, rect)
        painter.end()
        if self._previous.isNull():
            return frame
        blended = self._previous.scaled(
            frame.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        blended.setDevicePixelRatio(dpr)
        painter = QPainter(blended)
        # Interpolate the complete canvases, including transparent margins.
        # SourceOver would retain old pixels under the incoming transparency.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.setOpacity(self._progress)
        painter.drawImage(0, 0, frame)
        painter.end()
        return blended

    @staticmethod
    def _soften_edges(painter: QPainter, rect: QRect) -> None:
        """Fade the actual image bounds into any background, before crossfading."""
        feather = min(90.0, min(rect.width(), rect.height()) * 0.25)
        if feather <= 0:
            return
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn
        )
        for horizontal in (True, False):
            length = rect.width() if horizontal else rect.height()
            gradient = QLinearGradient(
                rect.x(),
                rect.y(),
                rect.x() + (length if horizontal else 0),
                rect.y() + (0 if horizontal else length),
            )
            # Smoothstep opacity gives the feather a soft start and finish.
            for step in range(17):
                position = step / 16
                alpha = round(255 * position * position * (3 - 2 * position))
                stop = position * feather / length
                color = QColor(0, 0, 0, alpha)
                gradient.setColorAt(stop, color)
                gradient.setColorAt(1.0 - stop, color)
            painter.fillRect(rect, gradient)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.drawImage(0, 0, self.frame())


class SettingsPreview(QWidget):
    """Crossfade replacements; use overall opacity only for appearing or leaving."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPreview")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._current: SettingExample | None = None
        self._pending: SettingExample | None = None
        self._queued: SettingExample | None = None
        self._hover_delay = QTimer(self)
        self._hover_delay.setObjectName("settingsPreviewHoverDelay")
        self._hover_delay.setSingleShot(True)
        self._hover_delay.setTimerType(Qt.TimerType.PreciseTimer)
        self._hover_delay.setInterval(200)
        self._hover_delay.timeout.connect(self._show_queued)
        self._image = SettingsExampleImage(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._image, 1)
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.finished.connect(self._finished)

    @property
    def example(self) -> SettingExample | None:
        return self._pending

    def set_example(self, example: SettingExample | None) -> None:
        if example == self._pending:
            return
        self._fade.stop()
        self._pending = example
        if example is None:
            self._animate(0.0)
            return
        self._current = example
        self.setAccessibleName(example.title)
        self.setAccessibleDescription(example.description)
        self._render()
        if self._opacity.opacity() < 1.0:
            self._animate(1.0)

    def queue_example(self, example: SettingExample | None) -> None:
        """Keep the current image until a new hover target remains for 200 ms."""
        if example is None or example == self._current:
            self._hover_delay.stop()
            self._queued = None
            self.set_example(example)
        elif example != self._queued:
            self._queued = example
            self._hover_delay.start()

    def _show_queued(self) -> None:
        example = self._queued
        self._queued = None
        self.set_example(example)

    def clear(self) -> None:
        self._hover_delay.stop()
        self._queued = None
        self._clear_image()

    def _clear_image(self) -> None:
        self._fade.stop()
        self._opacity.setOpacity(0.0)
        self._current = self._pending = None
        self.setAccessibleName("")
        self.setAccessibleDescription("")
        self._image.set_image(QPixmap(), animate=False)

    def _animate(self, opacity: float) -> None:
        self._fade.stop()
        self._fade.setEasingCurve(
            QEasingCurve.Type.InOutSine
            if opacity == 0.0
            else QEasingCurve.Type.OutCubic
        )
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(opacity)
        self._fade.setDuration(300)
        self._fade.start()

    def _finished(self) -> None:
        if self._pending is None and self._opacity.opacity() == 0.0:
            self._clear_image()

    def _render(self) -> None:
        if self._current is not None:
            self._image.set_image(
                setting_image(self._current, self.palette(), self.devicePixelRatioF()),
                animate=self._opacity.opacity() > 0.0,
            )

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.DevicePixelRatioChange,
        ):
            self._render()


class SettingsTab(QScrollArea):
    """Own column sizing and hover/popup lifetime without changing any preference."""

    columnWidthChanged = Signal(int)

    def __init__(
        self,
        name: str,
        widgets: tuple[QWidget, ...],
        parent: QWidget,
        *,
        theme_manager: ThemeManager,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self.setObjectName(name)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self._wide = False
        self._hovered: SettingRow | None = None
        self._popup: QComboBox | None = None
        self._highlight: int | None = None
        content = QWidget(self)
        self._column = content
        self._widgets = widgets
        self._column_width = SETTINGS_COLUMN_WIDTH
        column_layout = QVBoxLayout(content)
        column_layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        column_layout.setSpacing(LAYOUT.space_xs)
        for widget in widgets:
            # Category widgets retain their standalone caps; this page owns the
            # shared responsive column, including nested Settings groups.
            for child in (widget, *widget.findChildren(QWidget)):
                if child.maximumWidth() == SETTINGS_COLUMN_WIDTH:
                    child.setMaximumWidth(16777215)
            column_layout.addWidget(widget)
        column_layout.addStretch(1)
        self.setWidget(content)
        self.preview = SettingsPreview(self.viewport())
        self.preview.hide()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh_example)
        theme_manager.lightThemeChanged.connect(self._schedule_refresh)
        theme_manager.darkThemeChanged.connect(self._schedule_refresh)
        for combo in self._column.findChildren(QComboBox):
            # A custom popup can move its hover index without emitting the
            # combobox's highlighted signal. Observe the view's pointer entry.
            combo.view().setMouseTracking(True)
            combo.view().entered.connect(partial(self._option_entered, combo))
            combo.highlighted.connect(partial(self._highlighted, combo))
            combo.currentIndexChanged.connect(self._schedule_refresh)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)

    @property
    def column_width(self) -> int:
        return self._column_width

    def _layout_content(self) -> None:
        was_wide = self._wide
        self._wide = self.width() >= SETTINGS_PREVIEW_BREAKPOINT
        available = max(1, self.viewport().width() - 2 * LAYOUT.space_lg)
        width = SETTINGS_COLUMN_WIDTH if self._wide else available
        self._column_width = width
        for widget in self._widgets:
            widget.setMaximumWidth(width)
        x = LAYOUT.space_lg + width + LAYOUT.space_xl
        self.preview.setGeometry(
            x,
            LAYOUT.space_lg,
            max(1, self.viewport().width() - x - LAYOUT.space_lg),
            max(1, min(520, self.viewport().height() - 2 * LAYOUT.space_lg)),
        )
        self.preview.setVisible(self._wide)
        self.preview.raise_()
        if not self._wide:
            self.preview.clear()
        else:
            if not was_wide:
                self._hovered = next(
                    (
                        row
                        for row in self._column.findChildren(SettingRow)
                        if row.isVisible() and row.underMouse()
                    ),
                    None,
                )
                self._popup = next(
                    (
                        combo
                        for combo in self._column.findChildren(QComboBox)
                        if combo.view().isVisible()
                    ),
                    None,
                )
                self._highlight = None
            self._schedule_refresh()
        self.columnWidthChanged.emit(width)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._layout_content()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._layout_content()
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def hideEvent(self, event: QHideEvent) -> None:
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        self._hovered = None
        self._popup = None
        self._highlight = None
        self.preview.clear()
        super().hideEvent(event)

    def _row_for(self, widget: QObject) -> SettingRow | None:
        if not isinstance(widget, QWidget):
            return None
        current: QWidget | None = widget
        while current is not None and current is not self._column:
            if isinstance(current, SettingRow):
                return current if self._column.isAncestorOf(current) else None
            current = current.parentWidget()
        return None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not hasattr(self, "_refresh_timer"):
            return super().eventFilter(watched, event)
        kind = event.type()
        if watched is self.viewport() and kind == QEvent.Type.Resize:
            self._layout_content()
        if not self.isVisible() or not self._wide:
            return super().eventFilter(watched, event)
        if isinstance(watched, SettingRow):
            if kind == QEvent.Type.Enter and self._row_for(watched) is not None:
                self._hovered = watched
                self._schedule_refresh()
            elif (
                kind in (QEvent.Type.Leave, QEvent.Type.Hide)
                and watched is self._hovered
            ):
                self._hovered = None
                self._schedule_refresh()
        elif isinstance(watched, QAbstractItemView) and kind in (
            QEvent.Type.Show,
            QEvent.Type.Hide,
        ):
            row = self._row_for(watched)
            if row is not None:
                combo = (
                    row.control
                    if isinstance(row.control, QComboBox)
                    else row.control.findChild(QComboBox)
                )
                if combo is not None and watched is combo.view():
                    self._popup = combo if kind == QEvent.Type.Show else None
                    self._highlight = None
                    self._schedule_refresh()
        elif watched is self and kind in (
            QEvent.Type.LanguageChange,
            QEvent.Type.PaletteChange,
        ):
            self._schedule_refresh()
        return super().eventFilter(watched, event)

    def _schedule_refresh(self) -> None:
        self._refresh_timer.start(0)

    def _scrolled(self) -> None:
        # A scrolled-away row must not leave its example pinned in the viewport.
        self._hovered = None
        self._schedule_refresh()

    def _highlighted(self, combo: QComboBox, index: int) -> None:
        if combo.view().isVisible():
            self._popup = combo
            self._highlight = index
            self._schedule_refresh()

    def _option_entered(self, combo: QComboBox, index: QModelIndex) -> None:
        if (
            index.isValid()
            and index.flags() & Qt.ItemFlag.ItemIsEnabled
            and index.flags() & Qt.ItemFlag.ItemIsSelectable
        ):
            self._highlighted(combo, index.row())

    def _refresh_example(self) -> None:
        if not self._wide or not self.isVisible():
            return
        popup = self._popup
        row = (
            self._row_for(popup)
            if popup is not None and popup.view().isVisible()
            else self._hovered
        )
        if row is None or not row.isVisible():
            self.preview.queue_example(None)
            return
        combo = (
            row.control
            if isinstance(row.control, QComboBox)
            else row.control.findChild(QComboBox)
        )
        choice = value = ""
        if combo is not None:
            index = (
                self._highlight
                if combo is popup and self._highlight is not None
                else combo.currentIndex()
            )
            choice, value = combo.itemText(index), str(combo.itemData(index))
        key = row.control.objectName()
        if not key:
            named = next(
                (
                    child
                    for child in row.control.findChildren(QWidget)
                    if child.objectName()
                ),
                None,
            )
            key = named.objectName() if named is not None else ""
        example = SettingExample(
            key,
            self.objectName(),
            row.title,
            row.description,
            choice,
            value,
            light_theme=self._theme_manager.light_theme,
            dark_theme=self._theme_manager.dark_theme,
        )
        self.preview.queue_example(example if has_setting_image(example) else None)
