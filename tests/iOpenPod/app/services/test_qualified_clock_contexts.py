"""Model-specific clock evidence affects conversion, never retained bytes."""

import struct
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
)

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.services.device_time import resolve_device_time
from iOpenPod.app.services.ipod_preferences import (
    CapturedIPodPreferences,
    capture_ipod_preferences,
)
from iPodDB.device_time import DeviceTimeSource, mac_to_unix, unix_to_mac
from iPodDB.preferences import PreferencesProfile, parse_preferences, write_preferences
from storage import Storage
from storage.testing import VirtualStoragePlatform

EPOCH = 2082844800
WINTER = 1704085200
SUMMER = 1719806400


@pytest.mark.parametrize(
    "profile", (PreferencesProfile.MINI_1_1_4_1, PreferencesProfile.MINI_2_1_4_1)
)
@pytest.mark.parametrize("selector", range(1, 51))
def test_mini_effective_offset_reads_and_writes_without_adding_dst_twice(
    profile: PreferencesProfile, selector: int
) -> None:
    data = bytearray(2876)
    struct.pack_into("<I", data, 0, 0x16)
    struct.pack_into("<I", data, 0xB10, selector)
    document = parse_preferences(bytes(data), profile=profile)
    context = resolve_device_time(document).for_database(19800)
    assert context.source is DeviceTimeSource.PREFERENCES_OFFSET
    pair, dst = divmod(selector - 1, 2)
    offset = (pair - 12 + dst) * 3600
    for instant in (WINTER, SUMMER):
        expected = instant + EPOCH + offset
        assert unix_to_mac(instant, context) == expected
        assert mac_to_unix(expected, context) == instant
    assert write_preferences(document) == data


CLASSICS = (
    (PreferencesProfile.CLASSIC_6_1_1_2, 2952, 0x3C),
    (PreferencesProfile.CLASSIC_120GB_2_0_1, 2956, 0x3D),
    (PreferencesProfile.CLASSIC_UPDATER_35_2_0_4, 2956, 0x3E),
    (PreferencesProfile.CLASSIC_UPDATER_38_2_0_5, 2960, 0x3F),
)


@pytest.mark.parametrize("profile,size,version", CLASSICS)
@pytest.mark.parametrize("dst", (0, 1, 60, 255))
def test_each_classic_uses_city_rules_without_reapplying_bias(
    profile: PreferencesProfile, size: int, version: int, dst: int
) -> None:
    data = bytearray(size)
    struct.pack_into("<I", data, 0, version)
    struct.pack_into("<I", data, 0xB70, 41)  # New York.
    data[0xB6C] = dst
    struct.pack_into("<iI", data, 0xB78, -2, 12345)
    document = parse_preferences(bytes(data), profile=profile)
    context = resolve_device_time(document).for_database(19800)
    assert context.source is DeviceTimeSource.PREFERENCES_CITY
    for instant, offset in ((WINTER, -18000), (SUMMER, -14400)):
        assert unix_to_mac(instant, context) == instant + EPOCH + offset
        assert mac_to_unix(instant + EPOCH + offset, context) == instant
    assert write_preferences(document) == data


