"""Qualified preference publication, preservation and revision ownership."""

import plistlib
import struct
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
)

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.models.ipod_preferences import (
    IPodPreference,
    IPodPreferenceEdit,
    IPodPreferencesCatalog,
    PreferenceFileStatus,
)
from iOpenPod.app.services.device_coordinator import (
    DeviceAccessError,
    DeviceChangedError,
    DeviceCoordinator,
)
from iPodDB.iTunesDB.cdb import compress_iTunesCDB
from iPodDB.preferences import NamedPreferencesDocument, PreferencesDocument
from storage import FilePreconditionError, Storage
from storage.testing import VirtualStoragePlatform

pytestmark = pytest.mark.usefixtures("enable_ipod_preferences_writes")


def _preferences() -> bytes:
    source = bytearray((index * 37 + 11) % 256 for index in range(2956))
    struct.pack_into("<I", source, 0, 0x3D)
    source[4:8] = bytes(4)  # Native reset request must be clear for editable payload.
    source[0xB16] = 0
    return bytes(source)


def build_preferences_device(
    tmp_path: Path,
    *,
    version: str = "2.0.1",
    source: bytes | None = None,
    model_number: str = "MB565",
    updater_family: int = 33,
) -> tuple[Path, DeviceCoordinator]:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number(model_number)
    assert profile is not None
    database_name = (
        "iTunesCDB"
        if profile.capabilities.database.uses_sqlite_database
        else "iTunesDB"
    )
    root = _ipod_volume(
        tmp_path / "device", model_number=model_number, database_name=database_name
    )
    if database_name == "iTunesCDB":
        database = root / "iPod_Control/iTunes/iTunesCDB"
        database.write_bytes(compress_iTunesCDB(database.read_bytes()))
    device = root / "iPod_Control/Device"
    (device / "SysInfoExtended").write_bytes(
        plistlib.dumps({"VisibleBuildID": version, "UpdaterFamilyID": updater_family})
    )
    path = device / "Preferences"
    path.write_bytes(_preferences() if source is None else source)
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    return path, coordinator


EDIT = (IPodPreferenceEdit("device", "sound_check", 1),)


def _rows(
    catalog: IPodPreferencesCatalog, section_key: str = "device"
) -> dict[str, IPodPreference]:
    return {
        row.key: row
        for section in catalog.sections
        if section.key == section_key
        for row in section.rows
    }


TOUCH_SOURCE = (
    b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
    b'<iPodSettings version="1.0">\r\n'
    b"  <General><Brightness>40</Brightness><Date>invalid DST date</Date></General>\r\n"
    b"  <Playback><SoundCheck>0</SoundCheck><Repeat>unqualified</Repeat></Playback>\r\n"
    b"  <!-- untouched --><Future><Unknown>opaque {missing}</Unknown></Future>\r\n"
    b"</iPodSettings>\r\n"
)


@pytest.mark.parametrize(
    "model,family,version",
    [
        ("MC027", 34, "1.0.2"),
        ("MC525", 36, "1.2"),
        ("MD480", 37, "1.0.4"),
        ("MKN22", 39, "1.1.2"),
    ],
)
def test_named_publication_edits_only_xml_and_ignores_optional_binary_clock(
    tmp_path: Path, model: str, family: int, version: str
) -> None:
    binary, coordinator = build_preferences_device(
        tmp_path,
        source=b"unknown clock blob",
        model_number=model,
        updater_family=family,
        version=version,
    )
    path = binary.with_name("iPodSettings.xml")
    path.write_bytes(TOUCH_SOURCE)
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        assert isinstance(catalog.document, NamedPreferencesDocument)
        rows = {
            row.key: row
            for section in catalog.sections
            if section.key == "device"
            for row in section.rows
        }
        assert set(rows) == {
            "brightness",
            "sound_check",
            "General.Date",
            "Playback.Repeat",
            "Future.Unknown",
        }
        assert {key for key, row in rows.items() if row.edit is not None} == {
            "brightness",
            "sound_check",
        }
        assert rows["brightness"].edit is not None
        assert rows["brightness"].edit.minimum == 0
        assert rows["brightness"].edit.maximum == 100
        assert rows["brightness"].raw_value == "40"
        assert rows["brightness"].detail
        assert rows["Future.Unknown"].value == "opaque {missing}"
        assert rows["Future.Unknown"].raw_value == "opaque {missing}"
        assert rows["General.Date"].raw_value == "invalid DST date"
        for key in ("Future.Unknown", "General.Date", "Playback.Repeat"):
            with pytest.raises(ValueError, match="not available for editing"):
                coordinator.save_preferences(
                    active, catalog, (IPodPreferenceEdit("device", key, 1),), Event()
                )
            assert path.read_bytes() == TOUCH_SOURCE
        # Preferences is optional clock evidence, not the artifact being edited.
        binary.write_bytes(b"changed invalid datetime state")
        result = coordinator.save_preferences(
            active,
            catalog,
            (*EDIT, IPodPreferenceEdit("device", "brightness", 73)),
            Event(),
        )
        expected = TOUCH_SOURCE.replace(b">40<", b">73<").replace(b">0<", b">1<")
        assert path.read_bytes() == expected
        assert binary.read_bytes() == b"changed invalid datetime state"
        assert result.document is not None and result.document.source_bytes == expected
        assert coordinator.active_ipod is active
    finally:
        coordinator.close()


