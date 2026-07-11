from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QProgressBar, QPushButton

from iopenpod.gui.widgets.sidebar import DeviceInfoCard


def test_database_storage_bar_uses_capability_limit(qtbot) -> None:
    card = DeviceInfoCard()
    qtbot.addWidget(card)

    card.update_database_storage_info(
        16 * 1024 * 1024,
        64 * 1024 * 1024,
        "iTunesDB",
    )

    bar = card.findChild(QProgressBar, "databaseStorageBar")
    assert bar is not None
    assert bar.value() == 25
    assert not bar.isHidden()
    assert "16.0 MB" in bar.toolTip()
    assert "64.0 MB" in bar.toolTip()


def test_database_storage_bars_request_manage_storage(qtbot) -> None:
    card = DeviceInfoCard()
    qtbot.addWidget(card)
    card.update_database_storage_info(
        16 * 1024 * 1024,
        64 * 1024 * 1024,
        "iTunesDB",
    )

    button = card.findChild(QPushButton, "storageManageButton")

    assert button is not None
    assert button.isEnabled()
    with qtbot.waitSignal(card.manage_storage_requested):
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
