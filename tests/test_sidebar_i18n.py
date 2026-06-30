from __future__ import annotations

from PyQt6.QtWidgets import QPushButton

from GUI.widgets.sidebar import Sidebar
from infrastructure.i18n import set_language


def _available_button_text_width(button: QPushButton) -> int:
    available = button.contentsRect().width() - 6
    if not button.icon().isNull():
        available -= button.iconSize().width() + 6
    return max(0, available)


def _button_text_fits(button: QPushButton) -> bool:
    return (
        button.fontMetrics().horizontalAdvance(button.text())
        <= _available_button_text_width(button) + 1
    )


def test_sidebar_half_width_actions_fit_french_and_spanish(qtbot) -> None:
    try:
        for language in ("fr", "es"):
            set_language(language)
            sidebar = Sidebar()
            qtbot.addWidget(sidebar)
            sidebar.show()
            qtbot.wait(50)

            assert _button_text_fits(sidebar.deviceButton)
            assert _button_text_fits(sidebar.rescanButton)
    finally:
        set_language("en")


def test_sidebar_half_width_actions_elide_extreme_labels(qtbot) -> None:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    sidebar.show()
    qtbot.wait(50)

    long_label = "Relancer l’analyse complète du périphérique"
    sidebar.rescanButton.set_compact_text(long_label)
    qtbot.wait(50)

    assert sidebar.rescanButton.toolTip() == long_label
    assert sidebar.rescanButton.text() != long_label
    assert _button_text_fits(sidebar.rescanButton)
