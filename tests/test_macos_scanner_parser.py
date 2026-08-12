"""Unit tests for the macOS ioreg → (BSD disk, USB serial) parser.

These cover the bug that crashed device identification with
``ValueError: zip() argument 2 is longer than argument 1`` whenever the
Mac had any non-iPod Apple USB device on the bus (keyboard, AirPods
receiver, hub, iPhone).  The parser now extracts the iPod's own serial
inline from the text ioreg, so unrelated Apple devices never end up
paired with an iPod's BSD whole-disk name.
"""

from __future__ import annotations

import plistlib
import sys
from types import ModuleType

from iopenpod.device import info as device_info
from iopenpod.device import vpd_libusb
from iopenpod.device.diagnostic_log import format_fields
from iopenpod.device.scanner import _parse_macos_ioreg_bsd_serials

_SINGLE_IPOD = """\
+-o iPod@01130000  <class IOUSBHostDevice, ...>
  |   "USB Serial Number" = "000A270018A1F847"
  |   "idProduct" = 4704
  +-o IOUSBMassStorageDriver  <class IOUSBMassStorageDriver, ...>
    +-o IOUSBMassStorageInterfaceNub  <class IOSCSIPeripheralDeviceType00, ...>
      +-o Apple iPod Media  <class IOMedia, ...>
      |   "BSD Name" = "disk4"
"""


_SINGLE_IPOD_WITH_OTHER_APPLE_DEVICES = """\
+-o AppleUSBKeyboard@14100000  <class IOUSBHostDevice, ...>
  |   "USB Serial Number" = "KBD-ABCDEF"
  |   "idProduct" = 555
+-o iPod@01130000  <class IOUSBHostDevice, ...>
  |   "USB Serial Number" = "000A270018A1F847"
  |   "idProduct" = 4704
  +-o IOUSBMassStorageDriver  <class IOUSBMassStorageDriver, ...>
    +-o IOUSBMassStorageInterfaceNub  <class IOSCSIPeripheralDeviceType00, ...>
      +-o Apple iPod Media  <class IOMedia, ...>
      |   "BSD Name" = "disk4"
+-o AppleAirPodsReceiver@14200000  <class IOUSBHostDevice, ...>
  |   "USB Serial Number" = "AIRPODS-XYZ"
  |   "idProduct" = 999
"""


_TWO_IPODS_VIA_HUB = """\
+-o AppleUSBHub@14000000  <class IOUSBHostDevice, ...>
  |   "USB Serial Number" = "HUB-001"
  |   "idProduct" = 100
  +-o iPod@14100000  <class IOUSBHostDevice, ...>
  |   |   "USB Serial Number" = "AAA111"
  |   |   "idProduct" = 4704
  |   +-o IOUSBMassStorageDriver  <class IOUSBMassStorageDriver, ...>
  |     +-o IOUSBMassStorageInterfaceNub  <class IOSCSIPeripheralDeviceType00, ...>
  |       +-o Apple iPod Media  <class IOMedia, ...>
  |       |   "BSD Name" = "disk4"
  +-o iPod@14200000  <class IOUSBHostDevice, ...>
    |   "USB Serial Number" = "BBB222"
    |   "idProduct" = 4704
    +-o IOUSBMassStorageDriver  <class IOUSBMassStorageDriver, ...>
      +-o IOUSBMassStorageInterfaceNub  <class IOSCSIPeripheralDeviceType00, ...>
        +-o Apple iPod Media  <class IOMedia, ...>
        |   "BSD Name" = "disk6"
"""


def test_parser_pairs_single_ipod_with_its_serial() -> None:
    assert _parse_macos_ioreg_bsd_serials(_SINGLE_IPOD) == {
        "disk4": "000A270018A1F847",
    }


def test_parser_ignores_unrelated_apple_devices() -> None:
    """Regression for the ValueError("zip()...") crash from issue notes.

    With a keyboard and AirPods receiver on the bus, the previous
    implementation built two parallel lists and zipped them with
    strict=True — three Apple serials vs one iPod disk crashed.  The
    inline serial parse pairs only the iPod disk and drops the rest.
    """
    assert _parse_macos_ioreg_bsd_serials(
        _SINGLE_IPOD_WITH_OTHER_APPLE_DEVICES
    ) == {"disk4": "000A270018A1F847"}


def test_parser_pairs_two_ipods_behind_a_hub() -> None:
    """Each iPod's media disk pairs with its own serial, not the hub's."""
    assert _parse_macos_ioreg_bsd_serials(_TWO_IPODS_VIA_HUB) == {
        "disk4": "AAA111",
        "disk6": "BBB222",
    }


def test_parser_returns_empty_when_no_ipods_present() -> None:
    only_keyboard = """\
+-o AppleUSBKeyboard@14100000  <class IOUSBHostDevice, ...>
  |   "USB Serial Number" = "KBD-ABCDEF"
  |   "idProduct" = 555
"""
    assert _parse_macos_ioreg_bsd_serials(only_keyboard) == {}


