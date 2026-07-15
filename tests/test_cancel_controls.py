from types import SimpleNamespace
from typing import Any, cast

from iopenpod.gui.widgets.backupBrowser import BackupBrowserWidget
from iopenpod.gui.widgets.devicePicker import DevicePickerDialog


class _FakeButton:
    def __init__(self) -> None:
        self.enabled: bool | None = None
        self.text = ""

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setText(self, text: str) -> None:
        self.text = text


class _FakeLabel:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


class _FakeWorker:
    def __init__(self, *, running: bool = True) -> None:
        self._running = running
        self.request_count = 0

    def isRunning(self) -> bool:
        return self._running

    def requestInterruption(self) -> None:
        self.request_count += 1


class _FakeSignal:
    def __init__(self) -> None:
        self.disconnect_count = 0

    def disconnect(self) -> None:
        self.disconnect_count += 1


class _FakeScanThread(_FakeWorker):
    def __init__(self, *, running: bool = True) -> None:
        super().__init__(running=running)
        self.finished = _FakeSignal()
        self.error = _FakeSignal()
        self.delete_later_count = 0

    def deleteLater(self) -> None:
        self.delete_later_count += 1


def test_backup_cancel_is_one_shot_with_immediate_feedback() -> None:
    worker = _FakeWorker(running=True)
    cancel_btn = _FakeButton()
    title = _FakeLabel()
    detail = _FakeLabel()
    widget = SimpleNamespace(
        _backup_worker=worker,
        _restore_worker=None,
        _progress_cancel_btn=cancel_btn,
        _progress_title=title,
        _progress_file=detail,
    )

    BackupBrowserWidget._on_cancel(cast(Any, widget))

    assert worker.request_count == 1
    assert cancel_btn.enabled is False
    assert cancel_btn.text == "Cancelling..."
    assert title.text == "Cancelling"
    assert "stop safely" in detail.text


def test_device_picker_cancel_detaches_active_scan_thread() -> None:
    worker = _FakeScanThread(running=True)
    dialog = SimpleNamespace(_scan_thread=worker, _scan_orphan_threads=[])
    dialog._retain_scan_thread = DevicePickerDialog._retain_scan_thread.__get__(dialog)
    dialog._reap_scan_thread = DevicePickerDialog._reap_scan_thread.__get__(dialog)

    DevicePickerDialog._cleanup_scan_thread(cast(Any, dialog))

    assert worker.request_count == 1
    assert worker.finished.disconnect_count == 1
    assert worker.error.disconnect_count == 1
    assert dialog._scan_thread is None
    assert dialog._scan_orphan_threads == [worker]


def test_device_picker_stale_scan_completion_after_cancel_is_ignored() -> None:
    worker = _FakeScanThread(running=False)
    dialog = SimpleNamespace(_scan_thread=None)

    DevicePickerDialog._on_scan_complete(cast(Any, dialog), [], worker)

    assert dialog._scan_thread is None
