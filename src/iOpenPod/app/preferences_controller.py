"""Background inspection and explicit publication of firmware Preferences."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app import developer_flags
from iOpenPod.app.core.status import StatusProgress
from iOpenPod.app.display_text import exception_text
from iOpenPod.app.models.ipod_preferences import (
    IPodPreferenceEdit,
    IPodPreferencesCatalog,
)
from iOpenPod.app.services.device_coordinator import SyncRecoveryRequiredError

if TYPE_CHECKING:
    from iOpenPod.app.core.status import ApplicationStatus
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator

_LOGGER = logging.getLogger(__name__)
_STATUS = "preferences.write"


class _Signals(QObject):
    completed = Signal(object, object)


class _Work(QRunnable):
    def __init__(
        self,
        coordinator: DeviceCoordinator,
        active: ActiveIPod,
        catalog: IPodPreferencesCatalog,
        changes: tuple[IPodPreferenceEdit, ...] | None = None,
    ) -> None:
        super().__init__()
        self.coordinator = coordinator
        self.active = active
        self.catalog = catalog
        self.changes = changes
        self.cancelled = threading.Event()
        self.signals = _Signals()

    def run(self) -> None:
        outcome: IPodPreferencesCatalog | Exception
        try:
            if self.changes is None:
                outcome = self.coordinator.load_preferences(self.active, self.cancelled)
            else:
                outcome = self.coordinator.save_preferences(
                    self.active, self.catalog, self.changes, self.cancelled
                )
        except Exception as error:
            outcome = error
        self.signals.completed.emit(self, outcome)


class PreferencesController(QObject):
    """Only issued captures can be saved; optional errors never gate the Library."""

    changed = Signal()
    saved = Signal()

    def __init__(
        self,
        coordinator: DeviceCoordinator,
        devices: DeviceController,
        parent: QObject | None = None,
        *,
        status: ApplicationStatus,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._devices = devices
        self._status = status
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._job: _Work | None = None
        self._catalog = IPodPreferencesCatalog()
        self._loaded_for: ActiveIPod | None = None
        self._message = ""
        self._closed = False
        self._requested = False
        devices.activeIPodChanged.connect(self._device_changed)
        devices.deviceWritesAllowedChanged.connect(self._availability_changed)

    @property
    def active_ipod(self) -> ActiveIPod | None:
        return self._devices.active_ipod

    @property
    def catalog(self) -> IPodPreferencesCatalog:
        return self._catalog

    @property
    def busy(self) -> bool:
        return self._job is not None

    @property
    def message(self) -> str:
        return self._message

    @property
    def can_write(self) -> bool:
        return (
            developer_flags.ENABLE_IPOD_PREFERENCES_WRITES
            and not self._closed
            and not self.busy
            and self.active_ipod is not None
            and self.active_ipod is self._loaded_for
            and self._devices.device_writes_allowed
            and self._catalog.document is not None
            and self._catalog.fingerprint is not None
            and any(
                row.edit is not None
                for section in self._catalog.sections
                for row in section.rows
            )
        )

    def refresh(self) -> None:
        self._requested = True
        active = self.active_ipod
        if self._closed or self.busy or active is None:
            return
        if not self._devices.begin_read_only_operation():
            return
        self._start(_Work(self._coordinator, active, self._catalog))

    def save(self, changes: tuple[IPodPreferenceEdit, ...]) -> bool:
        active = self.active_ipod
        if active is None or not changes or not self.can_write:
            return False
        if not self._devices.begin_exclusive_operation():
            return False
        self._status.show(
            _STATUS, self.tr("Saving iPod preferences…"), progress=StatusProgress()
        )
        self._start(_Work(self._coordinator, active, self._catalog, changes))
        return True

    def _start(self, job: _Work) -> None:
        self._job = job
        self._message = ""
        job.signals.completed.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        self.changed.emit()
        self._pool.start(job)

    @Slot(object, object)
    def _completed(self, job: object, outcome: object) -> None:
        if self._closed or job is not self._job or not isinstance(job, _Work):
            return
        current = self.active_ipod is job.active
        # Keep busy set while releasing: availability signals must not start a
        # replacement job before this completion has installed its catalog.
        if job.changes is None:
            self._devices.finish_read_only_operation()
        else:
            if current and isinstance(outcome, SyncRecoveryRequiredError):
                self._devices.set_recovery_required(True)
            self._devices.finish_exclusive_operation()
        self._job = None
        self._status.clear(_STATUS)
        if current:
            if isinstance(outcome, IPodPreferencesCatalog):
                self._catalog = outcome
                self._loaded_for = job.active
                if job.changes is not None:
                    self.saved.emit()
            else:
                self._message = (
                    exception_text(outcome)
                    if isinstance(outcome, BaseException)
                    else str(outcome)
                )
                _LOGGER.warning("Preferences operation failed: %s", outcome)
        self.changed.emit()
        if not current and self._requested:
            self.refresh()

    @Slot(object)
    def _device_changed(self, active: object) -> None:
        if active is self._loaded_for and active is not None:
            self.changed.emit()
            return
        if self._job is not None:
            self._job.cancelled.set()
        self._catalog = IPodPreferencesCatalog()
        self._loaded_for = None
        self._message = ""
        self.changed.emit()
        if self._requested:
            self.refresh()

    @Slot(bool)
    def _availability_changed(self, allowed: bool) -> None:
        self.changed.emit()
        if allowed and self._requested and self._loaded_for is None and not self.busy:
            self.refresh()

    def shutdown(self) -> None:
        self._closed = True
        if self._job is not None:
            self._job.cancelled.set()
        self._pool.waitForDone()
        if self._job is not None:
            if self._job.changes is None:
                self._devices.finish_read_only_operation()
            else:
                self._devices.finish_exclusive_operation()
        self._job = None
        self._status.clear(_STATUS)
