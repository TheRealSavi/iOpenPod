"""ETA presentation and real progress routes share the same stage estimator."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QTimer
from tests.iOpenPod.app.core.test_eta import Clock
from tests.iOpenPod.GUI.application_shell_test_support import build_context
from tests.iOpenPod.GUI.test_backup_page import build_backup_page

from iOpenPod.app.backups.models import BackupProgress, BackupStage
from iOpenPod.app.core.eta import EtaEstimate, EtaState
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.eta import eta_text
from iOpenPod.GUI.sync_workspace import SyncWorkspace
from iOpenPod.GUI.widgets.eta_label import EtaLabel

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtWidgets import QWidget


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    simulated = Clock()

    class TimedLabel(EtaLabel):
        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent, clock=simulated)

    monkeypatch.setattr("iOpenPod.GUI.pages.backup_page.EtaLabel", TimedLabel)
    monkeypatch.setattr("iOpenPod.GUI.sync_workspace.EtaLabel", TimedLabel)
    return simulated


def test_label_withdraws_stale_eta_without_another_progress_callback() -> None:
    clock = Clock()
    label = EtaLabel(clock=clock)
    timer = label.findChild(QTimer)
    assert timer is not None
    for index in range(10):
        label.set_progress("copy", index * 100, 10_000, unit="bytes")
        clock.advance()
    assert "left in this stage" in label.text()
    assert timer.isActive()
    clock.advance(30)
    timer.timeout.emit()
    assert label.text() == "Waiting for progress…"
    label.reset()
    assert not label.text()
    assert not timer.isActive()
    label.set_progress("copy", 1, 100)
    assert label.text() == "Estimating time for this stage…"


@pytest.mark.parametrize("stage", [BackupStage.CAPTURING, BackupStage.APPLYING])
def test_backups_and_restore_show_eta_and_reset_on_terminal_busy_change(
    tmp_path: Path,
    clock: Clock,
    stage: BackupStage,
) -> None:
    page, controller = build_backup_page(tmp_path)
    label = page.findChild(EtaLabel, "backupProgressEta")
    assert label is not None
    controller.busyChanged.emit(True)
    for index in range(10):
        # Capture reports byte chunks before the first large file completes.
        controller.progressChanged.emit(
            BackupProgress(
                stage,
                0 if stage is BackupStage.CAPTURING else index,
                100,
                "Working…",
                completed_bytes=index * 100,
                total_bytes=10_000 if stage is BackupStage.CAPTURING else 0,
            )
        )
        clock.advance()
    assert "left in this stage" in label.text()
    controller.busyChanged.emit(False)
    assert not label.text()
    timer = label.findChild(QTimer)
    assert timer is not None and not timer.isActive()
    controller.busyChanged.emit(True)
    controller.progressChanged.emit(BackupProgress(stage, 0, 100, "Restarting…"))
    assert label.text() == "Estimating time for this stage…"


def test_backup_finalization_does_not_claim_a_success_or_reuse_copy_eta(
    tmp_path: Path,
    clock: Clock,
) -> None:
    page, controller = build_backup_page(tmp_path)
    label = page.findChild(EtaLabel, "backupProgressEta")
    assert label is not None
    for index in range(10):
        controller.progressChanged.emit(
            BackupProgress(BackupStage.APPLYING, index, 100, "Restoring…")
        )
        clock.advance()
    controller.progressChanged.emit(
        BackupProgress(BackupStage.FINALIZING, 100, 100, "Flushing…")
    )
    assert not label.text()


def test_sync_scan_stage_change_discards_host_rate_before_ipod_scan(
    clock: Clock,
) -> None:
    context = build_context()
    workspace = SyncWorkspace(
        context.settings,
        context.theme_manager,
        ArtworkPixmapProvider(context.artwork_controller),
    )
    try:
        label = workspace.findChild(EtaLabel, "syncScanEta")
        assert label is not None
        workspace.show_scan("Reading…")
        for index in range(10):
            workspace.update_scan(
                "Reading…", completed=index, total=100, phase="host:reading"
            )
            clock.advance()
        assert "left in this stage" in label.text()
        workspace.update_scan(
            "Inspecting…", completed=9, total=100, phase="ipod:tracks"
        )
        assert label.text() == "Estimating time for this stage…"
        workspace.update_scan("Discovering…", phase="discovering")
        assert not label.text()
    finally:
        workspace.close()
        workspace.deleteLater()
        context.shutdown()


def test_unknown_and_complete_are_not_confused_and_small_estimates_never_say_zero() -> (
    None
):
    unknown = EtaEstimate(EtaState.UNKNOWN_TOTAL, 0, None, 0)
    assert not eta_text(unknown)
    complete = EtaEstimate(EtaState.COMPLETE, 1, 1, 1, remaining_seconds=0)
    assert eta_text(complete) == "Finishing this stage…"
    tiny = EtaEstimate(EtaState.ESTIMATING, 9, 10, 1, 100, 0.1, 0.08, 0.15)
    assert eta_text(tiny) == "About 5s left in this stage"


def test_uncertain_forecast_is_presented_as_a_range() -> None:
    estimate = EtaEstimate(EtaState.ESTIMATING, 1, 100, 10, 1, 99, 60, 180)
    assert eta_text(estimate) == "About 1m to 3m left in this stage"
