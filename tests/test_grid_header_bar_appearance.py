from PyQt6.QtWidgets import QLabel, QLineEdit, QPushButton

from iopenpod.gui.styles import (
    BROWSER_SEARCH_CONTROL_SIZE,
    BROWSER_SEARCH_FIELD_WIDTH,
    Metrics,
    browser_search_field_css,
    paint_css,
)
from iopenpod.gui.widgets.gridHeaderBar import GridHeaderBar


def test_grid_header_matches_macos_browser_chrome(qtbot) -> None:
    header = GridHeaderBar()
    qtbot.addWidget(header)

    title = header.findChild(QLabel, "gridHeaderTitle")
    sort_button = header.findChild(QPushButton, "gridSortButton")
    search = header.findChild(QLineEdit, "gridSearchField")

    assert header.height() == 56
    assert title is not None
    assert title.text() == "Albums"
    assert title.font().pointSize() == Metrics.FONT_BROWSER_TITLE
    assert sort_button is not None
    assert sort_button.size().width() == sort_button.size().height() == 34
    assert sort_button.text() == ""
    assert sort_button.accessibleName() == "Sort: Name"
    assert search is not None
    assert (search.width(), search.height()) == (
        BROWSER_SEARCH_FIELD_WIDTH,
        BROWSER_SEARCH_CONTROL_SIZE,
    )
    assert search.styleSheet() == browser_search_field_css()
    assert search.placeholderText() == "Find in Albums"


def test_grid_header_category_updates_title_and_contextual_search(qtbot) -> None:
    header = GridHeaderBar()
    qtbot.addWidget(header)

    header.setCategory("Artists")

    title = header.findChild(QLabel, "gridHeaderTitle")
    search = header.findChild(QLineEdit, "gridSearchField")
    assert title is not None and title.text() == "Artists"
    assert search is not None and search.placeholderText() == "Find in Artists"


def test_grid_header_can_toggle_selected_item_grouping(qtbot) -> None:
    header = GridHeaderBar()
    qtbot.addWidget(header)
    toggle = header.findChild(QPushButton, "gridGroupBySelectedButton")

    assert toggle is not None
    assert toggle.isHidden()

    header.setSelectionGroupingAvailable(True)
    with qtbot.waitSignal(header.selection_grouping_changed) as signal:
        toggle.click()

    assert signal.args == [True]
    assert toggle.isChecked()
    assert toggle.accessibleName() == "Group by selected"
    assert paint_css("control.toggle.selected_fill") in toggle.styleSheet()
    assert paint_css("control.toggle.selected_border") in toggle.styleSheet()
