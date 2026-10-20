"""Structured options retain ordinary popup sizing and stream-selection behavior."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.checkable_combo_box import CheckableComboBox
from iOpenPod.GUI.widgets.media_stream_option import (
    StreamOption,
    StreamOptionDelegate,
    set_stream_option,
)


@pytest.mark.parametrize("width", [320, 514])
def test_structured_popup_wraps_details_and_keeps_multiple_selection(
    width: int,
) -> None:
    combo = CheckableComboBox()
    StreamOptionDelegate(combo)
    option = StreamOption(
        "Full English [FTW+Commie | Dekinai edit] with a long descriptive title",
        "English · ASS · Hearing impaired",
        "Convert to iPod text",
        "Stream 3",
        "English · Full English",
    )
    combo.add_choice("Original complete stream label", 3, checked=False, enabled=True)
    set_stream_option(combo, 0, option)
    try:
        combo.resize(width, 40)
        combo.show()
        combo.showPopup()
        APPLICATION.processEvents()
        view = combo.view()
        assert view.window().width() == combo.width()
        assert not view.horizontalScrollBar().isVisible()
        rect = view.visualRect(combo.model().index(0, 0))
        assert rect.height() >= 4 * combo.fontMetrics().height()
        assert rect.bottom() < view.viewport().height()
        assert combo.itemData(0, Qt.ItemDataRole.ToolTipRole) is None
        assert (
            combo.itemData(0, Qt.ItemDataRole.AccessibleTextRole)
            == option.accessible_text
        )
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        assert combo.selection_text() == option.summary
        assert combo.item(0).checkState() == Qt.CheckState.Checked
        assert view.isVisible()
        QTest.keyClick(view, Qt.Key.Key_Space)
        assert combo.selection_text() == "None"
    finally:
        combo.hidePopup()
        combo.close()


def test_structured_single_choice_keeps_original_stream_data() -> None:
    combo = AppComboBox()
    StreamOptionDelegate(combo)
    combo.addItem("None", None)
    combo.addItem("Original audio label", 7)
    set_stream_option(
        combo,
        1,
        StreamOption(
            "Main audio", "Japanese · AAC · 2 channels", "", "Stream 7", "Japanese"
        ),
    )
    try:
        combo.resize(360, 40)
        combo.show()
        combo.showPopup()
        APPLICATION.processEvents()
        view = combo.view()
        QTest.mouseClick(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=view.visualRect(combo.model().index(1, 0)).center(),
        )
        assert combo.currentData() == 7
        assert not view.isVisible()
    finally:
        combo.hidePopup()
        combo.close()
