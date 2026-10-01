"""The selected timezone survives preparation, publication, and source adoption."""

import struct
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device

from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.models.device import DeviceCandidateIssueCode
from iOpenPod.app.services.device_time import resolve_device_time
from iPodDB.device_time import DeviceTimeSource
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.preferences import parse_preferences


def _prefs(city: int = 0x21) -> bytes:
    data = bytearray(2956)
    struct.pack_into("<h", data, 0xB70, city)
    return bytes(data)


def test_selected_preferences_control_saved_dates_and_adopted_source(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        path = device.root / "iPod_Control/Device/Preferences"
        path.write_bytes(_prefs())
        active = device.coordinator.select_device(
            device.active.candidate.id, reconcile_metadata=False
        )
        original_header = parse_iTunesDB(
            (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
        ).header.timezone_offset
        winter, summer = 1704085200, 1719806400
        desired = replace(
            active.library,
            tracks=tuple(
                replace(
                    t,
                    metadata=replace(
                        t.metadata,
                        last_modified=winter,
                        last_played=summer,
                        release_date=summer,
                    ),
                )
                for t in active.library.tracks
            ),
        )
        review = device.prepare(desired)
        assert review.result.prepared is not None, review.result.issues
        result = device.save(review)
        assert result.active is not None, result.issues
        assert device.active.library.tracks[0].metadata.last_played == summer
        native = parse_iTunesDB(
            (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
        )
        first = native.find_chunks(MhitHeader)[0].chunk.header
        assert first.last_modified == winter + 2082844800 - 18000
        assert first.last_played == summer + 2082844800 - 14400
        assert first.date_released == summer + 2082844800
        assert native.header.timezone_offset == original_header
        assert path.read_bytes() == _prefs()
        # A second save uses the adopted geographical context too.
        next_snapshot = replace(
            device.active.library,
            tracks=tuple(
                replace(t, metadata=replace(t.metadata, last_played=winter))
                for t in device.active.library.tracks
            ),
        )
        second = device.prepare(next_snapshot)
        assert second.result.prepared is not None, second.result.issues
        assert device.save(second).active is not None
        assert device.active.library.tracks[0].metadata.last_played == winter
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("initially_present", [True, False])
@pytest.mark.parametrize("change_after_review", [True, False])
def test_timezone_changes_or_appearance_invalidate_preparation_and_save(
    tmp_path: Path, initially_present: bool, change_after_review: bool
) -> None:
    device = build_device(tmp_path)
    try:
        path = device.root / "iPod_Control/Device/Preferences"
        if initially_present:
            path.write_bytes(_prefs())
            device.coordinator.select_device(
                device.active.candidate.id, reconcile_metadata=False
            )
        active = device.active
        database = device.root / "iPod_Control/iTunes/iTunesDB"
        original = database.read_bytes()
        desired = replace(active.library, device_name="Changed name")
        if not change_after_review:
            path.write_bytes(_prefs(0x69))
        review = device.prepare(desired)
        if change_after_review:
            assert review.result.prepared is not None, review.result.issues
            path.write_bytes(_prefs(0x69))
            saved = device.save(review)
            assert saved.active is None
        else:
            assert review.result.prepared is None
        assert database.read_bytes() == original
    finally:
        device.coordinator.close()


def test_unknown_city_reports_fixed_header_fallback(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        (device.root / "iPod_Control/Device/Preferences").write_bytes(_prefs(0))
        active = device.coordinator.select_device(
            device.active.candidate.id, reconcile_metadata=False
        )
        assert any(
            issue.code is DeviceCandidateIssueCode.TIMEZONE_UNCERTAIN
            and "fixed offset" in issue.detail
            for issue in active.candidate.issues
        )
        context = resolve_device_time(parse_preferences(_prefs(0)))
        assert context.source is DeviceTimeSource.UNRESOLVED
        assert context.zone is None
    finally:
        device.coordinator.close()


def test_unverified_preferences_leave_library_readable_but_block_save(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        (device.root / "iPod_Control/Device/Preferences").write_bytes(
            bytes(1024 * 1024 + 1)
        )
        active = device.coordinator.select_device(
            device.active.candidate.id, reconcile_metadata=False
        )
        request = LibraryPreparationRequest(
            replace(active.library, device_name="Changed"), active, 1, 1
        )
        result = device.coordinator.prepare_library(request, lambda _: None, Event())
        assert result.result.prepared is None
        assert active.library.tracks
    finally:
        device.coordinator.close()