@pytest.mark.parametrize("value", (0, 1))
def test_touch_source_precondition_checks_xml_for_edits_and_noops(
    tmp_path: Path, value: int
) -> None:
    binary, coordinator = build_preferences_device(
        tmp_path, model_number="MC525", updater_family=36, version="1.2"
    )
    path = binary.with_name("iPodSettings.xml")
    path.write_bytes(TOUCH_SOURCE)
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        changed = TOUCH_SOURCE.replace(b"opaque", b"external change")
        path.write_bytes(changed)
        with pytest.raises(FilePreconditionError):
            coordinator.save_preferences(
                active,
                catalog,
                (IPodPreferenceEdit("device", "sound_check", value),),
                Event(),
            )
        assert path.read_bytes() == changed
    finally:
        coordinator.close()


def test_missing_touch_store_is_not_created_from_legacy_preferences(
    tmp_path: Path,
) -> None:
    binary, coordinator = build_preferences_device(
        tmp_path, model_number="MD480", updater_family=37, version="1.0.4"
    )
    path = binary.with_name("iPodSettings.xml")
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        assert catalog.document is None
        assert not any(row.edit for section in catalog.sections for row in section.rows)
        with pytest.raises(ValueError, match="Reload verified"):
            coordinator.save_preferences(active, catalog, EDIT, Event())
        assert not path.exists()
        assert binary.read_bytes() == _preferences()
    finally:
        coordinator.close()


@pytest.mark.parametrize(
    "model,family,version,size,format_version",
    [("MA978", 26, "1.1.3", 2952, 0x3C), ("MB598", 31, "1.0.4", 2960, 0x3E)],
)
def test_clickwheel_nano_settings_use_qualified_map_without_classic_clock(
    tmp_path: Path,
    model: str,
    family: int,
    version: str,
    size: int,
    format_version: int,
) -> None:
    original = bytearray((i * 37 + 11) % 256 for i in range(size))
    struct.pack_into("<II", original, 0, format_version, 0)
    struct.pack_into("<I", original, 0xB70, 0x21)  # Must not alias a Classic city.
    original[0x18] = original[0x8A] = 0
    original[0xB3B] = 0xFE
    original[0xB49] = 26 if family == 31 else 14
    path, coordinator = build_preferences_device(
        tmp_path,
        model_number=model,
        updater_family=family,
        version=version,
        source=bytes(original),
    )
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        rows = {
            row.key: row
            for section in catalog.sections
            if section.key == "device"
            for row in section.rows
        }
        assert rows["timezone"].value == "Unknown"
        assert {key for key, row in rows.items() if row.edit} == {
            "shuffle_mode",
            "repeat_mode",
            "sound_check",
            "eq_preset",
            "brightness",
            "clicker",
            "backlight_timeout",
            "contact_sort",
            "photo_shuffle",
            "photo_repeat",
            "photo_duration",
            "photo_transition",
            "tv_out",
            "tv_signal",
            "tv_screen",
            "fit_to_screen_disabled",
            "alternate_audio",
        }
        transition = rows["photo_transition"]
        assert transition.edit is not None
        assert transition.raw_value == (
            "Mode 0xFE, effect 0x1A" if family == 31 else "Mode 0xFE, effect 0x0E"
        )
        assert transition.detail and transition.category
        choices = {choice.value: choice.label for choice in transition.edit.choices}
        assert choices == (
            {
                25: "None",
                -1: "Random",
                26: "Dissolve",
                27: "Slide",
                6: "Push",
                5: "Fade Through Black",
                21: "Zoom",
            }
            if family == 31
            else {
                0: "None",
                -1: "Random",
                14: "Cross Fade",
                5: "Fade To Black",
                24: "Zoom Out",
                1: "Wipe Across",
                3: "Wipe Center",
            }
        )
        fit = rows["fit_to_screen_disabled"].edit
        assert fit is not None
        assert {choice.value: choice.label for choice in fit.choices} == {
            0: "On",
            1: "Off",
        }
        coordinator.save_preferences(
            active,
            catalog,
            tuple(
                IPodPreferenceEdit("device", key, value)
                for key, value in (
                    ("shuffle_mode", 2),
                    ("repeat_mode", 2),
                    ("sound_check", 1),
                    ("eq_preset", 109),
                    ("brightness", 0),
                    ("photo_transition", -1),
                    ("fit_to_screen_disabled", 0),
                )
            ),
            Event(),
        )
        expected = bytearray(original)
        expected[0x18] = expected[0x8A] = expected[0xB16] = 1
        struct.pack_into("<I", expected, 0x14, 2)
        struct.pack_into("<H", expected, 0xB60, 109)
        expected[0xB54] = 0
        expected[0xB3B] = 0xFF
        expected[0xB49] = 28 if family == 31 else 25
        expected[0xB4D] = 0
        assert path.read_bytes() == expected
    finally:
        coordinator.close()


