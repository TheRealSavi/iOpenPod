"""All latest Classic calendar profiles use qualified, non-blocking evidence."""

import plistlib
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iPodDB.sidecars.test_sidecar_readers import counts
from tests.iPodDB.test_classic_calendar_preferences import (
    CLASSIC_TARGETS,
    classic_preferences,
)

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.models.ipod_preferences import PreferenceFileStatus
from iOpenPod.app.services.classic_calendar import resolve_classic_calendar
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.app.services.ipod_preferences import capture_ipod_preferences
from iPodDB.device_time import DeviceTimeSource
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library.writing import IssueSeverity
from iPodDB.preferences import PreferencesProfile
from storage import HardwareProbeObservation, HardwareProbeResult, Storage
from storage.testing import VirtualStoragePlatform


@pytest.mark.parametrize("family,release,model,size,version,profile", CLASSIC_TARGETS)
def test_latest_target_qualification_requires_consistent_identity(
    family: int,
    release: str,
    model: str,
    size: int,
    version: int,
    profile: PreferencesProfile,
) -> None:
    device = DEFAULT_DEVICE_REGISTRY.profile_for_model_number(model)
    assert device is not None
    target = resolve_classic_calendar(device, (release,), (family,))
    assert target is not None and target.preferences_profile is profile
    assert (
        resolve_classic_calendar(device, (release, release), (family, family)) == target
    )
    assert resolve_classic_calendar(device, (), (family,)) is None
    assert resolve_classic_calendar(device, (release, "1.62"), (family,)) is None
    assert resolve_classic_calendar(device, (release,), (family, 999)) is None
    assert resolve_classic_calendar(device, (release,), (999,)) is None
    assert resolve_classic_calendar(device, ("2.0.3",), (family,)) is None
    missing_family = resolve_classic_calendar(device, (release,), ())
    assert missing_family == (target if family in (24, 33) else None)
    assert (
        resolve_classic_calendar(
            replace(device, family="iPod Nano"), (release,), (family,)
        )
        is None
    )


@pytest.mark.parametrize("family,release,model,size,version,profile", CLASSIC_TARGETS)
@pytest.mark.parametrize("city", (41, 0x10029))
def test_latest_calendar_inspection_exposes_full_city_saved_dst_and_bias(
    tmp_path: Path,
    family: int,
    release: str,
    model: str,
    size: int,
    version: int,
    profile: PreferencesProfile,
    city: int,
) -> None:
    root = _ipod_volume(tmp_path / "ipod", model_number=model)
    metadata = root / "iPod_Control/Device"
    source = classic_preferences(size, version, city)
    (metadata / "Preferences").write_bytes(source)
    rows = b"".join(
        struct.pack("<HBBB3sHHHH", city, 1, 0, 0, b"raw", 3, 2, 11, 1)
        for city in range(1, 206)
    )
    dst = (b"\xff\xa5" if family in (35, 38) else b"") + rows
    (metadata / "dst").write_bytes(dst)
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    device = DEFAULT_DEVICE_REGISTRY.profile_for_model_number(model)
    assert device is not None
    with storage.open_session(storage.discover().volumes[0]) as session:
        captured = capture_ipod_preferences(
            session, device, firmware_versions=(release,), updater_family_ids=(family,)
        )
    values = {row.key: row.value for row in captured.sections[0].rows}
    assert values["timezone"] == (
        "America/New_York" if city == 41 else "Unknown (city 65577)"
    )
    assert values["daylight_saving"] == "On (raw 60)"
    assert values["clock_bias_days"] == "-1"
    assert values["clock_bias_seconds"] == "4294967295"
    assert captured.device_time.source is (
        DeviceTimeSource.PREFERENCES_CITY if city == 41 else DeviceTimeSource.UNRESOLVED
    )
    assert captured.daylight_saving_rules is not None
    assert captured.daylight_saving_rules.serialize() == dst
    assert captured.daylight_saving_rules.complete == (family != 24)
    assert (metadata / "Preferences").read_bytes() == source
    assert (metadata / "dst").read_bytes() == dst


