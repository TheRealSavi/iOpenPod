"""Scan progress retains translation templates separately from file names."""

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QLabel
from pytest import MonkeyPatch
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.display_text import source_text
from iOpenPod.GUI.sync_workspace import _ScanPage  # pyright: ignore[reportPrivateUsage]


def test_scan_retranslation_preserves_file_name_and_template_values(
    monkeypatch: MonkeyPatch,
) -> None:
    language = "first"

    def translate(context: str, source: str, *_args: object) -> str:
        if context == "Workflow" and source == "Scanning {count} files":
            return language + ": {count}"
        return source

    monkeypatch.setattr(QCoreApplication, "translate", translate)
    page = _ScanPage()
    try:
        page.set_progress(
            source_text("Scanning {count} files", count="5"),
            path="My {file}.mp3",
            completed=2,
            total=5,
        )
        detail = page.findChild(QLabel, "syncScanDetail")
        assert detail is not None
        assert detail.text() == "first: 5\nMy {file}.mp3"
        language = "second"
        page.retranslate_ui()
        assert detail.text() == "second: 5\nMy {file}.mp3"
    finally:
        page.deleteLater()
        APPLICATION.processEvents()
