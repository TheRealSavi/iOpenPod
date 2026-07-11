from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton

from iopenpod.application.database_storage import DatabaseStorageReport, StorageBreakdownNode
from iopenpod.gui.styles import back_btn_css
from iopenpod.gui.widgets.databaseStorageBrowser import DatabaseStorageBrowser


def test_database_storage_browser_summary_describes_sqlite_storage(qtbot) -> None:
    browser = DatabaseStorageBrowser()
    qtbot.addWidget(browser)
    report = DatabaseStorageReport(
        mode="sqlite",
        physical_bytes=2048,
        logical_bytes=2048,
        roots=(
            StorageBreakdownNode(
                "SQLite databases",
                2048,
                children=(StorageBreakdownNode("Library.itdb", 2048),),
            ),
        ),
    )

    browser.load_report(report, max_database_bytes=4096)
    summary = browser.findChild(QLabel, "databaseStorageSummary")

    assert summary is not None
    assert summary.text() == "SQLite library · 2.0 KB across .itdb files"
    assert "RAM budget" not in summary.text()
    assert "iTunesCDB" not in summary.text()


def test_database_storage_browser_back_button_emits_closed(qtbot) -> None:
    browser = DatabaseStorageBrowser()
    qtbot.addWidget(browser)
    button = browser.findChild(QPushButton, "databaseStorageBackButton")

    assert button is not None
    assert button.text() == "\u2190"
    assert button.styleSheet() == back_btn_css()
    with qtbot.waitSignal(browser.closed):
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
