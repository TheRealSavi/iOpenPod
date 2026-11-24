"""GUI-thread state and exclusive device ownership for the unlock wizard."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from queue import Empty, SimpleQueue
from threading import Event, Thread
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QObject, QTimer, Signal

from storage import StorageError, UsbControlDriverError

from .bootloader_install import (
    UnlockIdentity,
    UnlockProgress,
    UnlockStage,
    supported_identity,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.models.device import ActiveIPod


class UnlockInstaller(Protocol):
    @property
    def platform(self) -> str: ...
    def pending_identity(self) -> UnlockIdentity | None: ...
    def run(
        self,
        identity: UnlockIdentity,
        cancel: Event,
        publish: Callable[[UnlockProgress], None],
        *,
        verify_only: bool = False,
    ) -> bool: ...


@dataclass(frozen=True)
class _Finished:
    progress: UnlockProgress


class BootloaderController(QObject):
    changed = Signal()

    def __init__(
        self,
        installer: UnlockInstaller,
        devices: DeviceController,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._installer = installer
        self._devices = devices
        self._progress = UnlockProgress()
        self._identity: UnlockIdentity | None = None
        self._pending = self._read_pending()
        self._events: SimpleQueue[UnlockProgress | _Finished] = SimpleQueue()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)
        devices.activeIPodChanged.connect(self._active_changed)

    @property
    def platform(self) -> str:
        return self._installer.platform

    @property
    def progress(self) -> UnlockProgress:
        return self._progress

    @property
    def busy(self) -> bool:
        return self._thread is not None

    @property
    def can_cancel(self) -> bool:
        return self.busy and self._progress.stage in (
            UnlockStage.WAITING_DFU,
            UnlockStage.CHECKING,
        )

    def supported(self, active: ActiveIPod | None) -> bool:
        return supported_identity(active, self._installer.platform) is not None

    @property
    def pending(self) -> UnlockIdentity | None:
        return self._pending

    def _read_pending(self) -> UnlockIdentity | None:
        try:
            return self._installer.pending_identity()
        except (ValueError, KeyError, OSError, StorageError):
            logging.getLogger(__name__).exception(
                "Could not read bootloader installation receipt"
            )
            return None

    @property
    def can_resume(self) -> bool:
        return not self.busy and self._pending is not None

    def prepare(self) -> None:
        if not self.busy:
            self._progress = UnlockProgress()
            self.changed.emit()

    def start(self, active: ActiveIPod) -> bool:
        identity = supported_identity(active, self._installer.platform)
        if (
            self._closed
            or self.busy
            or identity is None
            or not self._devices.prepare_firmware_mode_change(active)
        ):
            return False
        self._identity = identity
        self._launch(identity, verify_only=False)
        return True

    def resume(self) -> bool:
        identity = self._pending
        if self._closed or self.busy or identity is None:
            return False
        active = self._devices.active_ipod
        if active is not None:
            if (
                active.serial_number != identity.serial
                or not self._devices.prepare_firmware_mode_change(active)
            ):
                return False
        elif not self._devices.begin_recovery_operation():
            return False
        self._identity = identity
        self._launch(identity, verify_only=True)
        return True

    def _launch(self, identity: UnlockIdentity, *, verify_only: bool) -> None:
        self._cancel = Event()
        self._progress = UnlockProgress(UnlockStage.WAITING_DFU)

        def work() -> None:
            try:
                already = self._installer.run(
                    identity, self._cancel, self._events.put, verify_only=verify_only
                )
                result = UnlockProgress(UnlockStage.RESTART, already_unlocked=already)
            except InterruptedError:
                result = UnlockProgress(UnlockStage.CANCELED)
            except UsbControlDriverError:
                result = UnlockProgress(
                    UnlockStage.ERROR,
                    detail=(
                        "Windows could not open the iPod in DFU mode. Install Apple's "
                        "iPod device support included with iTunes, reconnect the iPod, "
                        "and reopen setup. iOpenPod includes libusb but does not install "
                        "a Windows USB driver."
                    ),
                )
            except Exception as error:
                result = UnlockProgress(UnlockStage.ERROR, detail=str(error))
            self._events.put(_Finished(result))

        self._thread = Thread(
            target=work, name="iOpenPod bootloader installer", daemon=False
        )
        self._thread.start()
        self._timer.start()
        self.changed.emit()

    def cancel(self) -> None:
        if self.can_cancel:
            self._cancel.set()

    def _poll(self) -> None:
        while True:
            try:
                event = self._events.get_nowait()
            except Empty:
                return
            if isinstance(event, _Finished):
                if self._thread is not None:
                    self._thread.join()
                self._thread = None
                self._progress = event.progress
                self._pending = self._read_pending()
                self._timer.stop()
                self._devices.finish_exclusive_operation()
                self._devices.refresh_devices()
            else:
                self._progress = event
            self.changed.emit()

    def _active_changed(self, active: ActiveIPod | None) -> None:
        if (
            self._progress.stage is UnlockStage.RESTART
            and active is not None
            and self._identity == supported_identity(active, self._installer.platform)
        ):
            self._progress = UnlockProgress(
                UnlockStage.COMPLETE, already_unlocked=self._progress.already_unlocked
            )
            self.changed.emit()

    def shutdown(self) -> None:
        self._closed = True
        self._cancel.set()
        if self._thread is not None:
            # The service honors cancellation only before its durable handoff.
            # A process shutdown must never detach a live flash writer.
            self._thread.join()
            self._poll()
        self._timer.stop()
