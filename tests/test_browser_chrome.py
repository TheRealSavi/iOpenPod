from PyQt6.QtWidgets import QSplitter

from iopenpod.gui.styles import paint_css
from iopenpod.gui.widgets.browserChrome import (
    BrowserHeroHeader,
    BrowserPane,
    style_browser_splitter,
)


def test_browser_chrome_uses_active_resolved_theme_paints(qtbot) -> None:
    header = BrowserHeroHeader("Library")
    pane = BrowserPane("Albums")
    splitter = QSplitter()
    qtbot.addWidget(header)
    qtbot.addWidget(pane)
    qtbot.addWidget(splitter)

    style_browser_splitter(splitter)

    assert paint_css("surface.default") in header.styleSheet()
    assert paint_css("border.subtle") in header.styleSheet()
    assert paint_css("text.primary") in pane.title_label.styleSheet()
    assert paint_css("control.primary.fill") in splitter.styleSheet()
    assert paint_css("control.primary.hover_fill") in splitter.styleSheet()