@pytest.mark.parametrize(
    "profile,size,version",
    (
        *CLASSICS,
        (PreferencesProfile.MINI_1_1_4_1, 2876, 0x16),
        (PreferencesProfile.MINI_2_1_4_1, 2876, 0x16),
    ),
)
def test_reset_requested_clock_values_use_nonblocking_fallback(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    data = bytearray(size)
    struct.pack_into("<II", data, 0, version, 1)
    struct.pack_into("<I", data, 0xB10 if size == 2876 else 0xB70, 41)
    document = parse_preferences(bytes(data), profile=profile)
    context = resolve_device_time(document)
    assert context.source is DeviceTimeSource.UNRESOLVED
    assert "reset" in context.detail
    for offset in (-18000, 86400):
        fallback = context.for_database(offset)
        expected = WINTER + EPOCH + (offset if offset == -18000 else 0)
        assert unix_to_mac(WINTER, fallback) == expected
        assert mac_to_unix(expected, fallback) == WINTER
    assert write_preferences(document) == data


@pytest.mark.parametrize(
    "profile,size,version",
    (
        (PreferencesProfile.NANO_1_1_3_1, 2916, 0x37),
        (PreferencesProfile.NANO_3_1_1_3, 2952, 0x3C),
        (PreferencesProfile.NANO_4_1_0_4, 2960, 0x3E),
        (PreferencesProfile.VIDEO_1_3, 2924, 0x39),
    ),
)
def test_unqualified_clock_fields_do_not_borrow_another_models_city(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    data = bytearray(size)
    struct.pack_into("<I", data, 0, version)
    struct.pack_into("<H", data, 0xB22, 480)
    if size >= 0xB74:
        struct.pack_into("<I", data, 0xB70, 41)
    document = parse_preferences(bytes(data), profile=profile)
    context = resolve_device_time(document)
    assert context.source is DeviceTimeSource.UNRESOLVED
    context = context.for_database(20700)
    assert unix_to_mac(WINTER, context) == WINTER + EPOCH + 20700
    assert write_preferences(document) == data


def _capture_saved_city(
    tmp_path: Path,
    *,
    model: str,
    size: int,
    version: int,
    city: int,
    firmware_versions: tuple[str, ...],
    updater_family_ids: tuple[int, ...],
) -> CapturedIPodPreferences:
    root = _ipod_volume(tmp_path / "ipod", model_number=model)
    raw = bytearray(size)
    struct.pack_into("<I", raw, 0, version)
    struct.pack_into("<I", raw, 0xB70, city)
    path = root / "iPod_Control/Device/Preferences"
    path.write_bytes(raw)
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number(model)
    assert profile is not None
    with storage.open_session(storage.discover().volumes[0]) as session:
        captured = capture_ipod_preferences(
            session,
            profile,
            firmware_versions=firmware_versions,
            updater_family_ids=updater_family_ids,
        )
        assert session.is_active
    assert captured.device_bytes == bytes(raw)
    assert captured.time_precondition is not None
    assert path.read_bytes() == raw
    return captured


def _assert_nonblocking_clock_fallback(captured: CapturedIPodPreferences) -> None:
    assert captured.device_time.source is DeviceTimeSource.UNRESOLVED
    assert captured.device_time.zone is None
    assert captured.device_time.timezone_name is None
    assert captured.device_time.detail
    # 2024-01-01 midnight in the native calendar. Header evidence is independent
    # of the rejected saved city; an invalid header instead gives a UTC estimate.
    for header, instant, source in (
        (-18000, 1704085200, DeviceTimeSource.DATABASE_HEADER),
        (86400, 1704067200, DeviceTimeSource.UNRESOLVED),
    ):
        context = captured.device_time.for_database(header)
        assert context.source is source
        assert mac_to_unix(3786912000, context) == instant
        assert unix_to_mac(instant, context) == 3786912000


@pytest.mark.parametrize(
    "versions,families",
    (
        (("1.1.3",), (26,)),
        ((), ()),
        ((), (26,)),
        (("1.1.3",), (31,)),
        (("1.1.3", "1.1.1"), (26,)),
        (("1.1.3",), (26, 31)),
        (("1.1.3",), ()),
    ),
    ids=(
        "qualified-clock-still-unknown",
        "missing-identity",
        "missing-release",
        "wrong-updater",
        "conflicting-releases",
        "conflicting-updaters",
        "qualified-without-optional-updater",
    ),
)
def test_nano3_capture_never_promotes_latest_unknown_clock_through_legacy_decode(
    tmp_path: Path, versions: tuple[str, ...], families: tuple[int, ...]
) -> None:
    captured = _capture_saved_city(
        tmp_path,
        model="MA978",
        size=2952,
        version=0x3C,
        city=41,
        firmware_versions=versions,
        updater_family_ids=families,
    )
    _assert_nonblocking_clock_fallback(captured)


@pytest.mark.parametrize(
    "model,family,release,size,version",
    (
        ("MB029", 24, "1.1.2", 2952, 0x3C),
        ("MB565", 33, "2.0.1", 2956, 0x3D),
        ("MC293", 35, "2.0.4", 2956, 0x3E),
        ("MC293", 38, "2.0.5", 2960, 0x3F),
    ),
)
@pytest.mark.parametrize(
    "identity",
    (
        "qualified",
        "missing",
        "missing-release",
        "wrong-updater",
        "conflicting-releases",
        "conflicting-updaters",
    ),
)
def test_classic_capture_never_aliases_full_city_after_failed_qualification(
    tmp_path: Path,
    model: str,
    family: int,
    release: str,
    size: int,
    version: int,
    identity: str,
) -> None:
    versions, families = {
        "qualified": ((release,), (family,)),
        "missing": ((), ()),
        "missing-release": ((), (family,)),
        "wrong-updater": ((release,), (31,)),
        "conflicting-releases": ((release, "9.9.9"), (family,)),
        "conflicting-updaters": ((release,), (family, 31)),
    }[identity]
    captured = _capture_saved_city(
        tmp_path,
        model=model,
        size=size,
        version=version,
        # This unknown full-width ID must never alias its New York low halfword,
        # even when firmware identity cannot select the exact modern decoder.
        city=0x10029,
        firmware_versions=versions,
        updater_family_ids=families,
    )
    _assert_nonblocking_clock_fallback(captured)
