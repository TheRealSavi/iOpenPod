from __future__ import annotations

import struct
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from iopenpod.device import (
    ChecksumType,
    DeviceCapabilities,
    create_virtual_ipod,
    filesystem,
    info,
    resolve_itdb_path,
    scanner,
)
from iopenpod.device.storage_safety import FileSizeLimitError
from iopenpod.device.write_guard import (
    DeviceWriteSafetyError,
    capture_database_generation,
)
from iopenpod.itunesdb_writer import mhbd_writer


def test_physical_device_without_sysinfo_does_not_guess_no_checksum(
    tmp_path: Path,
) -> None:
    assert info.detect_checksum_type(str(tmp_path)) == ChecksumType.UNKNOWN


def test_empty_physical_sysinfo_does_not_guess_no_checksum(tmp_path: Path) -> None:
    sysinfo = tmp_path / "iPod_Control" / "Device" / "SysInfo"
    sysinfo.parent.mkdir(parents=True)
    sysinfo.write_text("", encoding="utf-8")

    assert info.detect_checksum_type(str(tmp_path)) == ChecksumType.UNKNOWN


def test_database_firmware_limit_stops_before_replacing_live_database(
    tmp_path: Path,
) -> None:
    device = create_virtual_ipod(tmp_path, "MA005")
    database = tmp_path / "iPod_Control" / "iTunes" / "iTunesDB"
    original = database.read_bytes()
    limited = replace(device.capabilities, max_database_bytes=1)

    with pytest.raises(FileSizeLimitError, match="iTunesDB"):
        mhbd_writer.write_itunesdb(
            str(tmp_path),
            [],
            backup=False,
            capabilities=limited,
        )

    assert database.read_bytes() == original


def test_database_preflight_requires_space_for_atomic_staging(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "iTunesDB"
    profile = SimpleNamespace(
        max_file_size_bytes=1024,
        allocation_unit_size=1,
    )
    monkeypatch.setattr(
        mhbd_writer,
        "inspect_device_write_readiness",
        lambda _path: profile,
    )
    monkeypatch.setattr(
        mhbd_writer.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=9),
    )

    with pytest.raises(DeviceWriteSafetyError, match="enough free space"):
        mhbd_writer._preflight_database_install(
            str(tmp_path),
            str(database),
            10,
            capabilities=None,
        )


def test_linux_detects_actual_mounted_filesystem_with_findmnt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(filesystem.sys, "platform", "linux")

    def fake_run(args, **_kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=0, stdout="vfat\n", stderr="")

    monkeypatch.setattr(filesystem.subprocess, "run", fake_run)

    assert filesystem.detect_filesystem_type(tmp_path) == "vfat"
    assert commands == [
        ["findmnt", "-n", "-o", "FSTYPE", "--target", str(tmp_path)]
    ]


def test_database_platform_preserves_reference_and_reports_filesystem_mismatch() -> None:
    resolution = filesystem.resolve_itunesdb_platform(
        filesystem_type="hfsplus",
        reference_platform=2,
    )

    assert resolution.flag == 2
    assert resolution.source == "existing_database"
    assert resolution.inferred_flag == 1
    assert resolution.mismatch is True


def test_database_platform_uses_filesystem_only_without_valid_reference() -> None:
    resolution = filesystem.resolve_itunesdb_platform(
        filesystem_type="hfsplus",
        reference_platform=0,
    )

    assert resolution.flag == 1
    assert resolution.source == "filesystem"
    assert resolution.mismatch is False