@pytest.mark.parametrize(
    ("model", "family", "version", "size", "format_version", "speaker_value"),
    [
        ("M9160", 3, "1.4.1", 2876, 0x16, 1),
        ("M9434", 6, "1.4.1", 2876, 0x16, 1),
        ("M9800", 7, "1.4.1", 2876, 0x16, 1),
        ("MA004", 14, "1.3.1", 2916, 0x37, 1),
        ("MA352", 17, "1.3.1", 2916, 0x37, 1),
        ("MA002", 13, "1.3", 2924, 0x39, 2),
        ("MA146", 20, "1.3", 2924, 0x39, 2),
        ("MA450", 25, "1.3", 2924, 0x39, 2),
    ],
)
def test_legacy_clicker_routes_use_their_own_firmware_labels_and_preserve_bits(
    tmp_path: Path,
    model: str,
    family: int,
    version: str,
    size: int,
    format_version: int,
    speaker_value: int,
) -> None:
    original = bytearray(size)
    struct.pack_into("<I", original, 0, format_version)
    struct.pack_into("<I", original, 0xAF8, 0x12340000)
    struct.pack_into("<I", original, 0xAFC, 0xA5A50000)
    path, coordinator = build_preferences_device(
        tmp_path,
        source=bytes(original),
        version=version,
        model_number=model,
        updater_family=family,
    )
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        rows = {
            row.key: row
            for section in catalog.sections
            if section.key == "device"
            for row in section.rows
        }
        assert rows["language"].value == "Unknown (305397760)"
        assert rows["language"].raw_value == "305397760 (0x12340000)"
        assert rows["language"].edit is None
        assert rows["clicker"].raw_value == "2779054080 (0xA5A50000)"
        assert rows["clicker"].category and rows["clicker"].detail
        clicker = rows["clicker"].edit
        assert clicker is not None
        choices = {choice.value: choice.label for choice in clicker.choices}
        assert choices[speaker_value] == "Speaker"
        assert choices[3 - speaker_value] == "Headphones"
        coordinator.save_preferences(
            active,
            catalog,
            (IPodPreferenceEdit("device", "clicker", speaker_value),),
            Event(),
        )
        expected = bytearray(original)
        struct.pack_into("<I", expected, 0xAFC, 0xA5A50000 | speaker_value)
        assert path.read_bytes() == expected
    finally:
        coordinator.close()


