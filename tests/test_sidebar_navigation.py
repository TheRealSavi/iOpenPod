from PyQt6.QtWidgets import QVBoxLayout, QWidget

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
