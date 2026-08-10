from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton

from iopenpod.application.database_storage import DatabaseStorageReport, StorageBreakdownNode
from iopenpod.gui.styles import back_btn_css, paint_css
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
    assert paint_css("table.row.fill") in browser.tree.styleSheet()
    assert paint_css("table.row.selected_fill") in browser.tree.styleSheet()


def test_database_storage_browser_back_button_emits_closed(qtbot) -> None:
    browser = DatabaseStorageBrowser()
    qtbot.addWidget(browser)
    button = browser.findChild(QPushButton, "databaseStorageBackButton")

    assert button is not None
    assert button.text() == "\u2190"
    assert button.styleSheet() == back_btn_css()
    with qtbot.waitSignal(browser.closed):
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def test_database_storage_browser_adds_inspect_control_for_lyrics(qtbot) -> None:
    browser = DatabaseStorageBrowser()
    qtbot.addWidget(browser)
    report = DatabaseStorageReport(
        mode="classic",
        physical_bytes=2048,
        logical_bytes=2048,
        roots=(
            StorageBreakdownNode(
                "iTunesDB",
                2048,
                children=(
                    StorageBreakdownNode(
                        "Lyrics",
                        1024,
                        kind="mhod",
                        mhod_type=10,
                    ),
                ),
            ),
        ),
    )

    browser.load_report(report)
    button = browser.findChild(QPushButton, "databaseStorageInspectButton")

    assert button is not None
    assert button.text() == "Inspect…"
    with qtbot.waitSignal(browser.inspect_requested) as signal:
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert signal.args == [10, "Lyrics"]
