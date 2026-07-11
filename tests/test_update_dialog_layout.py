from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QFrame, QPushButton

from iopenpod.gui.auto_updater import InstallMethod, UpdateResult
from iopenpod.gui.widgets import updateDialog


def _source_checkout_method() -> InstallMethod:
    return InstallMethod(
        "source_checkout",
        "Source checkout",
        "Pull the latest source and sync the development environment.",
    )


def _make_update_dialog() -> updateDialog.UpdateAvailableDialog:
    return updateDialog.UpdateAvailableDialog(
        UpdateResult(
            update_available=True,
            current_version="1.0.64",
            latest_version="1.0.65",
            release_notes="## Changes\n\n"
            + "- Improved updater layout and install guidance.\n" * 14,
        ),
        method=_source_checkout_method(),
        platform="linux",
    )


def _button_with_text(dialog: updateDialog.UpdateAvailableDialog, text: str) -> QPushButton:
    for button in dialog.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"Could not find button with text {text!r}")


def _lay_out(dialog: updateDialog.UpdateAvailableDialog, width: int, height: int) -> None:
    dialog.resize(width, height)
    dialog.show()
    QApplication.processEvents()


def test_update_available_dialog_keeps_footer_visible_when_resized_short(
    qtbot,
) -> None:
    dialog = _make_update_dialog()
    qtbot.addWidget(dialog)

    _lay_out(dialog, 660, 520)

    later_button = _button_with_text(dialog, "Later")
    later_bottom = later_button.mapTo(dialog, later_button.rect().bottomLeft()).y()

    assert later_bottom <= dialog.rect().bottom()


def test_update_available_dialog_does_not_stretch_command_panel_when_resized_tall(
    qtbot,
) -> None:
    dialog = _make_update_dialog()
    qtbot.addWidget(dialog)

    _lay_out(dialog, 700, 620)
    command_panel = dialog.findChild(QFrame, "UpdateCommandPanel")
    assert command_panel is not None
    compact_height = command_panel.height()

    _lay_out(dialog, 1000, 900)

    assert command_panel.height() <= compact_height + 4
