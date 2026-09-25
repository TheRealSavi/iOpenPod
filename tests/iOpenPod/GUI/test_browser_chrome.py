"""Shared geometry and behavior for application browser chrome."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListView

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.browser_chrome import PageHeader, SourceListPanel


def test_page_header_owns_the_compact_title_and_action_rhythm() -> None:
    header = PageHeader()
    action = QLabel("Action", header)

    header.set_title("Photos")
    header.add_action(action)

    assert header.height() == LAYOUT.page_header_height
    assert header.minimumHeight() == LAYOUT.page_header_height
    assert header.maximumHeight() == LAYOUT.page_header_height
    assert header.property("pageHeader") is True
    assert header.title_label.text() == "Photos"
    assert header.title_label.accessibleName() == "Photos"
    assert header.title_label.property("browserTitle") is True
    layout = header.layout()
    assert layout is not None
    assert layout.indexOf(action) > layout.indexOf(header.title_label)


def test_source_list_panel_owns_rail_geometry_and_list_behavior() -> None:
    panel = SourceListPanel(236)
    view = QListView(panel)

    panel.set_title("PHOTO ALBUMS")
    panel.set_count(2)
    panel.set_view(view)

    assert panel.width() == 236
    assert panel.minimumWidth() == LAYOUT.source_list_minimum_width
    assert panel.maximumWidth() > 236
    assert panel.property("sourceListPanel") is True
    assert panel.title_label.text() == "PHOTO ALBUMS"
    assert panel.count_label.text() == "2"
    assert view.property("sourceList") is True
    assert view.property("sourceListStandardItems") is True
    assert view.accessibleName() == "PHOTO ALBUMS"
    assert view.horizontalScrollBarPolicy() is Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert view.verticalScrollMode() is QListView.ScrollMode.ScrollPerPixel

    with pytest.raises(RuntimeError, match="only one list view"):
        panel.set_view(QListView(panel))
