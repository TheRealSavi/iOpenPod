"""Named calendars retain source identity through grouped publication."""

from pathlib import Path

import pytest
from whenever import Date

from device_registry import ExtrasSupport
from iOpenPod.app.models.extras import (
    CreateCalendar,
    ImportCalendar,
    RenameCalendar,
    SaveCalendar,
)
from iOpenPod.app.services.extras import prepare_change, read_extras
from iPodDB.calendar import (
    CalendarEntryDraft,
    CalendarFrequency,
    CalendarRecurrenceRule,
    CalendarReminderDraft,
    create_calendar,
    serialize_calendar,
)
from storage import AccessMode, FilePreconditionError, Storage
from storage.testing import VirtualStoragePlatform

SUPPORT = ExtrasSupport(calendar_write=True)


def _storage(root: Path) -> Storage:
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    return Storage(platform)


def test_capture_uses_native_status_instead_of_host_completion_timestamp(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Calendars"
    folder.mkdir()
    raw = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\n"
        b"SUMMARY:Task\r\nCOMPLETED:20261101T090000Z\r\n"
        b"END:VTODO\r\nEND:VCALENDAR\r\n"
    )
    (folder / "task.ics").write_bytes(raw)
    storage = _storage(tmp_path)
    support = ExtrasSupport(calendar_write=True)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, support, lambda: None)
        assert not catalog.calendar[0].entry.completed
        assert catalog.files[0].data == raw


def test_empty_calendars_and_exact_names_survive_capture_and_destination_edits(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Calendars"
    folder.mkdir()
    for index, name in enumerate(("Work", "Personal", "work")):
        (folder / f"{index}.ics").write_bytes(
            serialize_calendar(create_calendar(name=name))
        )
    storage = _storage(tmp_path)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, SUPPORT, lambda: None)
        assert [group.name for group in catalog.calendars] == [
            "Work",
            "Personal",
            "work",
        ]
        assert not catalog.calendar
        group = catalog.calendars[1]
        transaction = prepare_change(
            catalog,
            SaveCalendar(
                CalendarEntryDraft(summary="Visit", start=Date(2026, 11, 8)),
                destination=group,
            ),
            checkpoint=lambda: None,
        )
        assert transaction is not None
        result = session.execute_transaction(transaction)
        session.finalize_transaction(result.recovery)
        updated = read_extras(session, SUPPORT, lambda: None)
        assert len(updated.files) == 3
        assert updated.calendar[0].calendar_name == "Personal"
        assert updated.calendar[0].document_key == "Calendars/1.ics"


@pytest.mark.parametrize("external_change", (False, True))
def test_rename_updates_every_group_member_and_rejects_stale_sources(
    tmp_path: Path, external_change: bool
) -> None:
    folder = tmp_path / "Calendars"
    folder.mkdir()
    original = serialize_calendar(create_calendar(name="Work"))
    for index in range(2):
        (folder / f"{index}.ics").write_bytes(original)
    storage = _storage(tmp_path)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, SUPPORT, lambda: None)
        assert len(catalog.calendars) == 1
        transaction = prepare_change(
            catalog,
            RenameCalendar(catalog.calendars[0], "Team"),
            checkpoint=lambda: None,
        )
        assert transaction is not None and len(transaction.writes) == 2
        if external_change:
            (folder / "1.ics").write_bytes(b"external change")
            with pytest.raises(FilePreconditionError):
                session.execute_transaction(transaction)
            assert (folder / "0.ics").read_bytes() == original
        else:
            result = session.execute_transaction(transaction)
            session.finalize_transaction(result.recovery)
            assert all(
                path.read_bytes() == original.replace(b":Work", b":Team")
                for path in folder.iterdir()
            )


def test_named_import_and_new_calendar_preserve_empty_containers(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ipod"
    root.mkdir()
    host = tmp_path / "import.ics"
    original = serialize_calendar(create_calendar(name="Old"))
    host.write_bytes(original)
    storage = _storage(root)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        for change in (
            CreateCalendar("Personal"),
            ImportCalendar(str(host), "Imported"),
        ):
            catalog = read_extras(session, SUPPORT, lambda: None)
            transaction = prepare_change(catalog, change, checkpoint=lambda: None)
            assert transaction is not None
            result = session.execute_transaction(transaction)
            session.finalize_transaction(result.recovery)
        catalog = read_extras(session, SUPPORT, lambda: None)
        assert {group.name for group in catalog.calendars} == {"Personal", "Imported"}
        assert not catalog.calendar
        assert host.read_bytes() == original
        with pytest.raises(ValueError, match="already exists"):
            prepare_change(catalog, CreateCalendar("Personal"), checkpoint=lambda: None)


def test_publication_uses_shared_calendar_writer(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    support = ExtrasSupport(calendar_write=True)
    repeat = CalendarRecurrenceRule(CalendarFrequency.DAILY, count=3)
    reminder = CalendarReminderDraft(-900)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        catalog = read_extras(session, support, lambda: None)
        from whenever import PlainDateTime

        draft = CalendarEntryDraft(
            summary="Qualified",
            start=PlainDateTime(2026, 11, 1, 9),
            end=PlainDateTime(2026, 11, 1, 10),
            recurrence=repeat,
            reminder=reminder,
        )
        transaction = prepare_change(
            catalog, SaveCalendar(draft), checkpoint=lambda: None
        )
        assert transaction is not None
        result = session.execute_transaction(transaction)
        session.finalize_transaction(result.recovery)
        updated = read_extras(session, support, lambda: None)
        entry = updated.calendar[0].entry
        assert entry.has_recurrence
        assert entry.reminders
