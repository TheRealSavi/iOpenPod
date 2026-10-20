"""Multi-selection dropdowns support mouse and keyboard without losing choices."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.GUI.widgets.checkable_combo_box import CheckableComboBox


def test_popup_toggles_multiple_rows_and_closes_without_changing_choices() -> None:
    combo = CheckableComboBox()
    combo.add_choice("English", 2, checked=True, enabled=True)
    combo.add_choice("Signs and songs", 3, checked=False, enabled=True)
    combo.add_choice("Unsupported", 4, checked=False, enabled=False)
    try:
        combo.resize(320, 40)
        combo.show()
        QTest.keyClick(combo, Qt.Key.Key_Space)
        APPLICATION.processEvents()
        view = combo.view()
        assert view.isVisible()
        index = combo.model().index(1, 0)
        QTest.mouseClick(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=view.visualRect(index).center(),
        )
        assert combo.item(1).checkState() == Qt.CheckState.Checked
        assert view.isVisible()
        assert combo.selection_text() == "2 selected"
        assert combo.toolTip() == "English\nSigns and songs"
        QTest.keyClick(view, Qt.Key.Key_Space)
        assert combo.selection_text() == "English"
        assert view.isVisible()
        blocked = combo.model().index(2, 0)
        QTest.mouseClick(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=view.visualRect(blocked).center(),
        )
        assert combo.item(2).checkState() == Qt.CheckState.Unchecked
        view.setCurrentIndex(combo.model().index(0, 0))
        QTest.keyClick(view, Qt.Key.Key_Space)
        assert combo.selection_text() == "None"
        QTest.keyClick(view, Qt.Key.Key_Escape)
        assert not view.isVisible()
        QTest.keyClick(combo, Qt.Key.Key_Down)
        assert view.isVisible()
        QTest.keyClick(view, Qt.Key.Key_Return)
        assert not view.isVisible()
        assert combo.selection_text() == "None"
    finally:
        combo.hidePopup()
        combo.close()


def test_empty_dropdown_explains_absence() -> None:
    combo = CheckableComboBox()
    combo.setPlaceholderText("No separate streams found")
    combo.setEnabled(False)
    assert combo.selection_text() == "No separate streams found"
    assert not combo.isEnabled()
    combo.close()
