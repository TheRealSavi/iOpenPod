from __future__ import annotations

import plistlib
from pathlib import Path

from iopenpod.device.vpd_libusb import consumer_safe_vpd_info, write_sysinfo
from iopenpod.itunesdb_writer.hash72 import write_hash_info


def _virtual_ipod(root: Path) -> None:
    (root / "iPod_Control" / "iTunes").mkdir(parents=True)
    (root / "iPodInfo.json").write_text("{}", encoding="utf-8")


def test_vpd_sysinfo_writes_use_guarded_metadata_path(tmp_path: Path) -> None:
    _virtual_ipod(tmp_path)

    wrote = write_sysinfo(
        str(tmp_path),
        {
            "SerialNumber": "SERIAL123",
            "FireWireGUID": "0011223344556677",
            "ModelNumStr": "xA123",
            "vpd_raw_xml": b"noise<plist><dict></dict></plist>",
        },
    )

    device_dir = tmp_path / "iPod_Control" / "Device"
    assert wrote is True
    assert "SERIAL123" in (device_dir / "SysInfo").read_text(encoding="utf-8")
    assert (device_dir / "SysInfoExtended").read_bytes().startswith(b"<plist>")


def test_rejected_product_serial_is_not_written_to_device_metadata(
    tmp_path: Path,
) -> None:
    _virtual_ipod(tmp_path)
    raw_xml = plistlib.dumps({
        "SerialNumber": "YM0350TRVQ5",
        "FireWireGUID": "0000002275EE",
    })
    result = {
        "serial": "",
        "serial_rejected_reason": "usb_pid_conflict",
        "vpd_info": {
            "SerialNumber": "YM0350TRVQ5",
            "vpd_serial": "4",
            "FireWireGUID": "0000002275EE",
            "vpd_raw_xml": raw_xml,
        },
    }

    safe = consumer_safe_vpd_info(result)
    assert result["vpd_info"]["SerialNumber"] == "YM0350TRVQ5"
    assert result["vpd_info"]["vpd_serial"] == "4"
    assert "SerialNumber" not in safe
    assert "SerialNumber" not in plistlib.loads(safe["vpd_raw_xml"])

    assert write_sysinfo(str(tmp_path), safe)
    device_dir = tmp_path / "iPod_Control" / "Device"
    sysinfo_text = (device_dir / "SysInfo").read_text(encoding="utf-8")
    assert "pszSerialNumber" not in sysinfo_text
    assert "0000002275EE" in sysinfo_text
    assert "SerialNumber" not in plistlib.loads(
        (device_dir / "SysInfoExtended").read_bytes()
    )


def test_hash_info_write_uses_guarded_metadata_path(tmp_path: Path) -> None:
    _virtual_ipod(tmp_path)

    wrote = write_hash_info(
        str(tmp_path),
        bytes(range(20)),
        bytes(range(16)),
        bytes(range(12)),
    )

    payload = (tmp_path / "iPod_Control" / "Device" / "HashInfo").read_bytes()
    assert wrote is True
    assert payload == b"HASHv0" + bytes(range(20)) + bytes(range(12)) + bytes(range(16))
