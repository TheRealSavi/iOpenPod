"""Shared direct-manipulation scrubber and playback timestamp formatting."""

from html import escape

from PySide6.QtCore import QCoreApplication, QEvent, QRect, Qt
from PySide6.QtGui import QHelpEvent, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider, QToolTip, QWidget

from iPodDB.library import TrackChapter


class SeekSlider(QSlider):
    """Provide direct, continuous pointer control over a playback position."""

    def __init__(self, orientation: Qt.Orientation, parent: QWidget) -> None:
        super().__init__(orientation, parent)
        self._chapters: tuple[TrackChapter, ...] = ()

    def set_chapters(self, chapters: tuple[TrackChapter, ...]) -> None:
        if chapters == self._chapters:
            return
        self._chapters = chapters
        QToolTip.hideText()
        self.update()

    def _chapter_markers(
        self, option: QStyleOptionSlider
    ) -> tuple[tuple[TrackChapter, QRect], ...]:
        if not self._chapters or option.maximum <= option.minimum:
            return ()
        style = self.style()
        endpoint = QStyleOptionSlider(option)
        endpoint.sliderPosition = option.minimum
        first = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            endpoint,
            QStyle.SubControl.SC_SliderHandle,
            self,
        ).center()
        endpoint.sliderPosition = option.maximum
        last = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            endpoint,
            QStyle.SubControl.SC_SliderHandle,
            self,
        ).center()
        span = last.x() - first.x()
        return tuple(
            (
                chapter,
                QRect(
                    round(
                        first.x()
                        + span
                        * (chapter.start_ms - option.minimum)
                        / (option.maximum - option.minimum)
                    ),
                    first.y() - 4,
                    1,
                    9,
                ),
            )
            for chapter in self._chapters
        )

    def event(self, event: QEvent) -> bool:
        if event.type() is QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            option = QStyleOptionSlider()
            self.initStyleOption(option)
            nearby = tuple(
                (chapter, marker)
                for chapter, marker in self._chapter_markers(option)
                if marker.adjusted(-4, -3, 4, 3).contains(event.pos())
            )
            if nearby and self.isEnabled():
                chapter, marker = min(
                    nearby, key=lambda item: abs(item[1].x() - event.pos().x())
                )
                title = chapter.title.strip() or QCoreApplication.translate(
                    "_SeekSlider", "Untitled Chapter"
                )
                timestamp = (
                    f"{format_playback_time(chapter.start_ms)}."
                    f"{chapter.start_ms % 1000:03d}"
                )
                QToolTip.showText(
                    event.globalPos(),
                    f"<p>{escape(title)}<br>{timestamp}</p>",
                    self,
                    marker.adjusted(-4, -3, 4, 3),
                )
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        control = QStyle.ComplexControl.CC_Slider
        handle_control = QStyle.SubControl.SC_SliderHandle
        handle = style.subControlRect(control, option, handle_control, self)

        # QStyle rounds the handle position to whole logical pixels. At normal
        # Track lengths that leaves many animation frames visually identical.
        # Keep the native styling, but translate its handle by the fractional
        # remainder so antialiasing can show motion between pixel boundaries.
        endpoint = QStyleOptionSlider(option)
        endpoint.sliderPosition = option.minimum
        start = style.subControlRect(control, endpoint, handle_control, self).x()
        endpoint.sliderPosition = option.maximum
        end = style.subControlRect(control, endpoint, handle_control, self).x()
        fraction = (option.sliderPosition - option.minimum) / max(
            1, option.maximum - option.minimum
        )
        offset = start + fraction * (end - start) - handle.x()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        option.subControls = (
            QStyle.SubControl.SC_SliderGroove | QStyle.SubControl.SC_SliderTickmarks
        )
        style.drawComplexControl(control, option, painter, self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for _chapter, marker in self._chapter_markers(option):
            painter.fillRect(marker, self.palette().color(self.foregroundRole()))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(offset, 0.0)
        option.subControls = handle_control
        style.drawComplexControl(control, option, painter, self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() is not Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setSliderDown(True)
        self._set_value_from_pointer(event.position().x())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (self.isSliderDown() and event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        self._set_value_from_pointer(event.position().x())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() is not Qt.MouseButton.LeftButton or not self.isSliderDown():
            super().mouseReleaseEvent(event)
            return
        self._set_value_from_pointer(event.position().x())
        self.setSliderDown(False)
        event.accept()

    def _set_value_from_pointer(self, pointer_x: float) -> None:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle_length = self.style().pixelMetric(
            QStyle.PixelMetric.PM_SliderLength,
            option,
            self,
        )
        span = self.style().pixelMetric(
            QStyle.PixelMetric.PM_SliderSpaceAvailable,
            option,
            self,
        )
        handle_center = round(pointer_x) - (handle_length // 2)
        self.setValue(
            QStyle.sliderValueFromPosition(
                self.minimum(),
                self.maximum(),
                handle_center,
                span,
                option.upsideDown,
            )
        )


def format_playback_time(length_ms: int) -> str:
    minutes, seconds = divmod(max(0, length_ms) // 1000, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"