def test_scanner_records_and_warns_about_mac_filesystem_on_linux(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(scanner.sys, "platform", "linux")
    monkeypatch.setattr(scanner, "_identify_via_sysinfo", lambda _path: {})
    monkeypatch.setattr(scanner, "_identify_via_hashing_scheme", lambda _path: {})
    monkeypatch.setattr(
        scanner,
        "detect_filesystem_type",
        lambda _path: "hfsplus",
    )

    result = scanner._probe_filesystem("/media/user/IPOD")

    assert result["filesystem_type"] == "hfsplus"
    assert "Mac-formatted iPod filesystem detected on Linux" in caplog.text


def test_scanner_records_scan_time_volume_identity(monkeypatch) -> None:
    monkeypatch.setattr(scanner, "detect_filesystem_type", lambda _path: "vfat")
    monkeypatch.setattr(scanner, "_identify_via_sysinfo", lambda _path: {})
    monkeypatch.setattr(scanner, "_identify_via_hashing_scheme", lambda _path: {})
    monkeypatch.setattr(
        scanner,
        "inspect_filesystem_profile",
        lambda _path: SimpleNamespace(
            filesystem_type="vfat",
            identity=SimpleNamespace(is_complete=True),
        ),
    )
    monkeypatch.setattr(scanner, "volume_lock_key", lambda _profile: "scan-volume")

    result = scanner._probe_filesystem("/media/user/IPOD")

    assert result["volume_identity_key"] == "scan-volume"
    assert result["_sources"]["volume_identity_key"] == "mounted_volume_identity"


def test_writer_logs_actual_filesystem_and_preserved_platform_mismatch(
    monkeypatch,
    caplog,
    tmp_path: Path,
) -> None:
    create_virtual_ipod(tmp_path, "MA005")
    itunes_dir = tmp_path / "iPod_Control" / "iTunes"
    predictable_temps = [
        itunes_dir / "iTunesDB.tmp",
        itunes_dir / "iTunesDB.backup.tmp",
    ]
    for predictable in predictable_temps:
        predictable.write_bytes(b"do-not-truncate")
    monkeypatch.setattr(
        mhbd_writer,
        "detect_filesystem_type",
        lambda _path: "hfsplus",
    )
    caplog.set_level("INFO", logger=mhbd_writer.__name__)

    assert mhbd_writer.write_itunesdb(str(tmp_path), []) is True

    db_path = tmp_path / "iPod_Control" / "iTunes" / "iTunesDB"
    assert struct.unpack_from("<H", db_path.read_bytes(), 0x20)[0] == 2
    assert all(path.read_bytes() == b"do-not-truncate" for path in predictable_temps)
    assert (
        "iTunesDB platform selection: flag=2 (Windows) "
        "source=existing_database filesystem=hfsplus reference=2"
    ) in caplog.text
    assert "iTunesDB platform/filesystem mismatch" in caplog.text


def test_writer_prefers_on_device_platform_over_foreign_reference_on_hfs(
    monkeypatch,
    caplog,
    tmp_path: Path,
) -> None:
    create_virtual_ipod(tmp_path, "MA005")
    db_path = tmp_path / "iPod_Control" / "iTunes" / "iTunesDB"
    existing = bytearray(db_path.read_bytes())
    struct.pack_into("<H", existing, 0x20, 1)
    db_path.write_bytes(existing)
    foreign_reference = tmp_path / "foreign-reference.itdb"
    foreign_reference.write_bytes(mhbd_writer.write_mhbd([], platform=2))
    monkeypatch.setattr(mhbd_writer, "detect_filesystem_type", lambda _path: "hfsplus")
    caplog.set_level("INFO", logger=mhbd_writer.__name__)

    assert mhbd_writer.write_itunesdb(
        str(tmp_path),
        [],
        backup=False,
        reference_itdb_path=str(foreign_reference),
    ) is True

    assert struct.unpack_from("<H", db_path.read_bytes(), 0x20)[0] == 1
    assert (
        "iTunesDB platform selection: flag=1 (Mac) "
        "source=existing_database filesystem=hfsplus reference=1"
    ) in caplog.text


def test_writer_logs_supplied_reference_as_reference_database(
    monkeypatch,
    caplog,
    tmp_path: Path,
) -> None:
    create_virtual_ipod(tmp_path, "MA005")
    db_path = tmp_path / "iPod_Control" / "iTunes" / "iTunesDB"
    existing = bytearray(db_path.read_bytes())
    struct.pack_into("<H", existing, 0x20, 0)
    db_path.write_bytes(existing)
    external_reference = tmp_path / "reference.itdb"
    external_reference.write_bytes(mhbd_writer.write_mhbd([], platform=1))
    monkeypatch.setattr(mhbd_writer, "detect_filesystem_type", lambda _path: "hfsplus")
    caplog.set_level("INFO", logger=mhbd_writer.__name__)

    assert mhbd_writer.write_itunesdb(
        str(tmp_path),
        [],
        backup=False,
        reference_itdb_path=str(external_reference),
    ) is True

    assert struct.unpack_from("<H", db_path.read_bytes(), 0x20)[0] == 1
    assert "source=reference_database filesystem=hfsplus reference=1" in caplog.text


def test_writer_uses_retained_capabilities_when_selected_device_changes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    itunes_dir = tmp_path / "iPod_Control" / "iTunes"
    itunes_dir.mkdir(parents=True)
    (tmp_path / "iPodInfo.json").write_text("{}", encoding="utf-8")
    (itunes_dir / "iTunesDB").write_bytes(mhbd_writer.write_mhbd([]))
    retained_capabilities = DeviceCapabilities(supports_compressed_db=True)
    monkeypatch.setattr(
        "iopenpod.device.itdb_write_filename",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("mutable selected-device filename must not be consulted")
        ),
    )

    assert mhbd_writer.write_itunesdb(
        str(tmp_path),
        [],
        backup=False,
        capabilities=retained_capabilities,
        force_checksum=ChecksumType.NONE,
    ) is True

    assert (itunes_dir / "iTunesCDB").read_bytes()[:4] == b"mhbd"
    assert (itunes_dir / "iTunesDB").read_bytes() == b""


