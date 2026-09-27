"""First-party failure templates survive capture while native details stay literal."""

from typing import Never

from PySide6.QtCore import QCoreApplication
from pytest import MonkeyPatch
from tests.iOpenPod.GUI.application_shell_test_support import build_context

from iOpenPod.app.backups.outcomes import CaptureFailed
from iOpenPod.app.backups.service import backup_failure_for
from iOpenPod.app.device_controller import DeviceOperation, DeviceOperationFailure
from iOpenPod.app.display_text import SourceText, source_text
from iOpenPod.app.services.device_coordinator import DeviceAccessError
from iOpenPod.app.sync_controller import (
    _KeepContentsWork,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.GUI.presentation.backup_messages import backup_message_for
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text


def test_nested_first_party_failure_translation_keeps_native_detail_literal(
    monkeypatch: MonkeyPatch,
) -> None:
    source = source_text(
        "The file {name} could not be opened: {detail}",
        name="My {file}.mp3",
        detail="Native {opaque} detail",
    )
    error = DeviceAccessError(source)

    def keep(_path: str) -> Never:
        raise error

    def translate(context: str, text: str, *_args: object) -> str:
        if context == "Workflow":
            return {
                "Could not finish keeping current contents. {detail}": "Behalten fehlgeschlagen. {detail}",
                "The file {name} could not be opened: {detail}": "Datei {name}: {detail}",
                "Native {opaque} detail": "Must not replace native text",
            }.get(text, text)
        return text

    monkeypatch.setattr(QCoreApplication, "translate", translate)
    work = _KeepContentsWork(keep, "journal.json")
    work.run()
    assert work.result is not None
    message = work.result.issues[0].message
    assert isinstance(message, SourceText)
    assert dict(message.parameters)["detail"] is source
    assert (
        workflow_text(message)
        == "Behalten fehlgeschlagen. Datei My {file}.mp3: Native {opaque} detail"
    )
    failure = backup_failure_for(error, operation="backup")
    assert failure.detail is source
    assert (
        "Datei My {file}.mp3: Native {opaque} detail"
        in backup_message_for(CaptureFailed(failure)).diagnostic_detail
    )


def test_device_failure_signal_keeps_source_template() -> None:
    context = build_context()
    controller = context.device_controller
    failures: list[DeviceOperationFailure] = []
    controller.operationFailed.connect(failures.append)
    source = source_text("The iPod {name} is not ready.", name="My {iPod}")
    error = DeviceAccessError(source)
    controller._active_token = 1  # pyright: ignore[reportPrivateUsage]
    try:
        controller._work_failed(1, DeviceOperation.SELECT, error)  # pyright: ignore[reportPrivateUsage]
        assert failures[0].message is source
        assert failures[0].error_type == "DeviceAccessError"
        assert error.args == (source,)
    finally:
        context.shutdown()