@pytest.mark.parametrize("family,release,model,size,version,profile", CLASSIC_TARGETS)
def test_wrong_preferences_format_cannot_alias_full_city_to_low_halfword(
    tmp_path: Path,
    family: int,
    release: str,
    model: str,
    size: int,
    version: int,
    profile: PreferencesProfile,
) -> None:
    root = _ipod_volume(tmp_path / "ipod", model_number=model)
    (root / "iPod_Control/Device/Preferences").write_bytes(
        classic_preferences(size, version + 1, 0x10029)
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    device = DEFAULT_DEVICE_REGISTRY.profile_for_model_number(model)
    assert device is not None
    with storage.open_session(storage.discover().volumes[0]) as session:
        captured = capture_ipod_preferences(
            session, device, firmware_versions=(release,), updater_family_ids=(family,)
        )
    assert captured.sections[0].status is PreferenceFileStatus.UNKNOWN
    assert captured.sections[0].rows == ()
    assert captured.device_time.source is DeviceTimeSource.UNRESOLVED


@pytest.mark.parametrize("family,release,model,size,version,profile", CLASSIC_TARGETS)
@pytest.mark.parametrize(
    "native", (3855781800, 3876341400), ids=("spring-gap", "autumn-fold")
)
def test_latest_classics_commit_uncertain_playback_dates_without_native_changes(
    tmp_path: Path,
    family: int,
    release: str,
    model: str,
    size: int,
    version: int,
    profile: PreferencesProfile,
    native: int,
) -> None:
    device = build_device(tmp_path, model=model)
    try:
        metadata = device.root / "iPod_Control/Device"
        sysinfo = metadata / "SysInfo"
        sysinfo.write_text(
            sysinfo.read_text(encoding="utf-8")
            + f"visibleBuildID: {release}\nUpdaterFamilyID: {family}\n",
            encoding="utf-8",
        )
        prefs = classic_preferences(size, version)
        (metadata / "Preferences").write_bytes(prefs)
        (metadata / "dst").write_bytes(b"partial optional rules")
        directory = device.root / "iPod_Control/iTunes"
        path = directory / "Play Counts"
        raw_counts = counts(((2, native, 0, 0xFFFFFFFF, 0, 3, native),))
        path.write_bytes(raw_counts)
        active = device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id,
            reconcile_metadata=False,
        )
        assert active.library.tracks[0].play_count == 2
        assert active.library.tracks[0].metadata.skip_count == 3
        assert not path.exists()
        assert path.with_name("Play Counts.bak").read_bytes() == raw_counts
        header = (
            parse_iTunesDB((directory / "iTunesDB").read_bytes())
            .find_chunks(MhitHeader)[0]
            .chunk.header
        )
        assert header.last_played == header.last_skipped == native
        review = device.prepare(
            replace(active.library, device_name="Latest Classic calendar")
        )
        assert review.result.prepared is not None, review.result.issues
        (metadata / "Preferences").write_bytes(b"changed after preparation")
        assert device.save(review).active is not None
        assert (metadata / "Preferences").read_bytes() == b"changed after preparation"
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("family,release,model,size,version,profile", CLASSIC_TARGETS)
@pytest.mark.parametrize(
    "city,zone",
    (
        (0x29, "America/New_York"),
        (0xA4, "Asia/Singapore"),
        (0, "Unknown (city 0)"),
        (0x26, "Unknown (city 38)"),
        (0xFFFFFFFF, "Unknown (city 4294967295)"),
    ),
)
def test_reloaded_clock_changes_do_not_rebase_retained_track_dates(
    tmp_path: Path,
    family: int,
    release: str,
    model: str,
    size: int,
    version: int,
    profile: PreferencesProfile,
    city: int,
    zone: str,
) -> None:
    device = build_device(tmp_path, model=model)
    try:
        metadata = device.root / "iPod_Control/Device"
        sysinfo = metadata / "SysInfo"
        sysinfo.write_text(
            sysinfo.read_text(encoding="utf-8")
            + f"visibleBuildID: {release}\nUpdaterFamilyID: {family}\n",
            encoding="utf-8",
        )
        preferences = metadata / "Preferences"
        preferences.write_bytes(classic_preferences(size, version))
        database = device.root / "iPod_Control/iTunes/iTunesDB"
        document = parse_iTunesDB(database.read_bytes())
        date_words = {
            "last_modified": 1,
            "date_added": 0xFFFFFFFF,
            "last_played": 3855781800,  # New York spring gap.
            "last_skipped": 3876341400,  # New York autumn fold.
            "date_released": 2082844800,  # Nonzero native word, semantic Unix zero.
            "date_added_to_itunes": 0,
        }
        for slot in document.find_chunks(MhitHeader):
            document = document.replace_chunk(
                slot,
                replace(
                    slot.chunk,
                    header=replace(
                        slot.chunk.header,
                        last_modified=date_words["last_modified"],
                        date_added=date_words["date_added"],
                        last_played=date_words["last_played"],
                        last_skipped=date_words["last_skipped"],
                        date_released=date_words["date_released"],
                        date_added_to_itunes=date_words["date_added_to_itunes"],
                    ),
                ),
            )
        original = write_iTunesDB(document)
        database.write_bytes(original)
        candidate = device.coordinator.discover_devices().candidates[0]
        before = device.coordinator.select_device(
            candidate.id, reconcile_metadata=False
        )

        # This represents changed observations on reselection, not a Host clock
        # command or a claim that every firmware notification recipient is known.
        changed = bytearray(classic_preferences(size, version, city))
        changed[0xB6C] = 255
        struct.pack_into("<iI", changed, 0xB78, -2147483648, 12345)
        preferences.write_bytes(changed)
        after = device.coordinator.select_device(candidate.id, reconcile_metadata=False)
        values = {row.key: row.value for row in after.preferences[0].rows}
        assert values["timezone"] == zone
        if city == 0x29:
            assert before.library.tracks == after.library.tracks
        else:
            assert (
                before.library.tracks[0].metadata.last_played
                != after.library.tracks[0].metadata.last_played
            )
        assert database.read_bytes() == original
        review = device.prepare(replace(after.library, device_name="Clock changed"))
        assert review.result.prepared is not None, review.result.issues
        warning = next(
            issue
            for issue in review.result.issues
            if issue.code
            == (
                "source.timezone_policy"
                if city in (0x29, 0xA4)
                else "source.timezone_fallback"
            )
        )
        assert warning.severity is IssueSeverity.WARNING
        if city in (0x29, 0xA4):
            assert (
                "can change the saved city during clock synchronization"
                in warning.message
            )
        elif city == 0:
            assert "when no city matches the live clock settings" in warning.detail
        assert device.save(review).active is not None
        saved = parse_iTunesDB(database.read_bytes())
        for slot in saved.find_chunks(MhitHeader):
            assert {
                name: getattr(slot.chunk.header, name) for name in date_words
            } == date_words
        assert preferences.read_bytes() == changed
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("family,release,model,size,version,profile", CLASSIC_TARGETS)
def test_live_calendar_identity_overrides_weaker_cached_version_and_family(
    tmp_path: Path,
    family: int,
    release: str,
    model: str,
    size: int,
    version: int,
    profile: PreferencesProfile,
) -> None:
    root = _ipod_volume(tmp_path / "ipod", model_number=model)
    metadata = root / "iPod_Control/Device"
    sysinfo = metadata / "SysInfo"
    sysinfo.write_text(
        sysinfo.read_text(encoding="utf-8")
        + "visibleBuildID: 1.62\nUpdaterFamilyID: 999\n",
        encoding="utf-8",
    )
    (metadata / "Preferences").write_bytes(classic_preferences(size, version, 0x10029))
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root,
        probe_result=HardwareProbeResult(
            observations=(
                HardwareProbeObservation(
                    source="windows_scsi",
                    vendor="Apple",
                    product="iPod",
                    firmware_revision="1.62",
                    vendor_payload=plistlib.dumps(
                        {
                            "ModelNumStr": model,
                            "VisibleBuildID": release,
                            "UpdaterFamilyID": family,
                        }
                    ),
                ),
            )
        ),
    )
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id, reconcile_metadata=False
        )
        values = {row.key: row.value for row in active.preferences[0].rows}
        assert values["timezone"] == "Unknown (city 65577)"
        assert values["clock_bias_seconds"] == "4294967295"
    finally:
        coordinator.close()