def test_parser_normalises_serial_whitespace_and_case() -> None:
    """Serials with embedded spaces/lowercase are normalised the same way
    the plist collector does, so both maps can be cross-referenced.
    """
    sample = """\
+-o iPod@01130000  <class IOUSBHostDevice, ...>
  |   "USB Serial Number" = "a b c 123 def"
  +-o IOUSBMassStorageDriver  <class IOUSBMassStorageDriver, ...>
    +-o Apple iPod Media  <class IOMedia, ...>
    |   "BSD Name" = "disk2"
"""
    assert _parse_macos_ioreg_bsd_serials(sample) == {"disk2": "ABC123DEF"}


def test_macos_vpd_page_80_serial_is_accepted_for_model_lookup(monkeypatch) -> None:
    """Older iPods expose their Apple serial on standard VPD page 0x80."""

    iokit = ModuleType("iopenpod.device.vpd_iokit")
    monkeypatch.setattr(
        iokit,
        "query_ipod_vpd",
        lambda **_kwargs: {
            "vpd_serial": "8P840FNNNRH",
            "usb_pid": 0x1201,
        },
        raising=False,
    )
    monkeypatch.setattr(vpd_libusb.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "iopenpod.device.vpd_iokit", iokit)

    result = vpd_libusb.identify_via_vpd(
        mount_path="",
        usb_pid=0x1201,
        write_sysinfo_to_device=False,
    )

    assert result is not None
    assert result["serial"] == "8P840FNNNRH"
    assert result["model_number"] == "M8976"