def test_writer_rejects_truncated_existing_database_before_mutation(
    tmp_path: Path,
) -> None:
    create_virtual_ipod(tmp_path, "MA005")
    db_path = tmp_path / "iPod_Control" / "iTunes" / "iTunesDB"
    original = b"mhbd-truncated"
    db_path.write_bytes(original)

    with pytest.raises(RuntimeError, match="truncated or malformed"):
        mhbd_writer.write_itunesdb(str(tmp_path), [], backup=False)

    assert db_path.read_bytes() == original
    assert list(db_path.parent.glob(".iop-*.tmp")) == []


def test_writer_rejects_unreadable_nonempty_existing_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    create_virtual_ipod(tmp_path, "MA005")
    db_path = tmp_path / "iPod_Control" / "iTunes" / "iTunesDB"
    original_open = open

    def guarded_open(path, mode="r", *args, **kwargs):
        if Path(path) == db_path and "r" in mode:
            raise PermissionError("device read denied")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded_open)

    with pytest.raises(RuntimeError, match="could not be read safely"):
        mhbd_writer.write_itunesdb(str(tmp_path), [], backup=False)

    with original_open(db_path, "rb") as database:
        assert database.read(4) == b"mhbd"
    assert list(db_path.parent.glob(".iop-*.tmp")) == []


def test_writer_runs_generation_check_immediately_before_database_replace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    create_virtual_ipod(tmp_path, "MA005")
    events: list[str] = []

    monkeypatch.setattr(
        mhbd_writer,
        "durable_replace",
        lambda _source, _target: events.append("replace"),
    )

    assert mhbd_writer.write_itunesdb(
        str(tmp_path),
        [],
        backup=False,
        before_database_replace=lambda: events.append("generation-check"),
    ) is True
    # The first replacement is the live database commit. A second replacement
    # may atomically truncate the obsolete alternate database filename.
    assert events[:2] == ["generation-check", "replace"]


