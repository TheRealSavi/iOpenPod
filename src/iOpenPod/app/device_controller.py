"""Qt adapter for non-blocking Application Layer device workflows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot

from iOpenPod.app.core.settings.definitions import (
    LAST_SELECTED_IPOD_VOLUME_ID,
    MANAGE_VOLUME_PRESENTATION,
)
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidateId,
    DeviceDiscovery,
)
from iOpenPod.app.services.device_coordinator import SyncRecoveryRequiredError
from storage import VolumeId

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.models.track_table_model import TrackTableModel
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator


_AUTO_REFRESH_INTERVAL_MS = 2_000
logger = logging.getLogger(__name__)


class DeviceOperation(StrEnum):
    DISCOVER = "discover"
    SELECT = "select"
    EJECT = "eject"


@dataclass(frozen=True, slots=True)
class DeviceOperationFailure:
    operation: DeviceOperation
    message: str
    error_type: str


@dataclass(frozen=True, slots=True)
class DeviceEjectCompletion:
    display_name: str
    detail: str


class _WorkerSignals(QObject):
    succeeded = Signal(int, object, object)
    failed = Signal(int, object, object)
    finished = Signal(int)


class _DeviceWork(QRunnable):
    def __init__(
        self,
        token: int,
        operation: DeviceOperation,
        work: Callable[[], object],
    ) -> None:
        super().__init__()
        self.token = token
        self.operation = operation
        self.work = work
        self.signals = _WorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self.work()
        except Exception as error:
            self.signals.failed.emit(self.token, self.operation, error)
        else:
            self.signals.succeeded.emit(self.token, self.operation, result)
        finally:
            self.signals.finished.emit(self.token)


class DeviceController(QObject):
    """Run device I/O away from Qt's GUI thread and publish immutable results."""

    discoveryChanged = Signal(object)
    activeIPodChanged = Signal(object)
    busyChanged = Signal(bool)
    searchingChanged = Signal(bool)
    discoveryErrorChanged = Signal(str)
    deviceWritesAllowedChanged = Signal(bool)
    operationFailed = Signal(object)
    librarySaved = Signal(object)
    ejectStarted = Signal()
    ejectCompleted = Signal(object)
    recoveryRequired = Signal(str)
    cleanupAvailable = Signal(str)

    def __init__(
        self,
        coordinator: DeviceCoordinator,
        track_model: TrackTableModel,
        settings: SettingsService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._track_model = track_model
        self._settings = settings
        coordinator.set_volume_presentation_enabled(
            settings.get(MANAGE_VOLUME_PRESENTATION)
        )
        settings.settingChanged.connect(self._setting_changed)
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(1)
        self._discovery = coordinator.discovery
        self._active_ipod = coordinator.active_ipod
        self._busy = False
        self._read_only_operation_count = 0
        self._recovery_required = False
        self._closed = False
        self._next_token = 0
        self._active_token: int | None = None
        self._pending_automatic_selection: DeviceCandidateId | None = None
        self._work_items: dict[int, _DeviceWork] = {}
        self._searching = False
        self._discovery_error = ""
        self._automatic_discovery = False
        self._restore_without_picker = False
        self._automatic_selection_attempts: set[DeviceCandidateId] = set()
        self._auto_refresh_enabled = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh_automatically)

    @Slot(str, object)
    def _setting_changed(self, key: str, value: object) -> None:
        if key == MANAGE_VOLUME_PRESENTATION.key and isinstance(value, bool):
            self._coordinator.set_volume_presentation_enabled(value)

    @property
    def discovery(self) -> DeviceDiscovery:
        return self._discovery

    @property
    def active_ipod(self) -> ActiveIPod | None:
        return self._active_ipod

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def searching(self) -> bool:
        return self._searching

    @property
    def discovery_error(self) -> str:
        return self._discovery_error

    def start_auto_refresh(self) -> None:
        """Discover immediately, then repeat after each completed pass on every OS."""

        if self._closed or self._auto_refresh_enabled:
            return
        self._auto_refresh_enabled = True
        self._refresh_timer.start(0)

    def restore_previous_device(self) -> None:
        """Look for the remembered iPod once at startup without opening the picker."""

        if not self._settings.get(LAST_SELECTED_IPOD_VOLUME_ID):
            return
        self._begin(
            DeviceOperation.DISCOVER,
            lambda: self._coordinator.discover_devices(refresh_known=False),
            automatic=True,
            restore_without_picker=True,
        )

    def stop_auto_refresh(self) -> None:
        """Stop scheduling discovery; let any in-flight Storage read finish."""

        self._auto_refresh_enabled = False
        self._refresh_timer.stop()
        if not self._restore_without_picker:
            self._pending_automatic_selection = None

    @Slot()
    def _refresh_automatically(self) -> None:
        if self._closed or not self._auto_refresh_enabled:
            return
        if self._busy or self._read_only_operation_count:
            self._schedule_refresh()
            return
        self._begin(
            DeviceOperation.DISCOVER,
            lambda: self._coordinator.discover_devices(refresh_known=False),
            automatic=True,
        )

    def _schedule_refresh(self) -> None:
        if self._auto_refresh_enabled and not self._closed:
            self._refresh_timer.start(_AUTO_REFRESH_INTERVAL_MS)

    @property
    def device_writes_allowed(self) -> bool:
        """Whether a new Active-iPod mutation may begin."""

        return (
            not self._closed
            and not self._busy
            and not self._recovery_required
            and self._read_only_operation_count == 0
            and self._active_ipod is not None
        )

    def begin_library_save(self) -> bool:
        return self.begin_exclusive_operation()

    def set_recovery_required(self, required: bool) -> None:
        """Prevent another write workflow from compounding an interrupted Sync."""
        before = self.device_writes_allowed
        self._recovery_required = required
        if before != self.device_writes_allowed:
            self.deviceWritesAllowedChanged.emit(self.device_writes_allowed)

    def begin_read_only_operation(self) -> bool:
        """Keep the Active iPod stable while allowing concurrent device reads."""

        if self._closed or self._busy or self._active_ipod is None:
            return False
        writes_were_allowed = self.device_writes_allowed
        self._read_only_operation_count += 1
        if writes_were_allowed:
            self.deviceWritesAllowedChanged.emit(False)
        return True

    def finish_read_only_operation(self) -> None:
        """Release a reservation made by :meth:`begin_read_only_operation`."""

        if self._read_only_operation_count == 0:
            return
        self._read_only_operation_count -= 1
        if self.device_writes_allowed:
            self.deviceWritesAllowedChanged.emit(True)

    def begin_exclusive_operation(self) -> bool:
        """Reserve the Active iPod for one background mutation workflow."""

        if not self.device_writes_allowed:
            return False
        self._set_busy(True)
        return True

    def begin_recovery_operation(self) -> bool:
        """Reserve discovery and writes even when an interrupted Library cannot load."""
        if self._closed or self._busy or self._read_only_operation_count:
            return False
        self._set_busy(True)
        return True

    def finish_library_save(self, active: ActiveIPod | None) -> None:
        """Publish a committed Library before releasing the device reservation."""

        if active is not None:
            self._active_ipod = active
            self._track_model.replace_tracks(active.library.tracks)
            self.activeIPodChanged.emit(active)
            self.librarySaved.emit(active)
        self.finish_exclusive_operation()

    def finish_sync_recovery(self, active: ActiveIPod | None) -> None:
        """Drop stale Library state when restoration needs a manual reload."""
        self._replace_active_ipod(active)
        self.finish_exclusive_operation()

    def finish_exclusive_operation(self) -> None:
        """Release a reservation made by :meth:`begin_exclusive_operation`."""

        self._set_busy(False)

    def reload_active_ipod(self) -> bool:
        """Reload the selected connection after an external device mutation."""

        active = self._active_ipod
        if (
            self._closed
            or self._busy
            or self._read_only_operation_count
            or active is None
        ):
            return False
        identifier = active.candidate.id
        self._replace_active_ipod(None, force_model_reset=True)
        self._begin(
            DeviceOperation.SELECT,
            lambda: self._coordinator.select_device(identifier),
        )
        return True

    @Slot()
    def refresh_devices(self) -> None:
        if self._read_only_operation_count:
            return
        self._begin(DeviceOperation.DISCOVER, self._coordinator.discover_devices)

    @Slot(str)
    def select_device(self, candidate_id: str) -> None:
        if self._busy or self._closed or self._read_only_operation_count:
            return
        self._pending_automatic_selection = None
        self._replace_active_ipod(None, force_model_reset=True)
        identifier = DeviceCandidateId(candidate_id)
        self._begin(
            DeviceOperation.SELECT,
            lambda: self._coordinator.select_device(identifier),
        )

    @Slot(result=bool)
    def eject_active_ipod(self) -> bool:
        """Begin exclusive native safe removal of the current Active iPod."""

        expected = self._active_ipod
        if not self.device_writes_allowed or expected is None:
            return False
        self.ejectStarted.emit()
        self._begin(
            DeviceOperation.EJECT,
            lambda: DeviceEjectCompletion(
                expected.display_name,
                self._coordinator.eject_active_ipod(expected).detail,
            ),
        )
        return True

    def shutdown(self) -> None:
        """Stop accepting work, wait for owned workers, then close Storage state."""

        if self._closed:
            return
        writes_were_allowed = self.device_writes_allowed
        self._closed = True
        self._refresh_timer.stop()
        self._pending_automatic_selection = None
        if writes_were_allowed:
            self.deviceWritesAllowedChanged.emit(False)
        self._thread_pool.clear()
        self._thread_pool.waitForDone()
        self._work_items.clear()
        self._coordinator.close()
        self._set_searching(False)

    def _begin(
        self,
        operation: DeviceOperation,
        work: Callable[[], object],
        *,
        automatic: bool = False,
        restore_without_picker: bool = False,
    ) -> None:
        if self._busy or self._closed:
            return
        if operation is DeviceOperation.DISCOVER:
            self._pending_automatic_selection = None
        self._refresh_timer.stop()
        self._automatic_discovery = automatic
        self._restore_without_picker = restore_without_picker
        self._set_searching(operation is DeviceOperation.DISCOVER)
        self._next_token += 1
        token = self._next_token
        item = _DeviceWork(token, operation, work)
        item.signals.succeeded.connect(
            self._work_succeeded,
            Qt.ConnectionType.QueuedConnection,
        )
        item.signals.failed.connect(
            self._work_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        item.signals.finished.connect(
            self._work_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._active_token = token
        self._work_items[token] = item
        self._set_busy(True)
        self._thread_pool.start(item)

    @Slot(int, object, object)
    def _work_succeeded(
        self,
        token: int,
        operation: object,
        result: object,
    ) -> None:
        if self._closed or token != self._active_token:
            return
        if operation == DeviceOperation.DISCOVER and isinstance(
            result,
            DeviceDiscovery,
        ):
            if result != self._discovery:
                self._discovery = result
                self.discoveryChanged.emit(result)
            self._set_discovery_error(
                "\n".join(issue.detail for issue in result.issues)
            )
            self._automatic_selection_attempts.intersection_update(
                candidate.id for candidate in result.candidates
            )
            active = self._coordinator.active_ipod
            if active is None:
                self._replace_active_ipod(None)
                remembered = self._remembered_candidate_id()
                if not self._automatic_discovery or (
                    (self._auto_refresh_enabled or self._restore_without_picker)
                    and remembered not in self._automatic_selection_attempts
                ):
                    self._pending_automatic_selection = remembered
            elif self._active_ipod is not None and active is not self._active_ipod:
                self._active_ipod = active
                self.activeIPodChanged.emit(active)
            return
        if operation == DeviceOperation.SELECT and isinstance(result, ActiveIPod):
            self._discovery = self._coordinator.discovery
            self.discoveryChanged.emit(self._discovery)
            self.set_recovery_required(False)
            self._replace_active_ipod(result)
            if self._coordinator.sync_cleanup_path:
                self.cleanupAvailable.emit(self._coordinator.sync_cleanup_path)
            active_volume_id = self._coordinator.active_volume_id
            if active_volume_id is not None:
                self._settings.set_global(
                    LAST_SELECTED_IPOD_VOLUME_ID,
                    active_volume_id.value,
                )
            return
        if operation == DeviceOperation.EJECT and isinstance(
            result,
            DeviceEjectCompletion,
        ):
            self._discovery = self._coordinator.discovery
            self.discoveryChanged.emit(self._discovery)
            self._replace_active_ipod(None)
            self.ejectCompleted.emit(result)

    @Slot(int, object, object)
    def _work_failed(
        self,
        token: int,
        operation: object,
        error: object,
    ) -> None:
        if self._closed or token != self._active_token:
            return
        if isinstance(error, SyncRecoveryRequiredError):
            self._pending_automatic_selection = None
            self._replace_active_ipod(None)
            self.set_recovery_required(True)
            self.recoveryRequired.emit(error.recovery_path)
            return
        resolved_operation = (
            operation
            if isinstance(operation, DeviceOperation)
            else DeviceOperation.DISCOVER
        )
        if resolved_operation in {DeviceOperation.SELECT, DeviceOperation.EJECT}:
            self._discovery = self._coordinator.discovery
            self.discoveryChanged.emit(self._discovery)
        if resolved_operation is DeviceOperation.EJECT:
            self._replace_active_ipod(self._coordinator.active_ipod)
        message = (
            str(error)
            if isinstance(error, Exception)
            else self.tr("The device operation failed.")
        )
        if resolved_operation is DeviceOperation.DISCOVER:
            self._set_discovery_error(message)
            if self._automatic_discovery:
                return
        self.operationFailed.emit(
            DeviceOperationFailure(
                operation=resolved_operation,
                message=message,
                error_type=type(error).__name__,
            )
        )

    @Slot(int)
    def _work_finished(self, token: int) -> None:
        self._work_items.pop(token, None)
        if token != self._active_token:
            return
        self._active_token = None
        self._set_busy(False)
        self._set_searching(False)
        pending = self._pending_automatic_selection
        self._pending_automatic_selection = None
        self._restore_without_picker = False
        if pending is not None and not self._closed:
            self._automatic_selection_attempts.add(pending)
            self.select_device(pending.value)
        if not self._busy:
            self._schedule_refresh()

    def _set_searching(self, searching: bool) -> None:
        if searching != self._searching:
            self._searching = searching
            self.searchingChanged.emit(searching)

    def _set_discovery_error(self, message: str) -> None:
        if message != self._discovery_error:
            self._discovery_error = message
            self.discoveryErrorChanged.emit(message)

    def _remembered_candidate_id(self) -> DeviceCandidateId | None:
        value = self._settings.get(LAST_SELECTED_IPOD_VOLUME_ID)
        if not value:
            return None
        return self._coordinator.candidate_id_for_volume(VolumeId(value))

    def _replace_active_ipod(
        self,
        active_ipod: ActiveIPod | None,
        *,
        force_model_reset: bool = False,
    ) -> None:
        if active_ipod == self._active_ipod and not force_model_reset:
            return
        writes_were_allowed = self.device_writes_allowed
        self._active_ipod = active_ipod
        tracks = active_ipod.library.tracks if active_ipod is not None else ()
        self._track_model.reset_tracks(tracks)
        self.activeIPodChanged.emit(active_ipod)
        writes_are_allowed = self.device_writes_allowed
        if writes_are_allowed != writes_were_allowed:
            self.deviceWritesAllowedChanged.emit(writes_are_allowed)

    def _set_busy(self, busy: bool) -> None:
        if busy == self._busy:
            return
        writes_were_allowed = self.device_writes_allowed
        self._busy = busy
        self.busyChanged.emit(busy)
        writes_are_allowed = self.device_writes_allowed
        if writes_are_allowed != writes_were_allowed:
            self.deviceWritesAllowedChanged.emit(writes_are_allowed)


__all__ = [
    "DeviceController",
    "DeviceEjectCompletion",
    "DeviceOperation",
    "DeviceOperationFailure",
]
