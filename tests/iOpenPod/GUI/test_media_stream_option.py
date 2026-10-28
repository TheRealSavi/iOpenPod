"""Structured options retain ordinary popup sizing and stream-selection behavior."""

import pytest
from PySide6.QtCore import Qt, qInstallMessageHandler
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QLineEdit
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.checkable_combo_box import CheckableComboBox
from iOpenPod.GUI.widgets.media_stream_option import (
    StreamOption,
    StreamOptionDelegate,
    set_stream_option,
)


@pytest.mark.parametrize("combo_type", [AppComboBox, CheckableComboBox])
@pytest.mark.parametrize("action", ["select", "escape", "hide"])
def test_stream_popup_closes_without_treating_widgets_as_editors(
    combo_type: type[AppComboBox], action: str
) -> None:
    combo = combo_type()
    delegate = StreamOptionDelegate(combo)
    if isinstance(combo, CheckableComboBox):
        combo.add_choice("Audio", 7, checked=False, enabled=True)
    else:
        combo.addItem("None", None)
        combo.addItem("Audio", 7)
    commits = QSignalSpy(delegate.commitData)
    closes = QSignalSpy(delegate.closeEditor)
    messages: list[str] = []
    previous = qInstallMessageHandler(
        lambda _kind, _context, message: messages.append(message)
    )
    try:
        combo.resize(360, 40)
        combo.show()
        combo.showPopup()
        APPLICATION.processEvents()
        view = combo.view()
        assert view.isVisible()
        if action == "select":
            index = combo.model().index(combo.count() - 1, 0)
            QTest.mouseClick(
                view.viewport(),
                Qt.MouseButton.LeftButton,
                pos=view.visualRect(index).center(),
            )
            if isinstance(combo, CheckableComboBox):
                assert combo.item(0).checkState() == Qt.CheckState.Checked
                assert view.isVisible()
                combo.hidePopup()
            else:
                assert combo.currentData() == 7
        elif action == "escape":
            QTest.keyClick(view, Qt.Key.Key_Escape)
        else:
            combo.hidePopup()
        APPLICATION.processEvents()
        assert not [
            message for message in messages if "does not belong to this view" in message
        ]
        assert not view.isVisible()
        assert commits.count() == 0
        assert closes.count() == 0
    finally:
        combo.hidePopup()
        combo.close()
        qInstallMessageHandler(previous)


def test_stream_delegate_preserves_real_editor_commit_and_close() -> None:
    combo = AppComboBox()
    delegate = StreamOptionDelegate(combo)
    combo.addItem("Before")
    commits = QSignalSpy(delegate.commitData)
    closes = QSignalSpy(delegate.closeEditor)
    try:
        combo.show()
        combo.showPopup()
        APPLICATION.processEvents()
        view = combo.view()
        index = combo.model().index(0, 0)
        view.edit(index)
        editor = view.findChild(QLineEdit)
        assert editor is not None
        editor.setText("After")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        APPLICATION.processEvents()

        assert combo.itemText(0) == "After"
        assert commits.count() == 1
        assert closes.count() == 1
    finally:
        combo.hidePopup()
        combo.close()


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
