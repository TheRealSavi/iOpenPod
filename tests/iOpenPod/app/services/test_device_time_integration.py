"""The selected timezone survives preparation, publication, and source adoption."""

import struct
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iPodDB.library.test_writing import library

from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.models.device import DeviceCandidateIssueCode
from iOpenPod.app.services.device_time import resolve_device_time
from iPodDB.device_time import DeviceTimeSource, mac_to_unix
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary
from iPodDB.preferences import PreferencesProfile, parse_preferences


def _prefs(city: int = 0x21) -> bytes:
    data = bytearray(2956)
    struct.pack_into("<h", data, 0xB70, city)
    return bytes(data)


@pytest.mark.parametrize(
    "city,name,instant",
    (
        (0x18, "America/Costa_Rica", 1704088800),
        (0x36, "America/Puerto_Rico", 1704081600),
        (0x41, "America/Sao_Paulo", 1704078000),
        (0x95, "Indian/Mahe", 1704052800),
    ),
)
@pytest.mark.parametrize(
    "profile", (PreferencesProfile.STANDARD, PreferencesProfile.CLASSIC_120GB_2_0_1)
)
def test_corrected_city_resolves_literal_calendar_word_without_rewriting_database(
    city: int, name: str, instant: int, profile: PreferencesProfile
) -> None:
    data = bytearray(_prefs(city))
    struct.pack_into("<I", data, 0, 0x3D)
    context = resolve_device_time(parse_preferences(data, profile=profile))
    assert context.source is DeviceTimeSource.PREFERENCES_CITY
    assert context.timezone_name == name
    # 2024-01-01 00:00:00 as a calendar-shaped Mac word. Expected UTC
    # instants are literals, independent of the conversion implementation.
    assert mac_to_unix(3786912000, context) == instant
    document = parse_iTunesDB(library().serialize().itunes)
    slot = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(
        slot,
        replace(slot.chunk, header=replace(slot.chunk.header, last_played=3786912000)),
    )
    raw = write_iTunesDB(document)
    source = IPodLibrary.parse(raw, device_time=context)
    assert source.snapshot.tracks[0].metadata.last_played == instant
    assert source.serialize().itunes == raw
    prepared = source.prepare(source.analyze(source.begin_draft())).prepared
    assert prepared is not None
    assert prepared.itunes == raw


@pytest.mark.parametrize("offset", (-18000, 0, 86400))
def test_qualified_classic_unresolved_city_explains_existing_header_fallback(
    offset: int,
) -> None:
    data = bytearray(_prefs(0x26))
    struct.pack_into("<I", data, 0, 0x3D)
    context = resolve_device_time(
        parse_preferences(data, profile=PreferencesProfile.CLASSIC_120GB_2_0_1)
    )
    assert context.source is DeviceTimeSource.UNRESOLVED
    assert context.zone is None and context.timezone_name is None
    assert "city 0x26" in context.detail and "legacy London" in context.detail
    document = parse_iTunesDB(library().serialize().itunes)
    raw = write_iTunesDB(
        replace(document, header=replace(document.header, timezone_offset=offset))
    )
    source = IPodLibrary.parse(raw, device_time=context)
    if offset == 86400:
        assert source.device_time.source is DeviceTimeSource.UNRESOLVED
        code = "source.timezone_unresolved"
        with pytest.raises(ValueError, match="unresolved"):
            mac_to_unix(3786912000, source.device_time)
    else:
        assert source.device_time.source is DeviceTimeSource.DATABASE_HEADER
        assert mac_to_unix(3786912000, source.device_time) == 1704067200 - offset
        code = "source.timezone_fallback"
    issue = next(item for item in source.time_warnings if item.code == code)
    assert issue.detail == context.detail
    assert source.serialize().itunes == raw


def test_qualified_classic_city_conflict_reaches_inspection_and_save_warning(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        metadata = device.root / "iPod_Control/Device"
        sysinfo = metadata / "SysInfo"
        sysinfo.write_text(
            sysinfo.read_text(encoding="utf-8") + "visibleBuildID: 2.0.1\n",
            encoding="utf-8",
        )
        data = bytearray(_prefs(0x26))
        struct.pack_into("<I", data, 0, 0x3D)
        path = metadata / "Preferences"
        path.write_bytes(data)
        candidate = device.coordinator.discover_devices().candidates[0]
        active = device.coordinator.select_device(
            candidate.id, reconcile_metadata=False
        )
        warning = next(
            issue
            for issue in active.candidate.issues
            if issue.code is DeviceCandidateIssueCode.TIMEZONE_UNCERTAIN
            and "city 0x26" in issue.detail
        )
        assert "fixed offset" in warning.detail
        assert "legacy London" in warning.detail
        assert "cannot recover historical city rules" in warning.detail
        review = device.prepare(replace(active.library, device_name="Changed"))
        assert review.result.prepared is not None, review.result.issues
        warning_at_save = next(
            issue
            for issue in review.result.issues
            if issue.code == "source.timezone_fallback"
        )
        assert "city 0x26" in warning_at_save.detail
        assert device.save(review).active is not None
        assert path.read_bytes() == data
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("dst", (0, 1, 60, 255))
def test_classic_saved_dst_and_bias_do_not_shift_historical_city_rules(
    dst: int,
) -> None:
    data = bytearray(_prefs())
    struct.pack_into("<I", data, 0, 0x3D)
    data[0xB6C] = dst
    struct.pack_into("<iI", data, 0xB78, -1, 81000)
    context = resolve_device_time(
        parse_preferences(data, profile=PreferencesProfile.CLASSIC_120GB_2_0_1)
    )
    assert context.source is DeviceTimeSource.PREFERENCES_CITY
    assert "firmware DST rules" in context.detail
    assert mac_to_unix(1704067200 + 2082844800, context) == 1704085200
    assert mac_to_unix(1719792000 + 2082844800, context) == 1719806400


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
