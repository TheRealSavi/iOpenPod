"""Skipped scan sources remain visible without unbounded GUI text."""

from pathlib import Path

from PySide6.QtWidgets import QLabel, QPlainTextEdit
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.display_text import source_text
from iOpenPod.app.host_media_library import HostMediaScanIssue
from iOpenPod.app.library_sync_helper import IPodMediaScanIssue
from iOpenPod.GUI.widgets.host_scan_issues import HostScanIssues
from iOpenPod.GUI.widgets.themed_buttons import ActionButton
from storage import HostPath


def test_scan_issue_details_are_bounded_plain_text_and_clearable(
    tmp_path: Path,
) -> None:
    panel = HostScanIssues()
    try:
        panel.load(
            tuple(
                HostMediaScanIssue(
                    HostPath(tmp_path / f"{index}.mp3"),
                    source_text(
                        "Symbolic link skipped because Follow symbolic links is disabled."
                    ),
                )
                for index in range(60)
            )
        )
        panel.show()
        APPLICATION.processEvents()
        summary = panel.findChild(QLabel)
        details = panel.findChild(QPlainTextEdit)
        toggle = panel.findChild(ActionButton)
        assert summary is not None and "60" in summary.text()
        assert panel.has_issues and details is not None and toggle is not None
        assert details.isHidden()
        toggle.click()
        assert details.isVisible()
        assert (
            "49.mp3" in details.toPlainText() and "50.mp3" not in details.toPlainText()
        )
        assert "Showing the first 50" in details.toPlainText()
        panel.load(())
        assert not panel.has_issues and details.isHidden()
    finally:
        panel.close()
        panel.deleteLater()
        APPLICATION.processEvents()


def test_scan_issues_include_ipod_subjects_and_plain_text(tmp_path: Path) -> None:
    panel = HostScanIssues()
    try:
        panel.load(
            (
                HostMediaScanIssue(HostPath(tmp_path / "host.mp3"), "Host unavailable"),
                IPodMediaScanIssue("Track <17>", "iPod file unavailable"),
                IPodMediaScanIssue("Host iPod analysis cache", "Cache unavailable"),
            )
        )
        summary = panel.findChild(QLabel)
        details = panel.findChild(QPlainTextEdit)
        assert summary is not None and "3" in summary.text()
        assert details is not None
        assert "host.mp3" in details.toPlainText()
        assert "Track <17>\niPod file unavailable" in details.toPlainText()
        assert "Host iPod analysis cache\nCache unavailable" in details.toPlainText()
    finally:
        panel.close()
        panel.deleteLater()
        APPLICATION.processEvents()