def test_macos_vpd_preserves_unit_serial_without_using_it_as_product_serial(
    monkeypatch,
) -> None:
    """A storage LUN value remains diagnostic data, not product identity."""

    iokit = ModuleType("iopenpod.device.vpd_iokit")
    monkeypatch.setattr(
        iokit,
        "query_ipod_vpd",
        lambda **_kwargs: {
            "vpd_serial": "4",
            "usb_pid": 0x1201,
            "usb_serial": "0000002275EE",
        },
        raising=False,
    )
    usb_control = ModuleType("iopenpod.device.vpd_usb_control")
    monkeypatch.setattr(
        usb_control,
        "query_ipod_usb_sysinfo_extended",
        lambda **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(vpd_libusb.sys, "platform", "darwin")
    monkeypatch.setattr(vpd_libusb, "query_ipod_vpd", lambda **_kwargs: None)
    monkeypatch.setitem(sys.modules, "iopenpod.device.vpd_iokit", iokit)
    monkeypatch.setitem(sys.modules, "iopenpod.device.vpd_usb_control", usb_control)

    result = vpd_libusb.identify_via_vpd(
        mount_path="",
        usb_pid=0x1201,
        write_sysinfo_to_device=False,
    )

    assert result is not None
    assert result["serial"] == ""
    assert result["model_number"] == ""
    assert result["serial_rejected_reason"] == "invalid_apple_product_serial"
    assert result["vpd_info"]["vpd_serial"] == "4"
    assert "vpd_unit_serial=4" in format_fields(result["vpd_info"])
    assert "serial_rejected=invalid_apple_product_serial" in format_fields(result)


def test_vpd_rejects_bare_model_suffix_as_product_serial() -> None:
    assert vpd_libusb._apple_product_serial({"vpd_serial": "NRH"}) == ""


def test_vpd_serial_model_must_agree_with_usb_pid(monkeypatch) -> None:
    iokit = ModuleType("iopenpod.device.vpd_iokit")
    monkeypatch.setattr(
        iokit,
        "query_ipod_vpd",
        lambda **_kwargs: {
            "vpd_serial": "YM0350TRVQ5",
            "usb_pid": 0x1201,
        },
        raising=False,
    )
    usb_control = ModuleType("iopenpod.device.vpd_usb_control")
    monkeypatch.setattr(
        usb_control,
        "query_ipod_usb_sysinfo_extended",
        lambda **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(vpd_libusb.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "iopenpod.device.vpd_iokit", iokit)
    monkeypatch.setitem(sys.modules, "iopenpod.device.vpd_usb_control", usb_control)

    result = vpd_libusb.identify_via_vpd(
        mount_path="",
        usb_pid=0x1201,
        write_sysinfo_to_device=False,
    )

    assert result is not None
    assert result["serial"] == ""
    assert result["model_number"] == ""
    assert result["serial_rejected_reason"] == "usb_pid_conflict"
    assert result["vpd_info"]["vpd_serial"] == "YM0350TRVQ5"


def test_enrich_does_not_reapply_vpd_serial_that_conflicts_with_pid(
    monkeypatch,
    tmp_path,
) -> None:
    iokit = ModuleType("iopenpod.device.vpd_iokit")
    monkeypatch.setattr(
        iokit,
        "query_ipod_vpd",
        lambda **_kwargs: {
            "vpd_serial": "YM0350TRVQ5",
            "usb_pid": 0x1201,
        },
        raising=False,
    )
    usb_control = ModuleType("iopenpod.device.vpd_usb_control")
    monkeypatch.setattr(
        usb_control,
        "query_ipod_usb_sysinfo_extended",
        lambda **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(vpd_libusb.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "iopenpod.device.vpd_iokit", iokit)
    monkeypatch.setitem(sys.modules, "iopenpod.device.vpd_usb_control", usb_control)
    monkeypatch.setattr(device_info, "_enrich_from_hardware_probe", lambda _info: None)

    ipod = device_info.DeviceInfo(
        path=str(tmp_path),
        model_family="iPod",
        generation="3rd Gen",
        usb_pid=0x1201,
    )
    ipod._field_sources.update({
        "model_family": "usb_pid",
        "generation": "usb_pid",
        "usb_pid": "ioreg",
    })
    ipod._live_usb_pid = 0x1201

    device_info.enrich(ipod)

    assert ipod.serial == ""
    assert ipod.model_number == ""
    assert ipod.model_family == "iPod"
    assert ipod.generation == "3rd Gen"
    assert device_info.has_safe_device_profile(ipod)


def test_background_validation_does_not_reapply_rejected_vendor_serial(
    monkeypatch,
    tmp_path,
) -> None:
    raw_vpd = {
        "_source": "scsi_vpd",
        "SerialNumber": "YM0350TRVQ5",
        "vpd_serial": "4",
        "usb_pid": 0x1201,
        "vpd_raw_xml": plistlib.dumps({
            "SerialNumber": "YM0350TRVQ5",
            "FireWireGUID": "0000002275EE",
        }),
    }
    rejected_result = {
        "serial": "",
        "firewire_guid": "0000002275EE",
        "firmware": "1.53",
        "model_number": "",
        "model_family": "",
        "generation": "",
        "capacity": "",
        "color": "",
        "source": "scsi_vpd",
        "serial_rejected_reason": "usb_pid_conflict",
        "vpd_info": raw_vpd,
    }
    monkeypatch.setattr(vpd_libusb, "identify_via_vpd", lambda **_kwargs: rejected_result)
    monkeypatch.setattr(device_info.sys, "platform", "darwin")
    monkeypatch.setattr(device_info, "_apply_live_result_to_cache", lambda *_args: None)
    cached_payloads = []
    monkeypatch.setattr(
        device_info,
        "_cache_live_sysinfo_extended",
        lambda _path, payload, *_args: cached_payloads.append(payload),
    )

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(device_info.threading, "Thread", ImmediateThread)

    ipod = device_info.DeviceInfo(
        path=str(tmp_path),
        model_family="iPod",
        generation="3rd Gen",
        usb_pid=0x1201,
    )
    device_info._start_live_identity_validation(ipod)

    assert ipod.serial == ""
    assert ipod.raw_identity_evidence["vpd"][0]["SerialNumber"] == "YM0350TRVQ5"
    assert cached_payloads
    assert "SerialNumber" not in cached_payloads[0]
    assert "SerialNumber" not in plistlib.loads(
        cached_payloads[0]["vpd_raw_xml"]
    )


def test_vpd_cli_prints_raw_serial_but_writes_only_safe_identity(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    raw = {
        "_source": "scsi_vpd",
        "SerialNumber": "YM0350TRVQ5",
        "vpd_serial": "4",
        "usb_vid": 0x05AC,
        "usb_pid": 0x1201,
        "usb_serial": "0000002275EE",
        "vpd_raw_xml": plistlib.dumps({"SerialNumber": "YM0350TRVQ5"}),
    }
    writes = []
    monkeypatch.setattr(vpd_libusb, "query_all_ipods", lambda: [raw])
    monkeypatch.setattr(
        vpd_libusb,
        "write_sysinfo",
        lambda path, payload: writes.append((path, payload)) or True,
    )
    monkeypatch.setattr(vpd_libusb.sys, "platform", "win32")
    monkeypatch.setattr(
        sys,
        "argv",
        ["vpd_libusb", "--write-sysinfo", "--path", str(tmp_path)],
    )

    assert vpd_libusb.main() == 0

    output = capsys.readouterr().out
    assert "Raw Product SN:  YM0350TRVQ5" in output
    assert "VPD Unit Serial: 4" in output
    assert "Serial Rejected: usb_pid_conflict" in output
    assert writes
    written = writes[0][1]
    assert written["vpd_serial"] == "4"
    assert "SerialNumber" not in written
    assert "SerialNumber" not in plistlib.loads(written["vpd_raw_xml"])
