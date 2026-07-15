"""Unit tests for the macOS ioreg → (BSD disk, USB serial) parser.

These cover the bug that crashed device identification with
``ValueError: zip() argument 2 is longer than argument 1`` whenever the
Mac had any non-iPod Apple USB device on the bus (keyboard, AirPods
receiver, hub, iPhone).  The parser now extracts the iPod's own serial
inline from the text ioreg, so unrelated Apple devices never end up
paired with an iPod's BSD whole-disk name.
"""

from __future__ import annotations

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