def test_database_resolution_ignores_zero_byte_alternate_marker(
    tmp_path: Path,
) -> None:
    itunes_dir = tmp_path / "iPod_Control" / "iTunes"
    itunes_dir.mkdir(parents=True)
    (itunes_dir / "iTunesCDB").write_bytes(b"")
    (itunes_dir / "iTunesDB").write_bytes(b"mhbd-current")

    assert resolve_itdb_path(str(tmp_path)) == str(itunes_dir / "iTunesDB")
    assert capture_database_generation(tmp_path).filename == "iTunesDB"


def test_write_filename_ignores_stale_marker_and_other_selected_device(
    monkeypatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "classic"
    other = tmp_path / "nano"
    itunes_dir = target / "iPod_Control" / "iTunes"
    itunes_dir.mkdir(parents=True)
    (itunes_dir / "iTunesCDB").write_bytes(b"")
    (itunes_dir / "iTunesDB").write_bytes(b"mhbd-current")
    monkeypatch.setattr(
        info,
        "get_current_device",
        lambda: SimpleNamespace(
            path=str(other),
            model_family="iPod Nano",
            generation="5th Gen",
        ),
    )

    assert info.itdb_write_filename(str(target)) == "iTunesDB"


def test_known_classic_write_target_overrides_foreign_cdb_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    itunes_dir = tmp_path / "iPod_Control" / "iTunes"
    itunes_dir.mkdir(parents=True)
    (itunes_dir / "iTunesCDB").write_bytes(b"mhbd-foreign")
    (itunes_dir / "iTunesDB").write_bytes(b"mhbd-current")
    monkeypatch.setattr(
        info,
        "get_current_device",
        lambda: SimpleNamespace(
            path=str(tmp_path),
            model_family="iPod Classic",
            generation="6th Gen",
        ),
    )

    assert info.itdb_write_filename(str(tmp_path)) == "iTunesDB"
    assert info.resolve_itdb_path(str(tmp_path)) == str(itunes_dir / "iTunesDB")
    assert capture_database_generation(tmp_path).filename == "iTunesDB"


def test_known_compressed_device_ignores_foreign_nonempty_itunesdb(
    monkeypatch,
    tmp_path: Path,
) -> None:
    itunes_dir = tmp_path / "iPod_Control" / "iTunes"
    itunes_dir.mkdir(parents=True)
    (itunes_dir / "iTunesCDB").write_bytes(b"mhbd-current")
    (itunes_dir / "iTunesDB").write_bytes(b"mhbd-foreign")
    monkeypatch.setattr(
        info,
        "get_current_device",
        lambda: SimpleNamespace(
            path=str(tmp_path),
            model_family="iPod Nano",
            generation="5th Gen",
        ),
    )

    assert info.itdb_write_filename(str(tmp_path)) == "iTunesCDB"
    assert info.resolve_itdb_path(str(tmp_path)) == str(itunes_dir / "iTunesCDB")
    assert capture_database_generation(tmp_path).filename == "iTunesCDB"


def test_known_classic_recovers_from_only_nonempty_alternate_database(
    monkeypatch,
    tmp_path: Path,
) -> None:
    itunes_dir = tmp_path / "iPod_Control" / "iTunes"
    itunes_dir.mkdir(parents=True)
    (itunes_dir / "iTunesDB").write_bytes(b"")
    (itunes_dir / "iTunesCDB").write_bytes(b"mhbd-recovery-source")
    monkeypatch.setattr(
        info,
        "get_current_device",
        lambda: SimpleNamespace(
            path=str(tmp_path),
            model_family="iPod Classic",
            generation="6th Gen",
        ),
    )

    assert info.resolve_itdb_path(str(tmp_path)) == str(itunes_dir / "iTunesCDB")
    assert info.itdb_write_filename(str(tmp_path)) == "iTunesDB"
    assert capture_database_generation(tmp_path).filename == "iTunesCDB"
