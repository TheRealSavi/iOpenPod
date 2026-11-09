"""Bounded Extras inspection and transaction preparation through Storage.

Calendar bytes are not normalized on import. A selected entry edit rewrites only
its supported properties; unrelated components and unknown data stay intact.
Alarm timestamps are native civil coordinates, never implicit Host instants.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from whenever import PlainDateTime, Time

from device_registry import AlarmFormat, ExtrasSupport
from iOpenPod.app.display_text import source_text
from iOpenPod.app.models.extras import (
    AlarmItem,
    CalendarGroup,
    CalendarItem,
    CreateCalendar,
    ExtrasCatalog,
    ExtrasChange,
    ExtrasFile,
    ImportCalendar,
    RemoveCalendar,
    RenameCalendar,
    SaveAlarm,
    SaveCalendar,
)
from iOpenPod.app.services.calendar_support import calendar_profile
from iPodDB.alarms import (
    parse_alarms,
    parse_preferences_alarm,
    patch_preferences_alarm,
    update_alarm,
    write_alarms,
)
from iPodDB.calendar import (
    CalendarEntryChanges,
    CalendarEntryDraft,
    add_entry,
    create_calendar,
    parse_calendar,
    remove_entry,
    rename_calendar,
    serialize_calendar,
    update_entry,
)
from storage import (
    DeviceEntryKind,
    DevicePath,
    FileContent,
    FilePrecondition,
    FilesystemSession,
    HostPath,
    StorageError,
    StorageTransaction,
    TransactionWrite,
    capture_host_file,
)

if TYPE_CHECKING:
    from collections.abc import Callable

CALENDAR_ROOT = DevicePath("Calendars")
ALARM_PATH = DevicePath("iPod_Control/Device/alarms")
PREFERENCES_PATH = DevicePath("iPod_Control/Device/Preferences")
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_CALENDAR_FILES = 256
MAX_CALENDAR_BYTES = 16 * 1024 * 1024


def read_extras(
    session: FilesystemSession,
    support: ExtrasSupport,
    checkpoint: Callable[[], None],
) -> ExtrasCatalog:
    """Optional malformed files contribute issues without discarding other files."""
    files: list[ExtrasFile] = []
    calendar: list[CalendarItem] = []
    issues: list[str] = []
    groups: dict[str | None, CalendarGroup] = {}
    total_bytes = 0
    checkpoint()
    try:
        entries = (
            session.list_directory(CALENDAR_ROOT)
            if session.exists(CALENDAR_ROOT)
            else ()
        )
        candidates = sorted(
            (
                entry
                for entry in entries
                if entry.kind is DeviceEntryKind.FILE
                and entry.path.name.lower().endswith((".ics", ".vcs"))
            ),
            key=lambda entry: entry.path.name.casefold(),
        )
        if len(candidates) > MAX_CALENDAR_FILES:
            issues.append("Some Calendar files were omitted because of the file limit.")
        for entry in candidates[:MAX_CALENDAR_FILES]:
            checkpoint()
            try:
                captured = session.read_snapshot(entry.path, max_bytes=MAX_FILE_BYTES)
                total_bytes += len(captured.data)
                if total_bytes > MAX_CALENDAR_BYTES:
                    issues.append("Some Calendar files exceeded the inspection budget.")
                    break
                key = str(entry.path)
                files.append(ExtrasFile(key, captured.data, captured.fingerprint))
                document = parse_calendar(
                    captured.data, profile=calendar_profile(support)
                )
                for component in document.components:
                    if component.name != "VCALENDAR":
                        continue
                    name = component.calendar_name
                    names = [
                        prop
                        for prop in component.properties
                        if prop.name == "X-WR-CALNAME"
                    ]
                    editable = (
                        document.editable
                        and len(names) <= 1
                        and not any(prop.parameters for prop in names)
                    )
                    previous = groups.get(name)
                    keys = (
                        tuple(dict.fromkeys((*previous.document_keys, key)))
                        if previous
                        else (key,)
                    )
                    groups[name] = CalendarGroup(
                        name,
                        keys,
                        editable and (previous.editable if previous else True),
                    )
                    calendar.extend(
                        CalendarItem(key, item, name)
                        for item in document.entries
                        if component.start_offset
                        < item.component.start_offset
                        < component.end_offset
                    )
                issues.extend(
                    f"{entry.path.name}: {issue}" for issue in document.issues
                )
            except (StorageError, ValueError) as error:
                if not session.is_active:
                    raise
                issues.append(f"{entry.path.name}: {error}")
    except (StorageError, ValueError) as error:
        if not session.is_active:
            raise
        issues.append(f"Calendars: {error}")
    alarms: tuple[AlarmItem, ...] = ()
    path = (
        ALARM_PATH if support.alarm_format is AlarmFormat.CLASSIC else PREFERENCES_PATH
    )
    if support.alarm_format is not AlarmFormat.NONE:
        checkpoint()
        try:
            if session.exists(path):
                captured = session.read_snapshot(path, max_bytes=MAX_FILE_BYTES)
                files.append(ExtrasFile(str(path), captured.data, captured.fingerprint))
                alarms, alarm_issues = _alarm_items(captured.data, support)
                issues.extend(alarm_issues)
        except (StorageError, ValueError) as error:
            if not session.is_active:
                raise
            issues.append(f"Alarms: {error}")
    checkpoint()
    return ExtrasCatalog(
        tuple(calendar),
        alarms,
        tuple(issues),
        support,
        tuple(files),
        tuple(groups.values()),
    )


def _alarm_items(
    data: bytes, support: ExtrasSupport
) -> tuple[tuple[AlarmItem, ...], tuple[str, ...]]:
    if support.alarm_format is AlarmFormat.CLASSIC:
        document = parse_alarms(data)
        return (
            tuple(
                AlarmItem(
                    record.index,
                    source_text("Alarm {number}", number=str(record.index + 1)),
                    record.scheduled,
                    record.repeat_mode,
                    record.can_edit_date and support.alarm_write,
                    record.label or "",
                    record.can_edit_repeat and support.alarm_write,
                )
                for record in document.records
            ),
            document.issues,
        )
    preferences = parse_preferences_alarm(data, support.alarm_format.value)
    projection = support.alarm_format is AlarmFormat.VIDEO
    return (
        (
            AlarmItem(
                0,
                source_text("Clock alarm snapshot")
                if projection
                else source_text("Clock alarm"),
                preferences.time,
                None,
                preferences.editable and support.alarm_write and not projection,
            ),
        ),
        preferences.issues,
    )


def _source(catalog: ExtrasCatalog, key: str) -> ExtrasFile:
    return next(file for file in catalog.files if file.key == key)


def _calendar_source(catalog: ExtrasCatalog, group: CalendarGroup) -> ExtrasFile:
    if group not in catalog.calendars or not group.editable or not group.document_keys:
        raise ValueError(
            "This calendar changed or cannot be edited. Reload before editing."
        )
    source = _source(catalog, group.document_keys[0])
    if DevicePath(source.key).parts[:-1] != CALENDAR_ROOT.parts:
        raise ValueError("Calendar edits must stay inside the Calendars folder.")
    return source


def _write_file(source: ExtrasFile, data: bytes) -> TransactionWrite:
    if DevicePath(source.key).parts[:-1] != CALENDAR_ROOT.parts:
        raise ValueError("Calendar edits must stay inside the Calendars folder.")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("The Calendar file exceeds the supported size.")
    return TransactionWrite(
        DevicePath(source.key),
        data,
        FileContent(len(data), hashlib.sha256(data).hexdigest()),
        expected=source.fingerprint,
    )


def prepare_change(
    catalog: ExtrasCatalog,
    change: ExtrasChange,
    *,
    dependencies: tuple[FilePrecondition, ...] = (),
    checkpoint: Callable[[], None],
) -> StorageTransaction | None:
    """Prepare exact bytes from an issued snapshot; Storage enforces preconditions."""
    support = catalog.support
    if support is None:
        raise ValueError("Reload Extras before editing this iPod.")
    checkpoint()
    source: ExtrasFile | None = None
    if isinstance(change, SaveAlarm):
        if not support.alarm_write or change.item not in catalog.alarms:
            raise ValueError("This saved alarm is not available for editing.")
        if not change.item.editable:
            raise ValueError("This saved alarm has an unsupported record layout.")
        if change.repeat is not None and not change.item.repeat_editable:
            raise ValueError("This saved alarm's repeat field is not editable.")
        if support.alarm_format is AlarmFormat.CLASSIC:
            path = ALARM_PATH
            source = _source(catalog, str(path))
            if not isinstance(change.time, PlainDateTime):
                raise ValueError("This alarm needs a date and time on the iPod.")
            alarm_document = update_alarm(
                parse_alarms(source.data),
                change.item.index,
                scheduled=change.time,
                repeat_mode=change.repeat,
            )
            data = write_alarms(alarm_document)
        elif support.alarm_format is AlarmFormat.MINI:
            path = PREFERENCES_PATH
            source = _source(catalog, str(path))
            if not isinstance(change.time, Time) or change.repeat is not None:
                raise ValueError("This Clock alarm stores only a time of day.")
            data = patch_preferences_alarm(
                parse_preferences_alarm(source.data, support.alarm_format.value),
                change.time,
            )
        else:
            raise ValueError("The alarm format is not qualified for this iPod.")
    else:
        if not support.calendar_write:
            raise ValueError(
                "Calendar editing is not qualified for this iPod firmware."
            )
        if isinstance(change, RenameCalendar):
            _calendar_source(catalog, change.calendar)
            if any(
                group.name == change.name and group != change.calendar
                for group in catalog.calendars
            ):
                raise ValueError("A calendar with this name already exists.")
            writes: list[TransactionWrite] = []
            for key in change.calendar.document_keys:
                checkpoint()
                member = _source(catalog, key)
                renamed = serialize_calendar(
                    rename_calendar(parse_calendar(member.data), change.name)
                )
                writes.append(_write_file(member, renamed))
            return StorageTransaction(writes=tuple(writes), dependencies=dependencies)
        if isinstance(change, CreateCalendar):
            if any(group.name == change.name for group in catalog.calendars):
                raise ValueError("A calendar with this name already exists.")
            data = serialize_calendar(create_calendar(name=change.name))
            path = DevicePath(f"Calendars/iopenpod-{uuid4().hex}.ics")
        elif isinstance(change, ImportCalendar):
            host = HostPath(change.host_path)
            suffix = Path(host).suffix.lower()
            if suffix not in (".ics", ".vcs"):
                raise ValueError("Choose an iCalendar (.ics) or vCalendar (.vcs) file.")
            with capture_host_file(
                host, checkpoint=checkpoint, max_bytes=MAX_FILE_BYTES
            ) as captured:
                data = Path(captured.snapshot).read_bytes()
            document = parse_calendar(data)
            if not any(
                component.name == "VCALENDAR" for component in document.components
            ):
                raise ValueError("This file has no readable calendar.")
            if change.name is not None:
                data = serialize_calendar(rename_calendar(document, change.name))
            # Without an explicit name, preserve every imported byte.
            path = DevicePath(f"Calendars/iopenpod-{uuid4().hex}{suffix}")
        elif isinstance(change, SaveCalendar) and change.existing is None:
            if not isinstance(change.edit, CalendarEntryDraft):
                raise ValueError("A new Calendar entry needs its complete draft.")
            destination = change.destination or next(
                (group for group in catalog.calendars if group.name == "iOpenPod"), None
            )
            if destination is not None:
                source = _calendar_source(catalog, destination)
                document = parse_calendar(
                    source.data, profile=calendar_profile(support)
                )
                path = DevicePath(source.key)
            else:
                document = create_calendar(name="iOpenPod")
                path = DevicePath(f"Calendars/iopenpod-{uuid4().hex}.ics")
            data = serialize_calendar(
                add_entry(document, change.edit, profile=calendar_profile(support))
            )
        else:
            item = (
                change.item if isinstance(change, RemoveCalendar) else change.existing
            )
            if item is None or item not in catalog.calendar:
                raise ValueError("This Calendar entry changed. Reload before editing.")
            source = _source(catalog, item.document_key)
            path = DevicePath(source.key)
            if path.parts[:-1] != CALENDAR_ROOT.parts:
                raise ValueError(
                    "Calendar edits must stay inside the Calendars folder."
                )
            document = parse_calendar(source.data, profile=calendar_profile(support))
            if isinstance(change, RemoveCalendar):
                document = remove_entry(document, item.index)
            else:
                if not isinstance(change.edit, CalendarEntryChanges):
                    raise ValueError(
                        "An existing Calendar entry needs explicit changes."
                    )
                document = update_entry(
                    document, item.index, change.edit, profile=calendar_profile(support)
                )
            data = serialize_calendar(document)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("The Calendar or Alarm file exceeds the supported size.")
    if source is not None and source.data == data:
        return None
    checkpoint()
    return StorageTransaction(
        writes=(
            TransactionWrite(
                path,
                data,
                FileContent(len(data), hashlib.sha256(data).hexdigest()),
                expected=source.fingerprint if source is not None else None,
            ),
        ),
        dependencies=dependencies,
    )
