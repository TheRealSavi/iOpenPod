"""Phase estimates arrive as source-owned data and sit before the status bar."""

from PySide6.QtWidgets import QHBoxLayout
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.core.eta import EtaEstimate, EtaState
from iOpenPod.app.core.status import ApplicationStatus, StatusProgress
from iOpenPod.app.library_write import WriteProgress
from iOpenPod.app.library_write_controller import PreparationState
from iOpenPod.GUI.presentation.library_write import library_write_status
from iOpenPod.GUI.widgets.status_controls import StatusBarControls, StatusControls


def test_eta_flows_from_phase_to_bar_and_popup_then_clears_on_rotation() -> None:
    estimate = EtaEstimate(
        EtaState.ESTIMATING, 180_000, 360_000, 18, 10_000, 18, 10, 30
    )
    value = library_write_status(
        PreparationState.PREPARING,
        WriteProgress(
            "resources.phase",
            "Phase · Demucs · CUDA",
            3,
            4,
            "A song",
            "tracks",
            eta=estimate,
        ),
    )
    assert value is not None and value.progress is not None
    assert value.progress.eta is estimate
    status = ApplicationStatus()
    bar, popup = StatusBarControls(status), StatusControls(status)
    status.show(value.source, value.message, progress=value.progress)
    APPLICATION.processEvents()
    popup.set_status(value)
    for controls in (bar, popup):
        assert controls.eta.text() == "ETA: ~20s"
        assert "left in this stage" in controls.eta.toolTip()
        assert controls.progress.toolTip() == "A song"
        layout = controls.layout()
        assert isinstance(layout, QHBoxLayout)
        assert layout.indexOf(controls.eta) < layout.indexOf(controls.progress)
    status.show("other", "Other work", progress=StatusProgress())
    assert bar.eta.isHidden() and not bar.eta.text()
    status.clear("other")
    assert bar.eta.text() == "ETA: ~20s"
    status.clear(value.source)
    assert bar.eta.isHidden() and not bar.eta.toolTip()
    for controls in (bar, popup):
        controls.deleteLater()


def test_finalization_never_displays_zero_or_save_complete() -> None:
    value = library_write_status(
        PreparationState.SAVING,
        WriteProgress(
            "resources.phase",
            "Finishing analysis",
            4,
            4,
            eta=EtaEstimate(EtaState.COMPLETE, 4, 4, 40, remaining_seconds=0),
        ),
    )
    status = ApplicationStatus()
    controls = StatusControls(status)
    controls.set_status(value)
    assert controls.eta.text() == "Finishing…"
    assert controls.warning.text() == "Do not disconnect your iPod"
    controls.deleteLater()
