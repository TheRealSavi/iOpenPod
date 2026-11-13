"""Background Extras reads and explicit edits for one selected connection."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from device_registry import AlarmFormat
from iOpenPod.app.core.status import StatusProgress
from iOpenPod.app.models.extras import (
    AlarmItem,
    AlarmSound,
    CalendarGroup,
    CalendarItem,
    CreateAlarm,
    CreateCalendar,
    CreateClockAlarm,
    CreateTone,
    ExtrasCatalog,
    ExtrasChange,
    ImportCalendar,
    RemoveAlarm,
    RemoveCalendar,
    RenameCalendar,
    SaveAlarm,
    SaveCalendar,
    SaveTimerSettings,
    SkipCalendarOccurrence,
)
from iOpenPod.app.services.device_coordinator import SyncRecoveryRequiredError

if TYPE_CHECKING:
    from whenever import Date, PlainDateTime, Time

    from iOpenPod.app.core.status import ApplicationStatus
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator
    from iPodDB.alarms import AlarmToneNote, ClockCity, CountdownTimerChanges
    from iPodDB.calendar import CalendarEntryChanges, CalendarEntryDraft

_LOGGER = logging.getLogger(__name__)
_STATUS = "extras.write"


class _Signals(QObject):
    completed = Signal(object, object)


class _Work(QRunnable):
    def __init__(
        self,
        coordinator: DeviceCoordinator,
        active: ActiveIPod,
        catalog: ExtrasCatalog,
        change: ExtrasChange | None = None,
    ) -> None:
        super().__init__()
        self.coordinator = coordinator
        self.active = active
        self.catalog = catalog
        self.change = change
        self.cancelled = threading.Event()
        self.signals = _Signals()

    def run(self) -> None:
        outcome: ExtrasCatalog | Exception
        try:
            if self.change is None:
                outcome = self.coordinator.load_extras(self.active, self.cancelled)
            else:
                outcome = self.coordinator.save_extras(
                    self.active, self.catalog, self.change, self.cancelled
                )
        except Exception as error:
            outcome = error
        self.signals.completed.emit(self, outcome)


class ExtrasController(QObject):
    """Keep optional date failures on their page, outside Library load/save gates."""

    changed = Signal()

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
        self._catalog = ExtrasCatalog()
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
    def catalog(self) -> ExtrasCatalog:
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
            not self._closed
            and not self.busy
            and self.active_ipod is not None
            and self.active_ipod is self._loaded_for
            and self._devices.device_writes_allowed
        )

    def refresh(self) -> None:
        self._requested = True
        active = self.active_ipod
        if self._closed or self.busy or active is None:
            return
        # Reads hold the same explicit connection reservation as other inspectors.
        if not self._devices.begin_read_only_operation():
            return
        self._start(_Work(self._coordinator, active, self._catalog))

    def save_calendar(
        self,
        edit: CalendarEntryDraft | CalendarEntryChanges,
        existing: CalendarItem | None = None,
        destination: CalendarGroup | None = None,
    ) -> bool:
        support = self._catalog.support
        if support is None or not support.calendar_write:
            return False
        if existing is not None and existing not in self._catalog.calendar:
            return False
        if destination is not None and (
            destination not in self._catalog.calendars or not destination.editable
        ):
            return False
        return self._write(SaveCalendar(edit, existing, destination))

    def remove_calendar(self, item: CalendarItem) -> bool:
        support = self._catalog.support
        if (
            support is None
            or not support.calendar_write
            or item not in self._catalog.calendar
        ):
            return False
        return self._write(RemoveCalendar(item))

    def skip_calendar_occurrence(
        self, item: CalendarItem, day: Date, start_day: Date
    ) -> bool:
        support = self._catalog.support
        return bool(
            support
            and support.calendar_write
            and item in self._catalog.calendar
            and self._write(SkipCalendarOccurrence(item, day, start_day))
        )

    def create_calendar(self, name: str) -> bool:
        support = self._catalog.support
        return bool(
            support and support.calendar_write and self._write(CreateCalendar(name))
        )

    def rename_calendar(self, calendar: CalendarGroup, name: str) -> bool:
        support = self._catalog.support
        return bool(
            support
            and support.calendar_write
            and calendar in self._catalog.calendars
            and calendar.editable
            and self._write(RenameCalendar(calendar, name))
        )

    def import_calendar(self, path: str, name: str | None = None) -> bool:
        support = self._catalog.support
        return bool(
            path
            and support is not None
            and support.calendar_write
            and self._write(ImportCalendar(path, name))
        )

    def save_alarm(
        self,
        item: AlarmItem,
        time: PlainDateTime | Time,
        repeat: int | None = None,
        *,
        enabled: bool | None = None,
        label_index: int | None = None,
        sound: AlarmSound | None = None,
        daylight_saving: bool | None = None,
    ) -> bool:
        support = self._catalog.support
        if (
            support is None
            or not support.alarm_write
            or item not in self._catalog.alarms
            or not item.editable
        ):
            return False
        return self._write(
            SaveAlarm(item, time, repeat, enabled, label_index, sound, daylight_saving)
        )

    def create_alarm(
        self,
        time: PlainDateTime,
        repeat: int = 0,
        *,
        enabled: bool = True,
        label_index: int = 3,
        sound: AlarmSound | None = None,
    ) -> bool:
        support = self._catalog.support
        return bool(
            support
            and support.alarm_write
            and support.alarm_format is AlarmFormat.CLASSIC
            and self._catalog.can_create_alarm
            and self._write(CreateAlarm(time, repeat, enabled, label_index, sound))
        )

    def create_clock_alarm(
        self,
        city: ClockCity,
        time: Time,
        *,
        daylight_saving: bool = False,
        enabled: bool = False,
        sound: AlarmSound | None = None,
    ) -> bool:
        support = self._catalog.support
        return bool(
            support
            and support.alarm_write
            and support.alarm_format is AlarmFormat.CLOCK
            and self._catalog.can_create_alarm
            and city in self._catalog.clock_cities
            and self._write(
                CreateClockAlarm(city, time, daylight_saving, enabled, sound)
            )
        )

    def remove_alarm(self, item: AlarmItem) -> bool:
        support = self._catalog.support
        return bool(
            support
            and support.alarm_write
            and support.alarm_format in (AlarmFormat.CLASSIC, AlarmFormat.CLOCK)
            and item in self._catalog.alarms
            and item.editable
            and self._write(RemoveAlarm(item))
        )

    def save_timer_settings(self, changes: CountdownTimerChanges) -> bool:
        support = self._catalog.support
        return bool(
            support
            and support.timer_settings_write
            and self._catalog.timer is not None
            and self._write(SaveTimerSettings(changes))
        )

    def create_tone(self, name: str, notes: tuple[AlarmToneNote, ...]) -> bool:
        return self._catalog.can_create_tone and self._write(CreateTone(name, notes))

    def _write(self, change: ExtrasChange) -> bool:
        active = self.active_ipod
        if (
            active is None
            or not self.can_write
            or not self._devices.begin_exclusive_operation()
        ):
            return False
        self._status.show(
            _STATUS, self.tr("Saving iPod Extras…"), progress=StatusProgress()
        )
        self._start(_Work(self._coordinator, active, self._catalog, change))
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
        # Release while busy is still true: availability callbacks cannot start
        # another scan and accidentally overwrite this completion's state.
        if job.change is None:
            self._devices.finish_read_only_operation()
        else:
            if current and isinstance(outcome, SyncRecoveryRequiredError):
                self._devices.set_recovery_required(True)
            self._devices.finish_exclusive_operation()
        self._job = None
        self._status.clear(_STATUS)
        if current:
            if isinstance(outcome, ExtrasCatalog):
                self._catalog = outcome
                self._loaded_for = job.active
            else:
                self._message = str(outcome)
                _LOGGER.warning("Extras operation failed: %s", outcome)
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
        self._catalog = ExtrasCatalog()
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
            if self._job.change is None:
                self._devices.finish_read_only_operation()
            else:
                self._devices.finish_exclusive_operation()
        self._job = None
        self._status.clear(_STATUS)
