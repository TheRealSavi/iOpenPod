"""Shared Extras controller and widget lookup for native GUI workflow tests."""

from PySide6.QtCore import QObject
from whenever import Date, PlainDateTime, Time

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app.extras_controller import ExtrasController
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.models.extras import (
    AlarmItem,
    AlarmSound,
    CalendarGroup,
    CalendarItem,
    ExtrasCatalog,
)
from iPodDB.calendar import CalendarEntryChanges, CalendarEntryDraft
from iPodDB.library import LibrarySnapshot
from storage import FileFingerprint


def make_active_ipod() -> ActiveIPod:
    profile = next(
        p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == "MB565"
    )
    candidate = DeviceCandidate(
        id=DeviceCandidateId("extras-gui"),
        display_name="iPod",
        host_description="Test",
        bus="usb",
        identification_status=IdentificationStatus.EXACT,
        readiness=DeviceReadiness.READY,
        profile=profile,
        total_bytes=120_000_000_000,
        available_bytes=60_000_000_000,
    )
    return ActiveIPod(
        candidate=candidate,
        profile=profile,
        library=LibrarySnapshot(),
        database_name="iTunesDB",
        database_fingerprint=FileFingerprint(
            size=0, modified_ns=0, device=0, inode=0, sha256="0" * 64
        ),
    )


class ExtrasTestController(ExtrasController):
    """A signal-bearing application boundary, without filesystem workers."""

    def __init__(self, catalog: ExtrasCatalog | None = None) -> None:
        QObject.__init__(self)
        self.current: ActiveIPod | None = make_active_ipod()
        self.view = catalog or ExtrasCatalog()
        self.working = False
        self.error = ""
        self.calendar_edits: list[
            tuple[CalendarEntryDraft | CalendarEntryChanges, CalendarItem | None]
        ] = []
        self.alarm_edits: list[tuple[AlarmItem, PlainDateTime | Time, int | None]] = []
        self.refreshes = 0
        self.destinations: list[CalendarGroup | None] = []
        self.names: list[tuple[CalendarGroup | None, str]] = []
        self.imports: list[tuple[str, str | None]] = []
        self.skipped: list[tuple[CalendarItem, Date, Date]] = []
        self.removed: list[CalendarItem] = []
        self.created_alarms: list[tuple[PlainDateTime, int, bool, int]] = []
        self.removed_alarms: list[AlarmItem] = []
        self.alarm_states: list[tuple[bool | None, int | None]] = []

    @property
    def active_ipod(self) -> ActiveIPod | None:
        return self.current

    @property
    def catalog(self) -> ExtrasCatalog:
        return self.view

    @property
    def busy(self) -> bool:
        return self.working

    @property
    def message(self) -> str:
        return self.error

    @property
    def can_write(self) -> bool:
        return self.current is not None and not self.working

    def refresh(self) -> None:
        self.refreshes += 1

    def save_calendar(
        self,
        edit: CalendarEntryDraft | CalendarEntryChanges,
        existing: CalendarItem | None = None,
        destination: CalendarGroup | None = None,
    ) -> bool:
        self.calendar_edits.append((edit, existing))
        self.destinations.append(destination)
        return True

    def create_calendar(self, name: str) -> bool:
        self.names.append((None, name))
        return True

    def skip_calendar_occurrence(
        self, item: CalendarItem, day: Date, start_day: Date
    ) -> bool:
        self.skipped.append((item, day, start_day))
        return True

    def remove_calendar(self, item: CalendarItem) -> bool:
        self.removed.append(item)
        return True

    def rename_calendar(self, calendar: CalendarGroup, name: str) -> bool:
        self.names.append((calendar, name))
        return True

    def import_calendar(self, path: str, name: str | None = None) -> bool:
        self.imports.append((path, name))
        return True

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
        self.alarm_edits.append((item, time, repeat))
        self.alarm_states.append((enabled, label_index))
        return True

    def create_alarm(
        self,
        time: PlainDateTime,
        repeat: int = 0,
        *,
        enabled: bool = True,
        label_index: int = 3,
        sound: AlarmSound | None = None,
    ) -> bool:
        self.created_alarms.append((time, repeat, enabled, label_index))
        return True

    def remove_alarm(self, item: AlarmItem) -> bool:
        self.removed_alarms.append(item)
        return True


def find_widget[T: QObject](parent: QObject, cls: type[T], name: str) -> T:
    found = parent.findChild(cls, name)
    assert isinstance(found, cls)
    return found
