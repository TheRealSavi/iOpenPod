from __future__ import annotations

from pathlib import Path

import pytest

from iopenpod.gui.styles import make_scroll_area, paint_css, scrollbar_appearance, scrollbar_css
from iopenpod.gui.widgets.syncReview import SyncCategoryCard


def test_standard_scroll_area_does_not_install_local_scrollbar_qss(qtbot) -> None:
    scroll = make_scroll_area()
    qtbot.addWidget(scroll)

    assert scroll.styleSheet() == ""


def test_scroll_area_rejects_unmanaged_local_scrollbar_qss() -> None:
    with pytest.raises(ValueError, match="scrollbar_css"):
        make_scroll_area(extra_css="QScrollBar::handle:vertical { background: red; }")


def test_gui_package_has_no_raw_local_scrollbar_stylesheets() -> None:
    gui_root = Path(__file__).parents[1] / "src" / "iopenpod" / "gui"
    local_scrollbar_styles = [
        source.relative_to(gui_root)
        for source in gui_root.rglob("*.py")
        if source.name != "styles.py" and "QScrollBar" in source.read_text(encoding="utf-8")
    ]

    assert local_scrollbar_styles == []


def test_shared_scrollbar_qss_uses_the_appearance_contract() -> None:
    appearance = scrollbar_appearance()
    stylesheet = scrollbar_css(owner_selector="QListView#reviewRows")

    assert "QListView#reviewRows QScrollBar::handle:vertical" in stylesheet
    assert "QScrollBar:vertical::handle" not in stylesheet
    assert f"width: {appearance.width}px" in stylesheet
    assert f"min-height: {appearance.min_handle_extent}px" in stylesheet
    assert paint_css(appearance.thumb_paint) in stylesheet


def test_sync_review_accordion_uses_the_shared_scrollbar_qss(qtbot) -> None:
    card = SyncCategoryCard("plus", "Add Items", 1, "add")
    qtbot.addWidget(card)

    assert "QListView#syncReviewRowsView QScrollBar::handle:vertical" in card._rows_view.styleSheet()
