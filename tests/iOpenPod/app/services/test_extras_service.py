"""Extras publication through virtual Storage, preservation and stale edits."""

import plistlib
import struct
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iPodDB.binary_fixtures import dataset, itunes_database, list_chunk
from whenever import Date, PlainDateTime, Time

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    AlarmFormat,
    DeviceEvidence,
    DeviceIdentifier,
    EvidenceAuthority,
    ExtrasSupport,
    FeatureSupport,
    resolve_extras_support,
)
from iOpenPod.app.models.extras import (
    ImportCalendar,
    RemoveCalendar,
    SaveAlarm,
    SaveCalendar,
    SkipCalendarOccurrence,
)
from iOpenPod.app.services.device_coordinator import (
    DeviceChangedError,
    DeviceCoordinator,
)
from iOpenPod.app.services.extras import prepare_change, read_extras
from iPodDB.calendar import (
    CalendarEntryChanges,
    CalendarEntryDraft,
    CalendarEntryKind,
    project_occurrences,
)
from storage import AccessMode, FilePreconditionError, Storage, StorageError
from storage.testing import VirtualStoragePlatform

SUPPORT = ExtrasSupport(True, AlarmFormat.CLASSIC, True, FeatureSupport.SUPPORTED)
SOURCE = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-KEEP:opaque\r\n"
    b"BEGIN:VEVENT\r\nUID:event\r\nDTSTART;TZID=Missing/Zone:20260308T023000\r\n"
    b"RRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:Before\r\nEND:VEVENT\r\n"
    b"BEGIN:VTODO\r\nUID:task\r\nDUE:broken-date\r\nSUMMARY:Task\r\nEND:VTODO\r\n"
    b"END:VCALENDAR\r\n"
)


def test_calendar_transaction_preserves_unknown_dates_zones_and_other_entries(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Calendars"
    folder.mkdir()
    path = folder / "existing.ics"
    path.write_bytes(SOURCE)
    (folder / "damaged.ics").write_bytes(b"unrelated broken stream")
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, SUPPORT, lambda: None)
        assert len(catalog.calendar) == 2
        assert catalog.issues
        transaction = prepare_change(
            catalog,
            SaveCalendar(CalendarEntryChanges(summary="After"), catalog.calendar[0]),
            checkpoint=lambda: None,
        )
        assert transaction is not None
        result = session.execute_transaction(transaction)
        assert result.flush.complete
        session.finalize_transaction(result.recovery)
        assert path.read_bytes() == SOURCE.replace(b"SUMMARY:Before", b"SUMMARY:After")
        assert (folder / "damaged.ics").read_bytes() == b"unrelated broken stream"


def test_create_todo_and_import_preserve_selected_bytes(tmp_path: Path) -> None:
    root = tmp_path / "device"
    root.mkdir()
    imported = tmp_path / "import.ics"
    imported.write_bytes(SOURCE)
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        empty = read_extras(session, SUPPORT, lambda: None)
        for change in (
            SaveCalendar(
                CalendarEntryDraft(
                    kind=CalendarEntryKind.TODO, summary="Pack", due=Date(2026, 11, 8)
                )
            ),
            ImportCalendar(str(imported)),
        ):
            transaction = prepare_change(empty, change, checkpoint=lambda: None)
            assert transaction is not None
            result = session.execute_transaction(transaction)
            session.finalize_transaction(result.recovery)
        catalog = read_extras(session, SUPPORT, lambda: None)
        assert len(catalog.calendar) == 3
        assert SOURCE in [file.data for file in catalog.files]
        todo = next(item for item in catalog.calendar if item.entry.summary == "Pack")
        assert todo.entry.due is not None
        assert todo.entry.due.value == Date(2026, 11, 8)
        transaction = prepare_change(
            catalog, RemoveCalendar(todo), checkpoint=lambda: None
        )
        assert transaction is not None
        result = session.execute_transaction(transaction)
        session.finalize_transaction(result.recovery)
        assert len(read_extras(session, SUPPORT, lambda: None).calendar) == 2


def test_external_calendar_change_rejects_stale_edit(tmp_path: Path) -> None:
    folder = tmp_path / "Calendars"
    folder.mkdir()
    path = folder / "existing.ics"
    path.write_bytes(SOURCE)
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, SUPPORT, lambda: None)
        transaction = prepare_change(
            catalog,
            SaveCalendar(CalendarEntryChanges(summary="Edit"), catalog.calendar[0]),
            checkpoint=lambda: None,
        )
        assert transaction is not None
        path.write_bytes(SOURCE + b"external change")
        with pytest.raises((FilePreconditionError, StorageError)):
            session.execute_transaction(transaction)
        assert path.read_bytes() == SOURCE + b"external change"


def test_skip_occurrence_publishes_only_its_exdate_with_source_precondition(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Calendars"
    folder.mkdir()
    path = folder / "repeats.ics"
    raw = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:series\r\n"
        b"DTSTART:20261101T090000\r\nDTEND:20261101T100000\r\n"
        b"RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    path.write_bytes(raw)
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    date = Date(2026, 11, 8)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, SUPPORT, lambda: None)
        transaction = prepare_change(
            catalog,
            SkipCalendarOccurrence(catalog.calendar[0], date, date),
            checkpoint=lambda: None,
        )
        assert transaction is not None
        path.write_bytes(raw + b"external change")
        with pytest.raises((FilePreconditionError, StorageError)):
            session.execute_transaction(transaction)
        path.write_bytes(raw)
        catalog = read_extras(session, SUPPORT, lambda: None)
        transaction = prepare_change(
            catalog,
            SkipCalendarOccurrence(catalog.calendar[0], date, date),
            checkpoint=lambda: None,
        )
        assert transaction is not None
        result = session.execute_transaction(transaction)
        session.finalize_transaction(result.recovery)
        assert path.read_bytes() == raw.replace(
            b"END:VEVENT", b"EXDATE:20261108\r\nEND:VEVENT"
        )
        updated = read_extras(session, SUPPORT, lambda: None).calendar[0].entry
        assert not project_occurrences(updated, date, date).occurrences


