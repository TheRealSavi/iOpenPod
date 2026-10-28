"""Slow Host scans explain cached imports without interrupting Sync."""

from collections.abc import Callable, Iterator

import pytest
from PySide6.QtCore import QEvent, Qt, QTimer, QTranslator
from PySide6.QtWidgets import QFrame, QLabel, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.sync_workspace import SyncWorkspace


@pytest.fixture
def workspace() -> Iterator[SyncWorkspace]:
    context = build_context()
    artwork = ArtworkPixmapProvider(context.artwork_controller)
    page = SyncWorkspace(context.settings, context.theme_manager, artwork)
    try:
        yield page
    finally:
        page.shutdown()
        artwork.shutdown()
        page.deleteLater()
        APPLICATION.sendPostedEvents(page, QEvent.Type.DeferredDelete)
        context.shutdown()


def _notice(workspace: SyncWorkspace) -> tuple[QFrame, QTimer]:
    notice = workspace.findChild(QFrame, "syncScanImportNotice")
    timer = workspace.findChild(QTimer, "syncScanImportNoticeTimer")
    assert notice is not None and timer is not None
    return notice, timer


def test_host_scan_shows_notice_after_ten_seconds_without_more_progress(
    workspace: SyncWorkspace,
) -> None:
    notice, timer = _notice(workspace)
    assert notice.isHidden() and not timer.isActive()
    workspace.show_scan("Finding media…")
    assert notice.isHidden() and timer.isActive()
    assert timer.interval() == 10_000
    assert timer.timerType() == Qt.TimerType.PreciseTimer
    assert timer.isSingleShot()
    timer_id = timer.timerId()
    workspace.update_scan("Reading music…", phase="host:reading", completed=1, total=10)
    workspace.update_scan("Checking files…", phase="host:validating")
    assert timer.timerId() == timer_id
    assert notice.isHidden()
    timer.timeout.emit()
    assert not notice.isHidden()
    title = notice.findChild(QLabel, "syncScanImportNoticeTitle")
    detail = notice.findChild(QLabel, "syncScanImportNoticeDetail")
    assert title is not None and title.text() == "Taking a while?"
    assert detail is not None and "cached" in detail.text()
    assert "next time" in detail.text() and "a few seconds" in detail.text()


@pytest.mark.parametrize(
    "finish",
    [
        SyncWorkspace.stop_scan,
        SyncWorkspace.show_selection,
        SyncWorkspace.clear,
        SyncWorkspace.shutdown,
    ],
)
@pytest.mark.parametrize("notice_shown", [False, True])
def test_scan_exit_clears_pending_or_visible_notice(
    workspace: SyncWorkspace,
    finish: Callable[[SyncWorkspace], None],
    notice_shown: bool,
) -> None:
    notice, timer = _notice(workspace)
    workspace.show_scan("Finding media…")
    if notice_shown:
        timer.timeout.emit()
    finish(workspace)
    assert notice.isHidden() and not timer.isActive()
    timer.timeout.emit()
    assert notice.isHidden()


def test_ipod_scan_has_no_import_notice_and_retry_starts_a_fresh_delay(
    workspace: SyncWorkspace,
) -> None:
    notice, timer = _notice(workspace)
    workspace.show_scan("Finding media…")
    timer.timeout.emit()
    workspace.show_scan("Comparing iPod media…", host_scan=False)
    assert notice.isHidden() and not timer.isActive()
    timer.timeout.emit()
    assert notice.isHidden()
    workspace.show_scan("Finding media again…")
    assert notice.isHidden() and timer.isActive()
    assert 0 < timer.remainingTime() <= 10_000
    timer.timeout.emit()
    assert not notice.isHidden()


def test_cancel_button_hides_notice_and_stops_delay(workspace: SyncWorkspace) -> None:
    notice, timer = _notice(workspace)
    workspace.show_scan("Finding media…")
    timer.timeout.emit()
    cancel = workspace.findChild(QPushButton, "cancelSyncScan")
    assert cancel is not None
    cancel.click()
    assert notice.isHidden() and not timer.isActive()


def test_scan_notice_retranslates_with_the_workspace(workspace: SyncWorkspace) -> None:
    notice, timer = _notice(workspace)
    workspace.show_scan("Finding media…")
    timer.timeout.emit()
    title = notice.findChild(QLabel, "syncScanImportNoticeTitle")
    detail = notice.findChild(QLabel, "syncScanImportNoticeDetail")
    assert title is not None and detail is not None
    source_title, source_detail = title.text(), detail.text()

    class Translator(QTranslator):
        def isEmpty(self) -> bool:
            return False

        def translate(
            self,
            context: str,
            source_text: str,
            /,
            disambiguation: str | None = None,
            n: int = -1,
        ) -> str | None:
            if context == "_ScanPage":
                return "Translated: " + source_text
            return None

    translator = Translator()
    assert APPLICATION.installTranslator(translator)
    try:
        workspace.retranslate_ui()
        assert title.text() == "Translated: " + source_title
        assert detail.text() == "Translated: " + source_detail
        assert not notice.isHidden()
    finally:
        APPLICATION.removeTranslator(translator)
