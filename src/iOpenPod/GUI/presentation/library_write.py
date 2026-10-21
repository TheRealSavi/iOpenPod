"""Shared Library preparation/save presentation for the bar and review dialog."""

from PySide6.QtCore import QCoreApplication

from iOpenPod.app.core.status import StatusMessage, StatusProgress
from iOpenPod.app.library_write import WriteProgress
from iOpenPod.app.library_write_controller import PreparationState
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text


def library_write_status(
    state: PreparationState, progress: WriteProgress | None
) -> StatusMessage | None:
    """Describe only a running stage; stage percentages are not overall completion."""
    if state not in (PreparationState.PREPARING, PreparationState.SAVING):
        return None
    saving = state is PreparationState.SAVING
    message = (
        QCoreApplication.translate("LibraryWriteStatus", "Saving Library changes…")
        if saving
        else QCoreApplication.translate(
            "LibraryWriteStatus", "Preparing Library changes…"
        )
    )
    value = StatusProgress()
    if progress is not None:
        message = workflow_text(progress.message)
        measured = (
            progress.completed is not None
            and progress.total is not None
            and progress.total > 0
        )
        value = StatusProgress(
            max(0, progress.completed or 0) if measured else 0,
            progress.total if measured and progress.total is not None else 0,
            progress.current_item,
        )
    warning = (
        QCoreApplication.translate("LibraryWriteStatus", "Do not disconnect your iPod")
        if saving
        else ""
    )
    return StatusMessage("library-write", message, value, safety_warning=warning)
