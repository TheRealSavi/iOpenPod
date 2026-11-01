"""Plain-text previews measure explicit line breaks before painting them."""

import pytest
from PySide6.QtGui import QFontMetrics
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.GUI.widgets.elided_label import ElidedLabel


@pytest.mark.parametrize("line_break", ("\n", "\r\n", "\r", "\u2028"))
def test_explicit_line_breaks_receive_two_complete_lines(line_break: str) -> None:
    label = ElidedLabel(2, tooltip_on_elision=False)
    text = f"A short show description.{line_break}©MWMH"
    label.setText(text)
    try:
        line_height = QFontMetrics(label.font()).lineSpacing()
        for width in (300, 900):
            label.resize(width, label.heightForWidth(width))
            label.show()
            APPLICATION.processEvents()

            assert label.text() == text
            assert label.heightForWidth(width) == 2 * line_height
            assert label.contentsRect().height() == 2 * line_height
            assert not label.is_elided
            assert not label.toolTip()
    finally:
        label.close()


def test_explicit_lines_still_respect_the_preview_limit() -> None:
    label = ElidedLabel(2)
    text = "First line\nSecond line\nThird line"
    label.setText(text)
    try:
        line_height = QFontMetrics(label.font()).lineSpacing()
        label.resize(300, label.heightForWidth(300))
        label.show()
        APPLICATION.processEvents()

        assert label.heightForWidth(300) == 2 * line_height
        assert label.is_elided
        assert label.toolTip() == text
    finally:
        label.close()


def test_constrained_height_elides_explicit_lines_without_growing() -> None:
    label = ElidedLabel(2)
    text = "A short show description.\nCopyright Studio"
    label.setText(text)
    try:
        line_height = QFontMetrics(label.font()).lineSpacing()
        available_height = line_height + line_height // 2
        label.resize(300, available_height)
        label.show()
        APPLICATION.processEvents()

        assert label.height() == available_height
        assert label.is_elided
        assert label.toolTip() == text
        assert not label.grab().isNull()
    finally:
        label.close()
