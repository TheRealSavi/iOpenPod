from PyQt6.QtWidgets import QVBoxLayout, QWidget

from iopenpod.gui.styles import (
    current_theme,
    paint_css,
    sidebar_item_view_css,
    sidebar_nav_state,
    sidebar_panel_css,
)
from iopenpod.gui.widgets.sidebarNavButton import SidebarNavButton


def test_sidebar_navigation_button_elides_long_labels(qtbot) -> None:
    full_text = "A very long photo or podcast collection name"
    button = SidebarNavButton(full_text)
    qtbot.addWidget(button)
    button.resize(140, 40)
    button.show()
    qtbot.wait(20)

    assert button.text() != full_text
    assert button.text().endswith("…")
    assert button.toolTip() == full_text


def test_sidebar_navigation_button_elides_inside_constrained_sidebar(qtbot) -> None:
    host = QWidget()
    layout = QVBoxLayout(host)
    button = SidebarNavButton("A very long photo album name")
    layout.addWidget(button)
    qtbot.addWidget(host)
    host.resize(150, 60)
    host.show()
    qtbot.wait(20)

    assert button.width() <= 150
    assert button.text().endswith("…")


def test_sidebar_navigation_button_owns_selected_glyph_state(qtbot) -> None:
    button = SidebarNavButton("Albums", icon_name="album")
    qtbot.addWidget(button)
    normal_icon_key = button.icon().cacheKey()

    button.setSelected(True)

    assert button.isSelected()
    assert button.icon().cacheKey() != normal_icon_key
    assert sidebar_nav_state(True).icon == paint_css("control.primary.fill")
    assert paint_css("surface.active") in button.styleSheet()


def test_sidebar_navigation_badge_reserves_trailing_space(qtbot) -> None:
    button = SidebarNavButton("Normalize Tags", icon_name="check-circle")
    qtbot.addWidget(button)
    button.resize(180, 32)
    button.setBadgeCount(42)
    button.show()
    qtbot.wait(20)

    assert button.badgeCount() == 42
    assert not button._badge_label.isHidden()
    assert button._badge_label.text() == "42"
    assert button._badge_label.geometry().right() < button.width()
    assert paint_css("control.primary.fill") in button._badge_label.styleSheet()
    assert paint_css("control.primary.text") in button._badge_label.styleSheet()


def test_item_view_sidebars_share_the_canonical_selected_state() -> None:
    css = sidebar_item_view_css()
    selected = sidebar_nav_state(True)

    assert selected.background in css
    assert selected.text in css
    assert "min-height: 32px" in css


def test_embedded_item_view_sidebar_does_not_paint_a_second_surface() -> None:
    css = sidebar_item_view_css(background="transparent")

    assert "background: transparent;" in css


def test_sidebar_helpers_use_the_active_resolved_theme_paints() -> None:
    selected = sidebar_nav_state(True)
    normal = sidebar_nav_state(False)
    panel_css = sidebar_panel_css("testSidebar")

    assert selected.background == paint_css("surface.active")
    assert selected.icon == paint_css("control.primary.fill")
    assert normal.hover_background == paint_css("surface.hover")
    assert normal.pressed_background == paint_css("surface.default")
    assert paint_css("chrome.sidebar.fill") in panel_css
    assert paint_css("border.subtle") in panel_css
    assert selected.background != current_theme().paint("selection.fill").css