def test_mini_alarm_changes_only_minute_word(tmp_path: Path) -> None:
    device = tmp_path / "iPod_Control/Device"
    device.mkdir(parents=True)
    original = bytearray(2876)
    struct.pack_into("<I", original, 0, 0x16)
    struct.pack_into("<H", original, 0xB22, 0xA000 | 90)
    (device / "Preferences").write_bytes(original)
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    support = replace(SUPPORT, alarm_format=AlarmFormat.MINI)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, support, lambda: None)
        assert catalog.alarms[0].time == Time(1, 30)
        transaction = prepare_change(
            catalog, SaveAlarm(catalog.alarms[0], Time(7, 45)), checkpoint=lambda: None
        )
        assert transaction is not None
        result = session.execute_transaction(transaction)
        session.finalize_transaction(result.recovery)
    expected = bytearray(original)
    struct.pack_into("<H", expected, 0xB22, 0xA000 | 465)
    assert (device / "Preferences").read_bytes() == expected


@pytest.mark.parametrize("minutes, kind", ((90, 0), (4095, 0), (0, 8)))
def test_video_invalid_clock_does_not_fall_back_to_projection_or_block_calendar(
    tmp_path: Path, minutes: int, kind: int
) -> None:
    device = tmp_path / "iPod_Control/Device"
    device.mkdir(parents=True)
    original = bytearray(2924)
    struct.pack_into("<I", original, 0, 0x39)
    struct.pack_into("<H", original, 0xB18, 0x20 | kind)
    struct.pack_into("<H", original, 0xB22, 0xA000 | minutes)
    (device / "Preferences").write_bytes(original)
    clock = b"retained per-city Clock records"
    (device / "clock").write_bytes(clock)
    profile = next(
        p
        for p in DEFAULT_DEVICE_REGISTRY.profiles
        if (p.family, p.generation) == ("iPod", "5th Gen")
    )
    support = resolve_extras_support(
        profile,
        DeviceEvidence(
            firmware_versions=(
                DeviceIdentifier("1.3", "test", EvidenceAuthority.CURRENT_HARDWARE),
            ),
            updater_family_ids=(
                DeviceIdentifier(13, "test", EvidenceAuthority.CURRENT_HARDWARE),
            ),
        ),
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, support, lambda: None)
        assert not catalog.alarms
        assert catalog.issues
        assert support.alarm_write
        assert "iPod_Control/Device/Preferences" not in [
            file.key for file in catalog.files
        ]
        transaction = prepare_change(
            catalog,
            SaveCalendar(
                CalendarEntryDraft(summary="Keep working", start=Date(2026, 11, 7))
            ),
            checkpoint=lambda: None,
        )
        assert transaction is not None
        result = session.execute_transaction(transaction)
        session.finalize_transaction(result.recovery)
        assert (
            read_extras(session, support, lambda: None).calendar[0].entry.summary
            == "Keep working"
        )
    assert (device / "Preferences").read_bytes() == original
    assert (device / "clock").read_bytes() == clock


def test_coordinator_issues_catalog_and_rejects_old_revision(tmp_path: Path) -> None:
    root = tmp_path / "device"
    device = root / "iPod_Control/Device"
    database = root / "iPod_Control/iTunes"
    device.mkdir(parents=True)
    database.mkdir(parents=True)
    (device / "SysInfo").write_text("ModelNumStr: MB565\n", encoding="utf-8")
    (database / "iTunesDB").write_bytes(
        itunes_database(dataset(1, list_chunk(b"mhlt")))
    )
    (root / "iPod_Control/Device/SysInfoExtended").write_bytes(
        plistlib.dumps({"VisibleBuildID": "2.0.1", "UpdaterFamilyID": 33})
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        catalog = coordinator.load_extras(active, Event())
        assert catalog.support is not None and catalog.support.calendar_write
        change = SaveCalendar(
            CalendarEntryDraft(summary="Fold", start=PlainDateTime(2026, 11, 1, 1, 30))
        )
        # Calendar is independent of changing or contradictory alarm evidence.
        (device / "SysInfoExtended").write_bytes(
            plistlib.dumps({"VisibleBuildID": "9.9.9", "UpdaterFamilyID": 999})
        )
        updated = coordinator.save_extras(active, catalog, change, Event())
        assert updated.calendar[0].entry.summary == "Fold"
        with pytest.raises(DeviceChangedError, match="Reload"):
            coordinator.save_extras(active, catalog, change, Event())
        assert coordinator.active_ipod is active
    finally:
        coordinator.close()


def test_unsupported_model_and_cancelled_read_do_not_write(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    with storage.open_session(storage.discover().volumes[0]) as session:
        catalog = read_extras(session, ExtrasSupport(), lambda: None)
        with pytest.raises(ValueError, match="unavailable"):
            prepare_change(
                catalog,
                SaveCalendar(CalendarEntryDraft(summary="No", start=Date(2026, 11, 7))),
                checkpoint=lambda: None,
            )

        def cancelled() -> None:
            raise RuntimeError("cancelled")

        with pytest.raises(RuntimeError, match="cancelled"):
            read_extras(session, SUPPORT, cancelled)
    assert not (tmp_path / "Calendars").exists()
