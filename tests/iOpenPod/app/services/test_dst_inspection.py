"""Optional firmware DST evidence cannot gate Library loading or saving."""

import struct
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
    _RecordingStorage,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iPodDB.sidecars.test_sidecar_readers import counts

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.models.ipod_preferences import PreferenceFileStatus
from iOpenPod.app.services.device_coordinator import (
    DeviceAccessError,
    DeviceCoordinator,
)
from iOpenPod.app.services.ipod_preferences import capture_ipod_preferences
from iPodDB.preferences import DSTTableProfile
from storage import AccessMode, DevicePath, FileSnapshot, FilesystemSession, Storage
from storage.testing import VirtualStoragePlatform


def _preferences(city: int = 41) -> bytes:
    data = bytearray(2956)
    struct.pack_into("<I", data, 0, 0x3D)
    struct.pack_into("<I", data, 0xB70, city)
    return bytes(data)


def _rules() -> bytes:
    return b"".join(
        struct.pack("<HBBB3sHHHH", city, 1, 0, 0, b"\x11\x22\x33", 3, 2, 11, 1)
        for city in range(1, 206)
    )


@pytest.mark.parametrize("city,matches", ((41, "1"), (0x10029, "0")))
def test_capture_preserves_saved_rules_without_changing_library_date_policy(
    tmp_path: Path, city: int, matches: str
) -> None:
    root = _ipod_volume(tmp_path / "ipod", model_number="MB565")
    metadata = root / "iPod_Control/Device"
    (metadata / "Preferences").write_bytes(_preferences(city))
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = _RecordingStorage(platform)
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert profile is not None
    with storage.open_session(storage.discover().volumes[0]) as session:
        before = capture_ipod_preferences(
            session, profile, firmware_versions=("2.0.1",)
        )
        assert len(before.sections) == 2 and before.daylight_saving_rules is None
        (metadata / "dst").write_bytes(_rules())
        after = capture_ipod_preferences(session, profile, firmware_versions=("2.0.1",))
    assert before.device_time == after.device_time
    assert after.daylight_saving_rules is not None
    assert after.daylight_saving_rules.profile is DSTTableProfile.CLASSIC_120GB_2_0_1
    assert after.daylight_saving_rules.serialize() == (metadata / "dst").read_bytes()
    section = after.sections[2]
    assert section.key == "dst" and section.status is PreferenceFileStatus.AVAILABLE
    rows = {row.key: row.value for row in section.rows}
    assert rows == {"rule_count": "205 / 205", "city_rule_count": matches}
    assert "historical timezones" in section.detail
    assert set(storage.access_modes) == {AccessMode.READ_ONLY}


@pytest.mark.parametrize("versions", ((), ("2.0.4",), ("2.0.1", "2.0.5")))
def test_file_length_cannot_qualify_an_unknown_firmware(
    tmp_path: Path, versions: tuple[str, ...]
) -> None:
    root = _ipod_volume(tmp_path / "ipod", model_number="MB565")
    metadata = root / "iPod_Control/Device"
    (metadata / "Preferences").write_bytes(_preferences())
    (metadata / "dst").write_bytes(_rules())
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert profile is not None
    with storage.open_session(storage.discover().volumes[0]) as session:
        captured = capture_ipod_preferences(
            session, profile, firmware_versions=versions
        )
    assert captured.daylight_saving_rules is not None
    assert captured.daylight_saving_rules.profile is DSTTableProfile.UNKNOWN
    assert captured.daylight_saving_rules.rules == ()
    assert captured.daylight_saving_rules.serialize() == _rules()
    assert captured.sections[2].status is PreferenceFileStatus.UNKNOWN


@pytest.mark.parametrize(
    "dst",
    (b"", b"partial", _rules()[:-1], bytes(1024 * 1024 + 1)),
    ids=("empty", "partial-row", "short-table", "oversized"),
)
def test_bad_optional_rules_do_not_block_playback_commit_or_later_library_save(
    tmp_path: Path, dst: bytes
) -> None:
    device = build_device(tmp_path, model="MB565")
    try:
        metadata = device.root / "iPod_Control/Device"
        sysinfo = metadata / "SysInfo"
        sysinfo.write_text(
            sysinfo.read_text(encoding="utf-8") + "visibleBuildID: 2.0.1\n",
            encoding="utf-8",
        )
        (metadata / "Preferences").write_bytes(_preferences())
        (metadata / "dst").write_bytes(dst)
        sidecar = device.root / "iPod_Control/iTunes/Play Counts"
        # New York's skipped 2026-03-08 02:30, independent authored Mac calendar word.
        sidecar.write_bytes(counts(((2, 3855781800, 0, 0xFFFFFFFF, 0, 0, 0),)))
        active = device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id,
            reconcile_metadata=False,
        )
        assert active.library.tracks[0].play_count == 2
        assert not sidecar.exists()
        assert (metadata / "dst").read_bytes() == dst
        assert active.preferences[-1].status in (
            PreferenceFileStatus.UNKNOWN,
            PreferenceFileStatus.UNREADABLE,
        )
        review = device.prepare(
            replace(active.library, device_name="Calendar uncertainty is optional")
        )
        assert review.result.prepared is not None, review.result.issues
        # A changed optional calendar file is not a transaction precondition.
        (metadata / "dst").write_bytes(b"changed after preparation")
        result = device.save(review)
        assert result.active is not None
        assert result.active.library.device_name == "Calendar uncertainty is optional"
        assert (metadata / "dst").read_bytes() == b"changed after preparation"
    finally:
        device.coordinator.close()


def test_disconnect_while_reading_dst_still_invalidates_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ipod_volume(tmp_path / "ipod", model_number="MB565")
    (root / "iPod_Control/Device/dst").write_bytes(_rules())
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    original = FilesystemSession.read_snapshot

    def disconnect(
        self: FilesystemSession, path: DevicePath, *, max_bytes: int
    ) -> FileSnapshot:
        if path.name == "dst":
            platform.disconnect(root)
        return original(self, path, max_bytes=max_bytes)

    monkeypatch.setattr(FilesystemSession, "read_snapshot", disconnect)
    try:
        with pytest.raises(DeviceAccessError):
            coordinator.select_device(candidate.id, reconcile_metadata=False)
        assert coordinator.active_ipod is None
    finally:
        coordinator.close()
