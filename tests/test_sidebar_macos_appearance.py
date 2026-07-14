from PyQt6.QtWidgets import QLabel

from iopenpod.gui.styles import Colors, Design, Metrics
from iopenpod.gui.widgets.sidebar import Sidebar
from iopenpod.gui.widgets.sidebarNavButton import SidebarNavButton


def test_sidebar_uses_macos_source_list_metrics(qtbot) -> None:
    Metrics.apply_font_scale("100%")
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    sidebar.resize(Metrics.SIDEBAR_WIDTH, 900)
    sidebar.show()
    qtbot.wait(20)

    margins = sidebar.sidebarLayout.contentsMargins()
    assert (
        margins.left(),
        margins.top(),
        margins.right(),
        margins.bottom(),
    ) == (10, 10, 10, 10)

    album_button = sidebar.buttons["Albums"]
    assert album_button.font().pointSize() == Metrics.FONT_SIDEBAR
    assert album_button.iconSize().width() == Design.SIDEBAR_ICON_SIZE
    assert album_button.height() >= Design.SIDEBAR_ROW_HEIGHT

    section_labels = sidebar.findChildren(QLabel, "sidebarSectionLabel")
    library_label = next(label for label in section_labels if label.text() == "Library")
    assert library_label.font().pointSize() == Metrics.FONT_SIDEBAR_SECTION
    assert any(label.text() == "Maintenance" for label in section_labels)


def test_sidebar_selection_is_neutral_instead_of_accent_colored(qtbot) -> None:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    sidebar.show()
    sidebar.setLibraryTabsVisible(True)

    selected_css = sidebar.buttons["Albums"].styleSheet()
    assert isinstance(sidebar.buttons["Albums"], SidebarNavButton)
    assert sidebar.buttons["Albums"].isSelected()
    assert Colors.SURFACE_ACTIVE in selected_css
    assert f"color: {Colors.TEXT_PRIMARY}" in selected_css
    assert Colors.ACCENT_MUTED not in selected_css


def test_device_summary_is_a_single_contained_sidebar_surface(qtbot) -> None:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    card = sidebar.device_card
    assert card.objectName() == "deviceInfoCard"
    assert Colors.SURFACE_RAISED in card.styleSheet()
    assert Colors.BORDER_SUBTLE in card.styleSheet()
    card_layout = card.layout()
    assert card_layout is not None
    margins = card_layout.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
        12,
        12,
        12,
        10,
    )


def test_device_summary_uses_one_library_stat_line(qtbot) -> None:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    sidebar.device_card.update_stats(
        tracks=2_072,
        albums=0,
        size_bytes=0,
        duration_ms=128 * 3_600_000,
    )

    assert sidebar.device_card.library_summary_label.text() == "2,072 songs · 128 hours"
