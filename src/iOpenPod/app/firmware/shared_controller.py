"""Background shared-firmware installation with completion after upload."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from queue import Empty, SimpleQueue
from threading import Event, Thread
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QObject, QTimer, Signal

from storage import StorageError

from .bootloader_install import UnlockIdentity, supported_identity
from .bootloader_report import require_reported_bootloader
from .shared_install import (
    InstallProgress,
    InstallStage,
)
from .shared_records import PENDING_STATES, InstallRecord
from .shared_release import MOD_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator
    from storage import MountedVolume


class FirmwareInstaller(Protocol):
    @property
    def platform(self) -> str: ...
    @property
    def upload_supported(self) -> bool: ...
    def pending_identity(self) -> UnlockIdentity | None: ...
    def record(self, identity: UnlockIdentity) -> InstallRecord | None: ...
    def require_bootloader(self, identity: UnlockIdentity) -> int: ...
    def install(
        self,
        identity: UnlockIdentity,
        mounted: MountedVolume,
        cancel: Event,
        publish: Callable[[InstallProgress], None],
    ) -> None: ...


@dataclass(frozen=True)
class _Finished:
    progress: InstallProgress


class SharedFirmwareController(QObject):
    changed = Signal()

    def __init__(
        self,
        installer: FirmwareInstaller,
        devices: DeviceController,
        coordinator: DeviceCoordinator,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._installer = installer
        self._devices = devices
        self._coordinator = coordinator
        self._progress = InstallProgress()
        self._mod_version = MOD_VERSION
        self._pending = self._read_pending()
        self._events: SimpleQueue[InstallProgress | _Finished] = SimpleQueue()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)

    @property
    def progress(self) -> InstallProgress:
        return self._progress

    @property
    def mod_version(self) -> str:
        """Release being installed, captured outside GUI rendering."""
        return self._mod_version

    @property
    def busy(self) -> bool:
        return self._thread is not None

    @property
    def can_cancel(self) -> bool:
        return self.busy and self._progress.stage in (
            InstallStage.PREPARING,
            InstallStage.CHECKING,
        )

    @property
    def pending(self) -> UnlockIdentity | None:
        return self._pending

    @property
    def needs_attention(self) -> bool:
        return not self.busy and self._pending is not None

    @property
    def upload_supported(self) -> bool:
        return self._installer.upload_supported

    def supported(self, active: ActiveIPod | None) -> bool:
        return (
            self.upload_supported
            and supported_identity(active, self._installer.platform) is not None
        )

    def recorded_hardware_family(self, active: ActiveIPod | None) -> int | None:
        identity = supported_identity(active, self._installer.platform)
        if identity is None:
            return None
        try:
            return self._installer.require_bootloader(identity)
        except (ValueError, OSError, StorageError):
            return None

    def has_bootloader_record(self, active: ActiveIPod | None) -> bool:
        return self.recorded_hardware_family(active) is not None

    def can_install(self, active: ActiveIPod | None) -> bool:
        if active is None or not self.supported(active):
            return False
        if active.bootloader_report is not None:
            identity = supported_identity(active, self._installer.platform)
            if identity is None:
                return False
            try:
                require_reported_bootloader(
                    active.bootloader_report,
                    serial=identity.serial,
                    model=identity.model,
                )
            except ValueError:
                return False
            qualified = True
        else:
            qualified = self.has_bootloader_record(active)
        return (
            bool(active.firmware_version)
            and active.updater_family_id is not None
            and active.firmware_version_current
            and active.updater_family_current
            and qualified
        )

    def _read_pending(self) -> UnlockIdentity | None:
        try:
            return self._installer.pending_identity()
        except Exception:
            logging.getLogger(__name__).exception(
                "Could not read pending firmware installation"
            )
            return None

    def prepare(self, active: ActiveIPod | None) -> None:
        if self.busy:
            return
        self._pending = self._read_pending()
        self._progress = InstallProgress()
        self._mod_version = MOD_VERSION
        if self._pending is not None:
            self._progress = InstallProgress(
                InstallStage.ERROR,
                detail="The previous firmware upload was interrupted. DFU recovery is required.",
            )
        self.changed.emit()

    def start(self, active: ActiveIPod) -> bool:
        identity = supported_identity(active, self._installer.platform)
        if (
            self._closed
            or self.busy
            or identity is None
            or not self.can_install(active)
        ):
            return False
        record = self._installer.record(identity)
        if record is not None and record.state in PENDING_STATES:
            self._pending = identity
            self.prepare(active)
            return False
        mounted = self._coordinator.firmware_volume(active)
        if not self._devices.prepare_firmware_mode_change(active):
            return False
        self._mod_version = MOD_VERSION
        self._launch(
            lambda: self._installer.install(
                identity, mounted, self._cancel, self._events.put
            ),
            InstallStage.PREPARING,
            InstallStage.COMPLETE,
        )
        return True

    def _launch(
        self,
        work: Callable[[], None],
        initial: InstallStage,
        final: InstallStage,
    ) -> None:
        self._cancel = Event()
        self._progress = InstallProgress(initial)

        def run() -> None:
            try:
                work()
                result = InstallProgress(final)
            except InterruptedError:
                result = InstallProgress(InstallStage.CANCELED)
            except Exception as error:
                result = InstallProgress(InstallStage.ERROR, detail=str(error))
            self._events.put(_Finished(result))

        self._thread = Thread(
            target=run, name="iOpenPod firmware installer", daemon=False
        )
        self._thread.start()
        self._timer.start()
        self.changed.emit()

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

    def cancel(self) -> None:
        if self.can_cancel:
            self._cancel.set()

    def shutdown(self) -> None:
        self._closed = True
        self._cancel.set()
        if self._thread is not None:
            self._thread.join()
            self._poll()
        self._timer.stop()
