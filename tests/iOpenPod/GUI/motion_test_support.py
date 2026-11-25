"""A deterministic Host style with widget animation disabled."""

from PySide6.QtWidgets import (
    QProxyStyle,
    QStyle,
    QStyleHintReturn,
    QStyleOption,
    QWidget,
)


class NoMotionStyle(QProxyStyle):
    def styleHint(
        self,
        hint: QStyle.StyleHint,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
        returnData: QStyleHintReturn | None = None,  # noqa: N803 - Qt keyword name
    ) -> int:
        if hint == QStyle.StyleHint.SH_Widget_Animate:
            return 0
        return super().styleHint(hint, option, widget, returnData)


def disable_motion(widget: QWidget) -> None:
    style = NoMotionStyle("Fusion")
    style.setParent(widget)
    widget.setStyle(style)