def test_verified_save_changes_only_requested_byte_and_keeps_unknown_clock(
    tmp_path: Path,
) -> None:
    path, coordinator = build_preferences_device(tmp_path)
    try:
        active = coordinator.active_ipod
        assert active is not None
        before = path.read_bytes()
        catalog = coordinator.load_preferences(active, Event())
        assert path.read_bytes() == before
        updated = coordinator.save_preferences(active, catalog, EDIT, Event())
        expected = bytearray(before)
        expected[0xB16] = 1
        assert path.read_bytes() == expected
        assert updated.document is not None
        assert updated.document.source_bytes == expected
        assert coordinator.active_ipod is active
        with pytest.raises(DeviceChangedError, match="Reload"):
            coordinator.save_preferences(active, catalog, EDIT, Event())
    finally:
        coordinator.close()


@pytest.mark.parametrize("source", [b"unrecognized", b"", bytes(2956)])
def test_unrecognized_framing_remains_readonly_without_blocking_library(
    tmp_path: Path, source: bytes
) -> None:
    path, coordinator = build_preferences_device(tmp_path, source=source)
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        assert catalog.document is None
        assert not any(row.edit for section in catalog.sections for row in section.rows)
        with pytest.raises(ValueError, match="Reload verified"):
            coordinator.save_preferences(active, catalog, EDIT, Event())
        assert path.read_bytes() == source
        assert coordinator.active_ipod is active
    finally:
        coordinator.close()


def test_unqualified_firmware_does_not_authorize_writes(tmp_path: Path) -> None:
    path, coordinator = build_preferences_device(tmp_path, version="2.0")
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        assert catalog.document is None
        with pytest.raises(ValueError, match="Reload verified"):
            coordinator.save_preferences(active, catalog, EDIT, Event())
        assert path.read_bytes() == _preferences()
    finally:
        coordinator.close()


def test_pending_native_reset_retains_bytes_but_does_not_offer_edits(
    tmp_path: Path,
) -> None:
    source = bytearray(_preferences())
    source[4] = 1
    path, coordinator = build_preferences_device(tmp_path, source=bytes(source))
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        assert catalog.document is not None
        assert not any(row.edit for section in catalog.sections for row in section.rows)
        assert "request a reset" in catalog.sections[0].detail
        with pytest.raises(ValueError, match="not available"):
            coordinator.save_preferences(active, catalog, EDIT, Event())
        assert path.read_bytes() == source
    finally:
        coordinator.close()


@pytest.mark.parametrize("value", [0, 1])
def test_external_changes_reject_both_edits_and_stale_noops(
    tmp_path: Path, value: int
) -> None:
    path, coordinator = build_preferences_device(tmp_path)
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        external = bytearray(path.read_bytes())
        external[0x42] ^= 0xFF
        path.write_bytes(external)
        with pytest.raises(FilePreconditionError):
            coordinator.save_preferences(
                active,
                catalog,
                (IPodPreferenceEdit("device", "sound_check", value),),
                Event(),
            )
        assert path.read_bytes() == external
    finally:
        coordinator.close()


@pytest.mark.parametrize(
    "changes",
    [
        (IPodPreferenceEdit("itunes", "sound_check", 1),),
        (IPodPreferenceEdit("device", "clock_bias_seconds", 0),),
        (IPodPreferenceEdit("device", "sound_check", 2),),
        EDIT + EDIT,
    ],
)
def test_invalid_or_unqualified_edits_cannot_mutate_bytes(
    tmp_path: Path, changes: tuple[IPodPreferenceEdit, ...]
) -> None:
    path, coordinator = build_preferences_device(tmp_path)
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        with pytest.raises(ValueError):
            coordinator.save_preferences(active, catalog, changes, Event())
        assert path.read_bytes() == _preferences()
    finally:
        coordinator.close()


def test_catalog_and_metadata_are_independent_publication_preconditions(
    tmp_path: Path,
) -> None:
    path, coordinator = build_preferences_device(tmp_path)
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        with pytest.raises(DeviceChangedError):
            coordinator.save_preferences(active, replace(catalog), EDIT, Event())
        (path.parent / "SysInfoExtended").write_bytes(
            plistlib.dumps({"VisibleBuildID": "2.0", "UpdaterFamilyID": 33})
        )
        with pytest.raises(DeviceChangedError, match="firmware"):
            coordinator.save_preferences(active, catalog, EDIT, Event())
        refreshed = coordinator.load_preferences(active, Event())
        assert refreshed.document is None
        assert path.read_bytes() == _preferences()
    finally:
        coordinator.close()


