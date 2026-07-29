from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from iopenpod.device import authority
from iopenpod.device.info import DeviceInfo
from iopenpod.device.virtual import create_virtual_ipod


class _RecordingSession:
    def __init__(self) -> None:
        self.writes: list[tuple[Path, bytes, Path]] = []

    def write_text_atomic(
        self,
        relative_path,
        text,
        *,
        allowed_subtree,
        encoding="utf-8",
    ):
        path = Path(relative_path)
        self.writes.append((path, text.encode(encoding), Path(allowed_subtree)))
        return path

    def write_bytes_atomic(self, relative_path, data, *, allowed_subtree):
        path = Path(relative_path)
        self.writes.append((path, bytes(data), Path(allowed_subtree)))
        return path


def test_update_sysinfo_uses_scan_identity_and_guarded_metadata_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "Device").mkdir(parents=True)
    session = _RecordingSession()
    captured: dict[str, str] = {}

    @contextmanager
    def fake_guard(path, **kwargs):
        captured["path"] = str(path)
        captured.update(kwargs)
        yield session

    monkeypatch.setattr(authority, "guarded_device_metadata_session", fake_guard)
    info = DeviceInfo(
        path=str(tmp_path),
        model_number="MA005",
        reported_volume_format="FAT32",
        volume_identity_key="scan-volume",
    )
    info._field_sources["model_number"] = "device_tree"

    authority.update_sysinfo(info)

    assert captured["expected_volume_identity_key"] == "scan-volume"
    assert captured["reported_volume_format"] == "FAT32"
    written_names = {path.name for path, _data, _subtree in session.writes}
    assert written_names == {"SysInfo", authority.AUTHORITY_FILENAME}
    assert all(
        subtree == Path("iPod_Control") / "Device"
        for _path, _data, subtree in session.writes
    )


def test_live_sysinfo_cache_uses_atomic_guarded_writes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "Device").mkdir(parents=True)
    session = _RecordingSession()

    @contextmanager
    def fake_guard(_path, **_kwargs):
        yield session

    monkeypatch.setattr(authority, "guarded_device_metadata_session", fake_guard)

    assert authority.cache_sysinfo_extended(
        str(tmp_path),
        b"<plist><dict></dict></plist>",
        expected_volume_identity_key="scan-volume",
    )

    written_names = [path.name for path, _data, _subtree in session.writes]
    assert written_names == ["SysInfoExtended", authority.AUTHORITY_FILENAME]


def test_update_sysinfo_skips_unidentified_partial_cache(tmp_path: Path) -> None:
    create_virtual_ipod(tmp_path, "MC297")
    sysinfo_path = tmp_path / "iPod_Control" / "Device" / "SysInfo"
    authority_path = (
        tmp_path / "iPod_Control" / "Device" / authority.AUTHORITY_FILENAME
    )
    before = sysinfo_path.read_bytes()
    authority_path.unlink(missing_ok=True)

    partial = DeviceInfo(
        path=str(tmp_path),
        model_family="iPod Classic",
        generation="6.5th Gen",
        capacity="120GB",
        firewire_guid="000A2700138A422D",
        usb_pid=0x1261,
        reported_volume_format="FAT32",
    )
    partial._field_sources.update({
        "model_family": "usb_pid",
        "generation": "inferred",
        "capacity": "disk_size",
        "firewire_guid": "sysfs",
        "usb_pid": "sysfs",
    })

    authority.update_sysinfo(partial)

    assert sysinfo_path.read_bytes() == before
    assert not authority_path.exists()


def test_authority_coverage_requires_current_core_sysinfo_values(
    tmp_path: Path,
) -> None:
    create_virtual_ipod(tmp_path, "MC297")
    device_dir = tmp_path / "iPod_Control" / "Device"
    sysinfo_path = device_dir / "SysInfo"
    sysinfo_path.write_text(
        "FirewireGuid: 0x000A2700138A422D\n",
        encoding="utf-8",
    )
    authority_path = device_dir / authority.AUTHORITY_FILENAME
    authority_path.write_text(
        json.dumps({
            "version": 1,
            "fields": {
                "pszSerialNumber": {
                    "value": "SERIAL000F0GD",
                    "source": "scsi_vpd",
                },
                "FirewireGuid": {
                    "value": "0x000A2700138A422D",
                    "source": "scsi_vpd",
                },
                "ModelNumStr": {
                    "value": "MC297",
                    "source": "scsi_vpd",
                },
            },
        }),
        encoding="utf-8",
    )

    all_tracked, _sources = authority.check_authority_coverage(str(tmp_path))

    assert not all_tracked


def test_authority_coverage_requires_bound_core_authority_values(
    tmp_path: Path,
) -> None:
    create_virtual_ipod(tmp_path, "MC297")
    device_dir = tmp_path / "iPod_Control" / "Device"
    authority_path = device_dir / authority.AUTHORITY_FILENAME
    authority_path.write_text(
        json.dumps({
            "version": 1,
            "fields": {
                "pszSerialNumber": {"source": "scsi_vpd"},
                "FirewireGuid": {"value": "", "source": "scsi_vpd"},
                "ModelNumStr": {"source": "scsi_vpd"},
            },
        }),
        encoding="utf-8",
    )

    all_tracked, _sources = authority.check_authority_coverage(str(tmp_path))

    assert not all_tracked


def test_authority_coverage_treats_structural_corruption_as_absent(
    tmp_path: Path,
) -> None:
    create_virtual_ipod(tmp_path, "MC297")
    authority_path = (
        tmp_path / "iPod_Control" / "Device" / authority.AUTHORITY_FILENAME
    )
    authority_path.write_text(
        json.dumps({
            "version": 1,
            "fields": {"pszSerialNumber": "not-an-entry"},
        }),
        encoding="utf-8",
    )

    assert authority.check_authority_coverage(str(tmp_path)) == (False, {})
