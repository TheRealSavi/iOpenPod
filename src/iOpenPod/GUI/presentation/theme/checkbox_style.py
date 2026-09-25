# Hallmark · component: checkbox · genre: modern-minimal · theme: iOpenPod
# states: default · hover · focus · active · disabled · indeterminate · checked
# contrast: pass · pre-emit critique: P5 H4 E5 S5 R5 V4
"""Cross-platform, palette-aware checkbox indicator painting."""

from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleOption, QWidget

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT, ThemeTokens

_APPLICATION_STYLE_ATTRIBUTE = "_iopenpod_checkbox_style"
_FOCUS_RING_WIDTH = 2.0
_BOX_BORDER_WIDTH = 1.5
_BOX_INSET = 2.0


class CheckboxStyle(QProxyStyle):
    """Retain the Host style while painting a consistent checkbox indicator."""

    def __init__(self, base_style_name: str, tokens: ThemeTokens) -> None:
        super().__init__(base_style_name)
        self._tokens = tokens

    def set_tokens(self, tokens: ThemeTokens) -> None:
        """Use semantic colors from the currently effective application theme."""

        self._tokens = tokens

    def pixelMetric(
        self,
        metric: QStyle.PixelMetric,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
    ) -> int:
        if metric in {
            QStyle.PixelMetric.PM_IndicatorWidth,
            QStyle.PixelMetric.PM_IndicatorHeight,
        }:
            return LAYOUT.checkbox_indicator_size
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            super().drawPrimitive(element, option, painter, widget)
            return

        state = option.state
        enabled = bool(state & QStyle.StateFlag.State_Enabled)
        checked = bool(state & QStyle.StateFlag.State_On)
        indeterminate = bool(state & QStyle.StateFlag.State_NoChange)
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        pressed = bool(state & QStyle.StateFlag.State_Sunken)
        focused = bool(state & QStyle.StateFlag.State_HasFocus)
        selected = checked or indeterminate

        outer_rect = QRectF(option.rect).adjusted(1.0, 1.0, -1.0, -1.0)
        box_rect = outer_rect.adjusted(
            _BOX_INSET,
            _BOX_INSET,
            -_BOX_INSET,
            -_BOX_INSET,
        )
        fill, border, mark = self._indicator_colors(
            enabled=enabled,
            selected=selected,
            hovered=hovered,
            pressed=pressed,
        )

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if focused:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(self._tokens.focus), _FOCUS_RING_WIDTH))
            painter.drawRoundedRect(outer_rect, 5.0, 5.0)

        painter.setBrush(QColor(fill))
        painter.setPen(QPen(QColor(border), _BOX_BORDER_WIDTH))
        painter.drawRoundedRect(box_rect, 3.0, 3.0)

        if checked:
            self._draw_checkmark(painter, box_rect, QColor(mark))
        elif indeterminate:
            self._draw_indeterminate_mark(painter, box_rect, QColor(mark))
        painter.restore()

    def _indicator_colors(
        self,
        *,
        enabled: bool,
        selected: bool,
        hovered: bool,
        pressed: bool,
    ) -> tuple[str, str, str]:
        tokens = self._tokens
        if not enabled:
            return tokens.surface_alt, tokens.border, tokens.text_disabled
        if selected:
            fill = (
                tokens.accent_pressed
                if pressed
                else tokens.accent_hover
                if hovered
                else tokens.accent
            )
            return fill, tokens.border_strong, tokens.accent_ink
        fill = (
            tokens.surface_pressed
            if pressed
            else tokens.surface_hover
            if hovered
            else tokens.surface
        )
        border = tokens.text_secondary if hovered else tokens.border_strong
        return fill, border, tokens.text

    @staticmethod
    def _draw_checkmark(
        painter: QPainter,
        rect: QRectF,
        color: QColor,
    ) -> None:
        path = QPainterPath()
        path.moveTo(rect.left() + 2.5, rect.center().y())
        path.lineTo(rect.left() + 4.8, rect.bottom() - 2.5)
        path.lineTo(rect.right() - 2.0, rect.top() + 2.5)
        pen = QPen(color, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        painter.drawPath(path)

    @staticmethod
    def _draw_indeterminate_mark(
        painter: QPainter,
        rect: QRectF,
        color: QColor,
    ) -> None:
        pen = QPen(color, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(
            QLineF(
                rect.left() + 2.5,
                rect.center().y(),
                rect.right() - 2.5,
                rect.center().y(),
            )
        )


def apply_checkbox_style(
    application: QApplication,
    tokens: ThemeTokens,
) -> None:
    """Install the checkbox proxy once, then update it on theme changes."""

    style = getattr(application, _APPLICATION_STYLE_ATTRIBUTE, None)
    if not isinstance(style, CheckboxStyle):
        base_style_name = application.style().objectName() or "fusion"
        style = CheckboxStyle(base_style_name, tokens)
        application.setStyle(style)
        setattr(application, _APPLICATION_STYLE_ATTRIBUTE, style)
    else:
        style.set_tokens(tokens)
