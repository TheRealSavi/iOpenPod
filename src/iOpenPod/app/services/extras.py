"""Bounded Extras inspection and transaction preparation through Storage.

Calendar bytes are not normalized on import. A selected entry edit rewrites only
its supported properties; unrelated components and unknown data stay intact.
Alarm timestamps are native civil coordinates, never implicit Host instants.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from whenever import PlainDateTime, Time

from device_registry import AlarmFormat, ExtrasSupport, FirmwareTarget
from iOpenPod.app.alarm_labels import ALARM_LABELS
from iOpenPod.app.display_text import source_text
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
    ExtrasFile,
    ImportCalendar,
    RemoveAlarm,
    RemoveCalendar,
    RenameCalendar,
    SaveAlarm,
    SaveCalendar,
    SaveTimerSettings,
    SkipCalendarOccurrence,
)
from iOpenPod.app.services.alarm_tones import capture_alarm_tones
from iPodDB.alarms import (
    CLOCK_CITIES,
    CountdownTimerSnapshot,
    add_alarm,
    add_clock_alarm,
    clock_city,
    create_alarm_tone,
    empty_alarm_document,
    empty_clock_document,
    parse_alarms,
    parse_clock_alarms,
    parse_countdown_timer,
    parse_preferences_alarm,
    patch_countdown_timer,
    patch_preferences_alarm,
    remove_alarm,
    remove_clock_alarm,
    update_alarm,
    update_clock_alarm,
    write_alarms,
    write_clock_alarms,
)
from iPodDB.calendar import (
    CalendarEntryChanges,
    CalendarEntryDraft,
    add_entry,
    calendar_zone_names,
    create_calendar,
    parse_calendar,
    remove_entry,
    rename_calendar,
    serialize_calendar,
    skip_occurrence,
    update_entry,
)
from iPodDB.library import AlarmPlaylistCatalog, AlarmPlaylistLayout
from iPodDB.preferences import NamedPreferencesProfile
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
CLOCK_PATH = DevicePath("iPod_Control/Device/clock")
SETTINGS_PATH = DevicePath("iPod_Control/Device/iPodSettings.xml")
TIMER_PATH = DevicePath("iPod_Control/Device/iPodTimerSettings.xml")
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_CALENDAR_FILES = 256
MAX_CALENDAR_BYTES = 16 * 1024 * 1024


def read_extras(
    session: FilesystemSession,
    support: ExtrasSupport,
    checkpoint: Callable[[], None],
    *,
    alarm_playlists: AlarmPlaylistCatalog | None = None,
    playlist_source: FilePrecondition | None = None,
    playlist_dependencies: tuple[FilePrecondition, ...] = (),
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
                document = parse_calendar(captured.data)
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
                        previous.zones if previous else calendar_zone_names(component),
                    )
                    calendar.extend(
                        CalendarItem(key, item, name, source_calendar=component)
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
    timer: CountdownTimerSnapshot | None = None
    can_create_alarm = False
    path = _alarm_path(support.alarm_format)
    if support.alarm_format is AlarmFormat.TIMER:
        timer = _read_timer(session, support, files, issues, checkpoint)
    elif support.alarm_format is not AlarmFormat.NONE:
        checkpoint()
        try:
            if session.exists(path):
                captured = session.read_snapshot(path, max_bytes=MAX_FILE_BYTES)
                files.append(ExtrasFile(str(path), captured.data, captured.fingerprint))
                alarms, alarm_issues = _alarm_items(captured.data, support)
                issues.extend(alarm_issues)
                can_create_alarm = (
                    support.alarm_format in (AlarmFormat.CLASSIC, AlarmFormat.CLOCK)
                    and support.alarm_write
                    and not alarm_issues
                )
            elif (
                support.alarm_format in (AlarmFormat.CLASSIC, AlarmFormat.CLOCK)
                and support.alarm_write
            ):
                can_create_alarm = True
        except (StorageError, ValueError) as error:
            if not session.is_active:
                raise
            issues.append(f"Alarms: {error}")
    sounds = _legacy_sounds(support, alarm_playlists)
    if alarm_playlists is not None:
        issues.extend(alarm_playlists.issues)
    tones = (
        capture_alarm_tones(session, support, checkpoint)
        if support.alarm_format is AlarmFormat.CLASSIC and support.alarm_write
        else None
    )
    if tones is not None:
        sounds = (*tones.sounds, *sounds)
        issues.extend(tones.issues)
        can_create_alarm = can_create_alarm and bool(sounds)
        source = next((file for file in files if file.key == str(ALARM_PATH)), None)
        if source is not None:
            alarms = tuple(
                replace(
                    item,
                    sound=next(
                        (
                            sound
                            for sound in sounds
                            if (
                                record.sound_selector == 0xFFFFFFFF
                                and sound.tone_name == record.tone_name
                            )
                            or (
                                record.sound_selector != 0xFFFFFFFF
                                and not record.tone_name
                                and sound.kind is AlarmSound.Kind.PLAYLIST
                                and sound.playlist_index == record.sound_selector
                            )
                        ),
                        None,
                    ),
                    sound_description=(
                        source_text("Saved playlist and tone")
                        if record.tone_name
                        else source_text("Saved playlist")
                    )
                    if record.sound_selector != 0xFFFFFFFF
                    else record.tone_name or "",
                    sound_editable=bool(sounds)
                    and record.can_edit_tone
                    and record.can_edit_playlist,
                )
                for item, record in zip(
                    alarms, parse_alarms(source.data).records, strict=True
                )
            )
    else:
        alarms = _legacy_sound_items(alarms, files, support, sounds)
    checkpoint()
    return ExtrasCatalog(
        tuple(calendar),
        alarms,
        tuple(issues),
        support,
        tuple(files),
        tuple(groups.values()),
        timer,
        can_create_alarm,
        sounds,
        alarm_playlists,
        playlist_source,
        tones.dependencies if tones else (),
        tones.inventory if tones else None,
        CLOCK_CITIES
        if support.alarm_format is AlarmFormat.CLOCK and support.alarm_write
        else (),
        playlist_dependencies,
        tones.items if tones else (),
        tones.can_create if tones else False,
    )


def alarm_playlist_layout(support: ExtrasSupport) -> AlarmPlaylistLayout | None:
    if support.alarm_format in (AlarmFormat.MINI, AlarmFormat.MINI_1):
        return AlarmPlaylistLayout.MINI
    if support.alarm_format is AlarmFormat.CLOCK:
        return (
            AlarmPlaylistLayout.VIDEO
            if support.alarm_firmware is FirmwareTarget.VIDEO_1_3
            else AlarmPlaylistLayout.CLOCK
        )
    return (
        {
            FirmwareTarget.CLASSIC_6_1_1_2: AlarmPlaylistLayout.CLASSIC,
            FirmwareTarget.CLASSIC_120GB_2_0_1: AlarmPlaylistLayout.CLASSIC,
            FirmwareTarget.CLASSIC_UPDATER_35_2_0_4: AlarmPlaylistLayout.CLASSIC_LATE,
            FirmwareTarget.CLASSIC_UPDATER_38_2_0_5: AlarmPlaylistLayout.CLASSIC_LATE,
            FirmwareTarget.NANO_3_1_1_3: AlarmPlaylistLayout.CLASSIC,
            FirmwareTarget.NANO_4_1_0_4: AlarmPlaylistLayout.NANO_4,
        }.get(support.alarm_firmware)
        if support.alarm_format is AlarmFormat.CLASSIC
        and support.alarm_firmware is not None
        else None
    )


def _legacy_sounds(
    support: ExtrasSupport, playlists: AlarmPlaylistCatalog | None
) -> tuple[AlarmSound, ...]:
    if not support.alarm_write or (
        alarm_playlist_layout(support) is None
        and support.alarm_firmware is not FirmwareTarget.NANO_5_1_0_2
    ):
        return ()
    if playlists is None or not playlists.complete:
        return (
            (AlarmSound(AlarmSound.Kind.BEEP, source_text("Beep"), playlist_index=-1),)
            if support.alarm_format is AlarmFormat.CLOCK
            else ()
        )
    if support.alarm_format is AlarmFormat.CLASSIC:
        return tuple(
            AlarmSound(
                AlarmSound.Kind.PLAYLIST,
                playlist.name,
                playlist.playlist_id,
                playlist.index - int(playlists.has_master),
            )
            for playlist in playlists.playlists
            if not playlist.is_master
        )
    return tuple(
        AlarmSound(
            AlarmSound.Kind.BEEP if playlist.is_master else AlarmSound.Kind.PLAYLIST,
            source_text("Beep") if playlist.is_master else playlist.name,
            playlist.playlist_id,
            (
                -1
                if playlist.is_master and support.alarm_format is AlarmFormat.CLOCK
                else playlist.index
            ),
        )
        for playlist in playlists.playlists
    )


def _legacy_sound_items(
    items: tuple[AlarmItem, ...],
    files: list[ExtrasFile],
    support: ExtrasSupport,
    sounds: tuple[AlarmSound, ...],
) -> tuple[AlarmItem, ...]:
    if support.alarm_format not in (
        AlarmFormat.MINI,
        AlarmFormat.MINI_1,
        AlarmFormat.CLOCK,
    ):
        return items
    source = next(
        (file for file in files if file.key == str(_alarm_path(support.alarm_format))),
        None,
    )
    if source is None or alarm_playlist_layout(support) is None:
        return items
    if support.alarm_format is AlarmFormat.CLOCK:
        records = parse_clock_alarms(source.data).records
        return tuple(
            replace(
                item,
                sound=next(
                    (
                        sound
                        for sound in sounds
                        if (
                            (
                                record.sound_mode == 0
                                and sound.kind is AlarmSound.Kind.BEEP
                            )
                            or (
                                record.sound_mode == 4
                                and sound.playlist_index == record.sound_selector
                            )
                        )
                    ),
                    None,
                ),
                sound_editable=record.can_edit_sound and bool(sounds),
                sound_description=source_text("Radio")
                if record.sound_mode == 12
                else "",
            )
            for item, record in zip(items, records, strict=True)
        )
    document = parse_preferences_alarm(source.data, support.alarm_format.value)
    selected = next(
        (sound for sound in sounds if sound.playlist_id == document.playlist_id), None
    )
    index = (
        selected.playlist_index
        if selected
        else (-1 if document.playlist_id == 0 else None)
    )
    return tuple(
        replace(
            item,
            sound=selected,
            sound_editable=document.can_edit_sound and bool(sounds),
            enabled_editable=item.enabled_editable
            or (item.editable and index is not None),
            playlist_index=index,
        )
        for item in items
    )


def alarm_sound_preconditions(
    catalog: ExtrasCatalog, change: ExtrasChange
) -> tuple[FilePrecondition, ...]:
    if not isinstance(change, SaveAlarm | CreateAlarm | CreateClockAlarm):
        return ()
    depends_on_library = (
        change.sound is not None and change.sound.playlist_id is not None
    )
    if (
        isinstance(change, SaveAlarm)
        and change.enabled is True
        and change.item.playlist_index is not None
    ):
        depends_on_library = True
    dependencies = (
        (
            *((catalog.playlist_source,) if catalog.playlist_source else ()),
            *catalog.playlist_dependencies,
        )
        if depends_on_library
        else ()
    )
    return (
        (*dependencies, *catalog.tone_dependencies)
        if change.sound is not None and change.sound.tone_name is not None
        else dependencies
    )


def _alarm_path(format: AlarmFormat) -> DevicePath:
    if format is AlarmFormat.CLASSIC:
        return ALARM_PATH
    if format is AlarmFormat.CLOCK:
        return CLOCK_PATH
    return PREFERENCES_PATH


def _read_timer(
    session: FilesystemSession,
    support: ExtrasSupport,
    files: list[ExtrasFile],
    issues: list[str],
    checkpoint: Callable[[], None],
) -> CountdownTimerSnapshot | None:
    profile = _timer_profile(support)
    if profile is None:
        return None
    captured_files: dict[DevicePath, bytes] = {}
    paths = (
        (SETTINGS_PATH, TIMER_PATH)
        if profile is NamedPreferencesProfile.NANO_6_1_2
        else (SETTINGS_PATH,)
    )
    for path in paths:
        checkpoint()
        try:
            if session.exists(path):
                captured = session.read_snapshot(path, max_bytes=MAX_FILE_BYTES)
                files.append(ExtrasFile(str(path), captured.data, captured.fingerprint))
                captured_files[path] = captured.data
        except (StorageError, ValueError) as error:
            if not session.is_active:
                raise
            issues.append(f"Timer: {error}")
    timer = parse_countdown_timer(
        captured_files.get(SETTINGS_PATH),
        profile=profile,
        timer_settings=captured_files.get(TIMER_PATH),
    )
    issues.extend(timer.issues)
    return timer


def _timer_profile(support: ExtrasSupport) -> NamedPreferencesProfile | None:
    profiles = {
        FirmwareTarget.NANO_6_1_2: NamedPreferencesProfile.NANO_6_1_2,
        FirmwareTarget.NANO_7_1_0_4: NamedPreferencesProfile.NANO_7_1_0_4,
        FirmwareTarget.NANO_UPDATER_39_1_1_2: NamedPreferencesProfile.NANO_UPDATER_39_1_1_2,
    }
    return profiles.get(support.alarm_firmware) if support.alarm_firmware else None


def timer_preconditions(catalog: ExtrasCatalog) -> tuple[FilePrecondition, ...]:
    """Bind an explicit timer edit, including no-ops, to its captured stores."""
    return tuple(
        FilePrecondition(DevicePath(file.key), file.fingerprint)
        for file in catalog.files
        if file.key in (str(SETTINGS_PATH), str(TIMER_PATH))
    )


def _prepare_timer_change(
    catalog: ExtrasCatalog,
    change: SaveTimerSettings,
    dependencies: tuple[FilePrecondition, ...],
) -> StorageTransaction | None:
    support = catalog.support
    if (
        support is None
        or not support.timer_settings_write
        or support.alarm_format is not AlarmFormat.TIMER
        or catalog.timer is None
        or (profile := _timer_profile(support)) is None
    ):
        raise ValueError("Saved timer editing is unavailable for this iPod.")
    sources = {file.key: file for file in catalog.files}
    settings = sources.get(str(SETTINGS_PATH))
    timer = sources.get(str(TIMER_PATH))
    changed = patch_countdown_timer(
        settings.data if settings else None,
        profile=profile,
        changes=change.changes,
        timer_settings=timer.data if timer else None,
    )
    writes: list[TransactionWrite] = []
    for source, data in (
        (settings, changed.settings),
        (timer, changed.timer_settings),
    ):
        if source is None or data is None or source.data == data:
            continue
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("The timer settings file exceeds the supported size.")
        writes.append(
            TransactionWrite(
                DevicePath(source.key),
                data,
                FileContent(len(data), hashlib.sha256(data).hexdigest()),
                expected=source.fingerprint,
            )
        )
    return (
        StorageTransaction(
            writes=tuple(writes),
            dependencies=tuple(
                dependency
                for dependency in dependencies
                if dependency.path not in {write.path for write in writes}
            ),
        )
        if writes
        else None
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
                    ALARM_LABELS[record.selection]
                    if record.selection is not None
                    and 0 <= record.selection < len(ALARM_LABELS)
                    else source_text("Alarm {number}", number=str(record.index + 1)),
                    record.scheduled,
                    record.repeat_mode,
                    record.can_edit_date and support.alarm_write,
                    "",
                    record.can_edit_repeat and support.alarm_write,
                    enabled=record.enabled,
                    enabled_editable=record.can_edit_enabled and support.alarm_write,
                    label_index=record.selection,
                    label_editable=record.can_edit_label and support.alarm_write,
                )
                for record in document.records
            ),
            document.issues,
        )
    if support.alarm_format is AlarmFormat.CLOCK:
        clock = parse_clock_alarms(data)
        return (
            tuple(
                AlarmItem(
                    record.index,
                    city.name
                    if (city := clock_city(record.region, record.city))
                    else source_text("Clock {number}", number=str(record.index + 1)),
                    record.time,
                    None,
                    record.editable and support.alarm_write,
                    enabled=record.enabled,
                    enabled_editable=record.can_edit_enabled and support.alarm_write,
                    clock_city=city,
                    daylight_saving=bool(record.daylight_saving)
                    if record.daylight_saving in (0, 1)
                    else None,
                    daylight_saving_editable=record.editable and support.alarm_write,
                )
                for record in clock.records
            ),
            clock.issues,
        )
    preferences = parse_preferences_alarm(data, support.alarm_format.value)
    return (
        (
            AlarmItem(
                0,
                source_text("Clock alarm"),
                preferences.time,
                None,
                preferences.editable and support.alarm_write,
                enabled=preferences.enabled,
                enabled_editable=preferences.can_edit_enabled and support.alarm_write,
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
    if isinstance(change, CreateTone):
        if (
            support.alarm_format is not AlarmFormat.CLASSIC
            or not support.alarm_write
            or not catalog.can_create_tone
        ):
            raise ValueError(
                "A new tone cannot be added to this iPod. Refresh Tones and check the available space."
            )
        if change.name in {
            "Beep",
            *(sound.tone_name for sound in catalog.alarm_sounds if sound.tone_name),
        }:
            raise ValueError(
                "A tone with this name already exists. Choose another name."
            )
        data = create_alarm_tone(change.name, change.notes)
        path = DevicePath(f"iPod_Control/Tones/iopenpod-{uuid4().hex}.tone")
        return StorageTransaction(
            writes=(
                TransactionWrite(
                    path,
                    data,
                    FileContent(len(data), hashlib.sha256(data).hexdigest()),
                    expected=None,
                ),
            ),
            dependencies=(*dependencies, *catalog.tone_dependencies),
        )
    if isinstance(change, SaveTimerSettings):
        return _prepare_timer_change(catalog, change, dependencies)
    if isinstance(change, CreateClockAlarm) or (
        isinstance(change, RemoveAlarm) and support.alarm_format is AlarmFormat.CLOCK
    ):
        if support.alarm_format is not AlarmFormat.CLOCK or not support.alarm_write:
            raise ValueError("City alarms are unavailable for this iPod.")
        path = CLOCK_PATH
        source = next((file for file in catalog.files if file.key == str(path)), None)
        clock_document = (
            parse_clock_alarms(source.data)
            if source is not None
            else empty_clock_document()
        )
        if isinstance(change, CreateClockAlarm):
            if not catalog.can_create_alarm or change.city not in catalog.clock_cities:
                raise ValueError("Choose a city from the current iPod Clock catalog.")
            if change.sound is None or change.sound not in catalog.alarm_sounds:
                raise ValueError("Choose an available sound for the city alarm.")
            clock_document = add_clock_alarm(
                clock_document, change.city, daylight_saving=change.daylight_saving
            )
            clock_document = update_clock_alarm(
                clock_document,
                len(clock_document.records) - 1,
                time=change.time,
                enabled=change.enabled,
                sound_playlist_index=change.sound.playlist_index,
            )
        else:
            if (
                source is None
                or change.item not in catalog.alarms
                or not change.item.editable
            ):
                raise ValueError("This city is not available for removal.")
            clock_document = remove_clock_alarm(clock_document, change.item.index)
        data = write_clock_alarms(clock_document)
    elif isinstance(change, CreateAlarm | RemoveAlarm):
        if support.alarm_format is not AlarmFormat.CLASSIC or not support.alarm_write:
            raise ValueError(
                "Alarm creation and removal are unavailable for this iPod."
            )
        path = ALARM_PATH
        source = next((file for file in catalog.files if file.key == str(path)), None)
        original = (
            parse_alarms(source.data) if source is not None else empty_alarm_document()
        )
        if isinstance(change, CreateAlarm):
            if not catalog.can_create_alarm:
                raise ValueError("Reload the saved alarms before creating an alarm.")
            if change.sound is not None and change.sound not in catalog.alarm_sounds:
                raise ValueError("This alarm sound changed. Reload before saving.")
            if change.sound is None or (
                not change.sound.tone_name
                and change.sound.kind is not AlarmSound.Kind.PLAYLIST
            ):
                raise ValueError("Choose a verified sound for the new alarm.")
            changed = add_alarm(
                original,
                scheduled=change.time,
                repeat_mode=change.repeat,
                enabled=change.enabled,
                label_index=change.label_index,
                tone_name=change.sound.tone_name or "",
                playlist_selector=change.sound.playlist_index
                if change.sound.kind is AlarmSound.Kind.PLAYLIST
                and change.sound.playlist_index is not None
                else 0xFFFFFFFF,
            )
        else:
            if (
                source is None
                or change.item not in catalog.alarms
                or not change.item.editable
            ):
                raise ValueError("This saved alarm is not available for removal.")
            changed = remove_alarm(original, change.item.index)
        data = write_alarms(changed)
    elif isinstance(change, SaveAlarm):
        if not support.alarm_write or change.item not in catalog.alarms:
            raise ValueError("This saved alarm is not available for editing.")
        if not change.item.editable:
            raise ValueError("This saved alarm has an unsupported record layout.")
        if change.repeat is not None and not change.item.repeat_editable:
            raise ValueError("This saved alarm's repeat field is not editable.")
        if (
            change.enabled is not None
            and not change.item.enabled_editable
            and change.sound is None
        ):
            raise ValueError("This saved alarm's enable state is not editable.")
        if change.label_index is not None and not change.item.label_editable:
            raise ValueError("This saved alarm's label is not editable.")
        if (
            change.daylight_saving is not None
            and not change.item.daylight_saving_editable
        ):
            raise ValueError(
                "This saved clock's daylight-saving setting is not editable."
            )
        if change.sound is not None and (
            not change.item.sound_editable or change.sound not in catalog.alarm_sounds
        ):
            raise ValueError("This alarm sound changed. Reload before saving.")
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
                enabled=change.enabled,
                label_index=change.label_index,
                tone_name=(change.sound.tone_name or "") if change.sound else None,
                playlist_selector=(
                    change.sound.playlist_index
                    if change.sound.kind is AlarmSound.Kind.PLAYLIST
                    else 0xFFFFFFFF
                )
                if change.sound
                else None,
            )
            data = write_alarms(alarm_document)
        elif support.alarm_format is AlarmFormat.CLOCK:
            path = CLOCK_PATH
            source = _source(catalog, str(path))
            if not isinstance(change.time, Time) or change.repeat is not None:
                raise ValueError("This Clock alarm stores only a time of day.")
            data = write_clock_alarms(
                update_clock_alarm(
                    parse_clock_alarms(source.data),
                    change.item.index,
                    time=change.time,
                    enabled=change.enabled,
                    sound_playlist_index=change.sound.playlist_index
                    if change.sound
                    else None,
                    daylight_saving=change.daylight_saving,
                )
            )
        elif support.alarm_format in {AlarmFormat.MINI, AlarmFormat.MINI_1}:
            path = PREFERENCES_PATH
            source = _source(catalog, str(path))
            if not isinstance(change.time, Time) or change.repeat is not None:
                raise ValueError("This Clock alarm stores only a time of day.")
            data = patch_preferences_alarm(
                parse_preferences_alarm(source.data, support.alarm_format.value),
                change.time,
                enabled=change.enabled,
                sound_playlist_id=change.sound.playlist_id if change.sound else None,
                sound_playlist_index=change.sound.playlist_index
                if change.sound
                else None,
                playlist_index=change.item.playlist_index,
            )
        else:
            raise ValueError("The alarm format is not qualified for this iPod.")
    else:
        if not support.calendar_write:
            raise ValueError("Calendar editing is unavailable for this iPod model.")
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
                document = parse_calendar(source.data)
                path = DevicePath(source.key)
            else:
                document = create_calendar(name="iOpenPod")
                path = DevicePath(f"Calendars/iopenpod-{uuid4().hex}.ics")
            data = serialize_calendar(add_entry(document, change.edit))
        else:
            item = (
                change.item
                if isinstance(change, (RemoveCalendar, SkipCalendarOccurrence))
                else change.existing
            )
            if item is None or item not in catalog.calendar:
                raise ValueError("This Calendar entry changed. Reload before editing.")
            source = _source(catalog, item.document_key)
            path = DevicePath(source.key)
            if path.parts[:-1] != CALENDAR_ROOT.parts:
                raise ValueError(
                    "Calendar edits must stay inside the Calendars folder."
                )
            document = parse_calendar(source.data)
            if isinstance(change, RemoveCalendar):
                document = remove_entry(document, item.index)
            elif isinstance(change, SkipCalendarOccurrence):
                document = skip_occurrence(
                    document, item.index, change.day, change.start_day
                )
            else:
                if not isinstance(change.edit, CalendarEntryChanges):
                    raise ValueError(
                        "An existing Calendar entry needs explicit changes."
                    )
                document = update_entry(document, item.index, change.edit)
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