def test_cancelled_preferences_work_does_not_write(tmp_path: Path) -> None:
    path, coordinator = build_preferences_device(tmp_path)
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        cancelled = Event()
        cancelled.set()
        with pytest.raises(DeviceAccessError, match="cancelled"):
            coordinator.save_preferences(active, catalog, EDIT, cancelled)
        assert path.read_bytes() == _preferences()
    finally:
        coordinator.close()


@pytest.mark.parametrize(
    "model,family,version,size,format_version",
    [
        ("M9160", 3, "1.4.1", 2876, 0x16),
        ("M9800", 7, "1.4.1", 2876, 0x16),
        ("MA004", 14, "1.3.1", 2916, 0x37),
        ("MA002", 13, "1.3", 2924, 0x39),
        ("MA978", 26, "1.1.3", 2952, 0x3C),
        ("MB598", 31, "1.0.4", 2960, 0x3E),
        ("MB029", 24, "1.1.2", 2952, 0x3C),
        ("MB565", 33, "2.0.1", 2956, 0x3D),
        ("MC293", 35, "2.0.4", 2956, 0x3E),
        ("MC297", 38, "2.0.5", 2960, 0x3F),
    ],
)
def test_backlight_and_audiobook_choices_use_model_specific_native_units(
    tmp_path: Path,
    model: str,
    family: int,
    version: str,
    size: int,
    format_version: int,
) -> None:
    original = bytearray(size)
    struct.pack_into("<II", original, 0, format_version, 0)
    struct.pack_into("<I", original, 0xAF0, 5)
    original[0xB38] = 0xFF
    path, coordinator = build_preferences_device(
        tmp_path,
        source=bytes(original),
        model_number=model,
        updater_family=family,
        version=version,
    )
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        rows = _rows(catalog)
        backlight = rows["backlight_timeout"]
        assert backlight.edit is not None
        choices = {choice.value: choice.label for choice in backlight.edit.choices}
        if family in (3, 7):
            assert choices == {
                0: "Off",
                2: "2 seconds",
                3: "5 seconds",
                4: "10 seconds",
                5: "20 seconds",
                6: "Always on",
            }
        elif family in (13, 14):
            assert choices == {
                0: "Off",
                2: "2 seconds",
                3: "5 seconds",
                4: "10 seconds",
                5: "15 seconds",
                6: "20 seconds",
                8: "Always on",
            }
        else:
            assert choices == {
                0: "Off",
                1: "2 seconds",
                2: "5 seconds",
                3: "10 seconds",
                4: "20 seconds",
                5: "30 seconds",
                6: "Always on",
            }
        assert backlight.value == choices[5]
        assert backlight.raw_value == "5 (0x00000005)"
        assert backlight.detail and backlight.category
        if family in (3, 7, 13, 14):
            speed = rows["audiobook_speed"]
            assert speed.value == "Slower"
            assert speed.raw_value == "-1 (0xFF)"
            assert speed.edit is not None
            assert {choice.value: choice.label for choice in speed.edit.choices} == {
                -1: "Slower",
                0: "Normal",
                1: "Faster",
            }
        else:
            assert "audiobook_speed" not in {
                key for key, row in rows.items() if row.edit is not None
            }
        assert path.read_bytes() == original
    finally:
        coordinator.close()


def test_nano4_extensionless_secondary_store_is_readonly_and_independent(
    tmp_path: Path,
) -> None:
    original = bytearray(2960)
    struct.pack_into("<I", original, 0, 0x3E)
    path, coordinator = build_preferences_device(
        tmp_path,
        source=bytes(original),
        model_number="MB598",
        updater_family=31,
        version="1.0.4",
    )
    named = path.with_name("iPodSettings")
    named_source = (
        b'<iPodSettings version="1.0"><Settings><FontSize>1</FontSize>'
        b"<VoiceFeedback>1</VoiceFeedback></Settings>"
        b"<Future><Unknown>do not change</Unknown></Future></iPodSettings>"
    )
    named.write_bytes(named_source)
    misleading_xml = path.with_name("iPodSettings.xml")
    misleading_xml.write_bytes(TOUCH_SOURCE)
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        assert isinstance(catalog.document, PreferencesDocument)
        secondary = next(s for s in catalog.sections if s.key == "named")
        assert secondary.status is PreferenceFileStatus.AVAILABLE
        rows = _rows(catalog, "named")
        assert set(rows) == {
            "Settings.FontSize",
            "Settings.VoiceFeedback",
            "Future.Unknown",
        }
        assert rows["Settings.FontSize"].value == "Large"
        assert rows["Settings.VoiceFeedback"].value == "On"
        assert rows["Future.Unknown"].raw_value == "do not change"
        assert all(row.edit is None for row in secondary.rows)
        with pytest.raises(ValueError, match="not available for editing"):
            coordinator.save_preferences(
                active,
                catalog,
                (IPodPreferenceEdit("named", "Settings.VoiceFeedback", 0),),
                Event(),
            )
        coordinator.save_preferences(active, catalog, EDIT, Event())
        expected = bytearray(original)
        expected[0xB16] = 1
        assert path.read_bytes() == expected
        assert named.read_bytes() == named_source
        assert misleading_xml.read_bytes() == TOUCH_SOURCE
    finally:
        coordinator.close()


