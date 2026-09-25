"""Reusable plain-text label with bounded multiline elision."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import (
    QFont,
    QFontMetrics,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    """Draw wrapped plain text up to an explicit number of visible lines."""

    def __init__(
        self,
        maximum_lines: int,
        parent: QWidget | None = None,
    ) -> None:
        if maximum_lines <= 0:
            raise ValueError("An ElidedLabel requires at least one visible line")
        self._maximum_lines = maximum_lines
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._sync_geometry()

    @property
    def maximum_lines(self) -> int:
        return self._maximum_lines

    @property
    def is_elided(self) -> bool:
        return self._visible_lines()[1]

    def setText(self, text: str) -> None:
        super().setText(text)
        self._sync_geometry()
        self.updateGeometry()
        self.update()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        margins = self.contentsMargins()
        content_width = max(1, width - margins.left() - margins.right())
        lines, _elided = _layout_lines(
            self.text(),
            self.font(),
            content_width,
            self._maximum_lines,
        )
        line_count = max(1, len(lines)) if self.text() else 0
        return (
            margins.top()
            + margins.bottom()
            + QFontMetrics(self.font()).lineSpacing() * line_count
        )

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(hint.width(), min(hint.height(), self._maximum_text_height()))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, min(super().minimumSizeHint().height(), self.maximumHeight()))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange}:
            self._sync_geometry()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_tooltip()

    def paintEvent(self, _event: QPaintEvent) -> None:
        rect = QRectF(self.contentsRect())
        lines, _elided = self._visible_lines()
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        line_height = QFontMetrics(self.font()).lineSpacing()
        for index, line in enumerate(lines):
            painter.drawText(
                QRectF(
                    rect.left(),
                    rect.top() + index * line_height,
                    rect.width(),
                    line_height,
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                line,
            )

    def _visible_lines(self) -> tuple[tuple[str, ...], bool]:
        line_height = max(1, QFontMetrics(self.font()).lineSpacing())
        fitting_lines = max(1, self.contentsRect().height() // line_height)
        return _layout_lines(
            self.text(),
            self.font(),
            max(1, self.contentsRect().width()),
            min(self._maximum_lines, fitting_lines),
        )

    def _maximum_text_height(self) -> int:
        margins = self.contentsMargins()
        return (
            margins.top()
            + margins.bottom()
            + QFontMetrics(self.font()).lineSpacing() * self._maximum_lines
        )

    def _sync_geometry(self) -> None:
        height = self._maximum_text_height()
        if self.maximumHeight() != height:
            self.setMaximumHeight(height)
        self._sync_tooltip()

    def _sync_tooltip(self) -> None:
        self.setToolTip(self.text() if self.is_elided else "")


def _layout_lines(
    text: str,
    font: QFont,
    width: int,
    maximum_lines: int,
) -> tuple[tuple[str, ...], bool]:
    if not text:
        return (), False
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    ranges: list[tuple[int, int]] = []
    layout.beginLayout()
    while len(ranges) < maximum_lines:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(float(width))
        ranges.append((line.textStart(), line.textLength()))
    overflow = len(ranges) == maximum_lines and layout.createLine().isValid()
    layout.endLayout()

    metrics = QFontMetrics(font)
    lines = [text[start : start + length].strip() for start, length in ranges]
    if overflow and ranges:
        last_start, _last_length = ranges[-1]
        remainder = " ".join(text[last_start:].split())
        lines[-1] = metrics.elidedText(
            remainder,
            Qt.TextElideMode.ElideRight,
            width,
        )
    return tuple(lines), overflow


__all__ = ["ElidedLabel"]