@pytest.mark.parametrize(
    "model,family,version",
    [
        ("MC027", 34, "1.0.2"),
        ("MC525", 36, "1.2"),
        ("MD480", 37, "1.0.4"),
        ("MKN22", 39, "1.1.2"),
    ],
)
@pytest.mark.parametrize("binary_present", (False, True))
def test_named_eq_edits_do_not_require_or_author_legacy_binary_preferences(
    tmp_path: Path, model: str, family: int, version: str, binary_present: bool
) -> None:
    raw = bytearray(2960)
    struct.pack_into("<I", raw, 0, 0x3E)
    struct.pack_into("<I", raw, 8, 0xFFFFFFFF)
    binary, coordinator = build_preferences_device(
        tmp_path,
        source=bytes(raw),
        model_number=model,
        updater_family=family,
        version=version,
    )
    if not binary_present:
        binary.unlink()
    path = binary.with_name("iPodSettings.xml")
    source = TOUCH_SOURCE.replace(b"<Playback>", b"<Playback><EQ>109</EQ>")
    path.write_bytes(source)
    try:
        active = coordinator.active_ipod
        assert active is not None
        catalog = coordinator.load_preferences(active, Event())
        assert isinstance(catalog.document, NamedPreferencesDocument)
        equalizer = _rows(catalog)["eq_preset"]
        assert equalizer.value == "Jazz"
        assert equalizer.raw_value == "109"
        assert equalizer.edit is not None
        assert len(equalizer.edit.choices) == 23
        legacy = _rows(catalog, "legacy_device")
        if binary_present:
            assert legacy["legacy.volume"].raw_value == "0xFFFFFFFF"
            assert all(row.edit is None for row in legacy.values())
            assert "timezone" not in legacy and "clock_bias_seconds" not in legacy
        else:
            assert not legacy
        coordinator.save_preferences(
            active, catalog, (IPodPreferenceEdit("device", "eq_preset", 110),), Event()
        )
        assert path.read_bytes() == source.replace(b"<EQ>109</EQ>", b"<EQ>110</EQ>")
        if binary_present:
            assert binary.read_bytes() == raw
        else:
            assert not binary.exists()
        assert coordinator.active_ipod is active
    finally:
        coordinator.close()


@pytest.mark.parametrize(
    "timer_source",
    (
        None,
        b"",
        b"<iPodSettings>{bad}",
        b'<iPodSettings version="1.0"><Timer><SleepiPod>1</SleepiPod></Timer></iPodSettings>',
    ),
)
def test_nano6_timer_file_is_ignored_during_preferences_edits(
    tmp_path: Path, timer_source: bytes | None
) -> None:
    binary, coordinator = build_preferences_device(
        tmp_path,
        source=b"optional clock",
        model_number="MC525",
        updater_family=36,
        version="1.2",
    )
    path = binary.with_name("iPodSettings.xml")
    path.write_bytes(TOUCH_SOURCE)
    timer = binary.with_name("iPodTimerSettings.xml")
    if timer_source is not None:
        timer.write_bytes(timer_source)
    try:
        active = coordinator.active_ipod
        assert active is not None and active.library.tracks
        catalog = coordinator.load_preferences(active, Event())
        assert all(section.key != "timer" for section in catalog.sections)
        coordinator.save_preferences(active, catalog, EDIT, Event())
        assert path.read_bytes() == TOUCH_SOURCE.replace(b">0<", b">1<")
        if timer_source is None:
            assert not timer.exists()
        else:
            assert timer.read_bytes() == timer_source
    finally:
        coordinator.close()
