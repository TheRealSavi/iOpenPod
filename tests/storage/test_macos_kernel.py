# pyright: strict, reportPrivateUsage=false
"""Darwin ABI, parsing, and bounded macOS reinspection tests."""

from __future__ import annotations

import ctypes
import errno
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from storage import DeviceBus, HardwareIdentifiers, MountInspectionError
from storage.platform.macos import (
    _ATTR_VOL_CAPABILITIES,
    _ATTR_VOL_UUID,
    _MNT_NOATIME,
    _MNT_NOFOLLOW,
    _MNT_RDONLY,
    _VOL_CAP_FMT_CASE_SENSITIVE,
    MacOSPlatformAdapter,
    _bind_getattrlist,
    _bind_statfs,
    _bsd_identifiers,
    _DarwinAttributeSet,
    _DarwinAttrList,
    _DarwinStatFS,
    _DarwinVolumeAttributeBuffer,
    _DarwinVolumeCapabilities,
    _decode_required_c_string,
    _diskutil_info,
    _observation_from_kernel,
    _parse_volume_attributes,
    _read_statfs,
    _read_volume_attributes,
    _require_same_snapshot,
    _validate_diskutil_fallback,
)

_VOLUME_UUID = "12345678-1234-5678-9ABC-DEF012345678"


class _Function:
    argtypes = None
    restype = None

    def __init__(self, result: int = 0) -> None:
        self.result = result

    def __call__(self, *_args: object) -> int:
        return self.result


def _snapshot(
    root: Path,
    *,
    source: bytes = b"/dev/disk4s2",
    filesystem: bytes = b"apfs",
    fsid: tuple[int, int] = (0x12345678, -2),
    flags: int = 0,
) -> _DarwinStatFS:
    result = _DarwinStatFS()
    result.f_bsize = 4096
    result.f_blocks = 100
    result.f_bavail = 25
    result.f_fsid.val[0] = fsid[0]
    result.f_fsid.val[1] = fsid[1]
    result.f_flags = flags
    result.f_fstypename = filesystem
    result.f_mntonname = os.fsencode(root)
    result.f_mntfromname = source
    return result


def _attribute_result(
    *,
    returned: int = _ATTR_VOL_CAPABILITIES | _ATTR_VOL_UUID,
    length: int = 72,
    volume_uuid: str = _VOLUME_UUID,
    valid_case: bool = True,
    case_sensitive: bool = True,
) -> _DarwinVolumeAttributeBuffer:
    result = _DarwinVolumeAttributeBuffer()
    result.length = length
    result.returned.volattr = returned
    if valid_case:
        result.volume_capabilities.valid[0] = _VOL_CAP_FMT_CASE_SENSITIVE
    if case_sensitive:
        result.volume_capabilities.capabilities[0] = _VOL_CAP_FMT_CASE_SENSITIVE
    raw_uuid = uuid.UUID(volume_uuid).bytes
    result.volume_uuid[:] = raw_uuid
    return _DarwinVolumeAttributeBuffer.from_buffer_copy(bytes(result))


def test_darwin_statfs_abi_layout_is_exact() -> None:
    assert ctypes.sizeof(_DarwinStatFS) == 2168
    assert ctypes.alignment(_DarwinStatFS) == 8
    assert {
        field[0]: getattr(_DarwinStatFS, field[0]).offset
        for field in _DarwinStatFS._fields_
    } == {
        "f_bsize": 0,
        "f_iosize": 4,
        "f_blocks": 8,
        "f_bfree": 16,
        "f_bavail": 24,
        "f_files": 32,
        "f_ffree": 40,
        "f_fsid": 48,
        "f_owner": 56,
        "f_type": 60,
        "f_flags": 64,
        "f_fssubtype": 68,
        "f_fstypename": 72,
        "f_mntonname": 88,
        "f_mntfromname": 1112,
        "f_flags_ext": 2136,
        "f_reserved": 2140,
    }


def test_darwin_getattrlist_abi_layout_is_exact() -> None:
    assert ctypes.sizeof(_DarwinAttrList) == 24
    assert ctypes.sizeof(_DarwinAttributeSet) == 20
    assert ctypes.sizeof(_DarwinVolumeCapabilities) == 32
    assert ctypes.sizeof(_DarwinVolumeAttributeBuffer) == 72
    assert _DarwinVolumeAttributeBuffer.length.offset == 0
    assert _DarwinVolumeAttributeBuffer.returned.offset == 4
    assert _DarwinVolumeAttributeBuffer.volume_capabilities.offset == 24
    assert _DarwinVolumeAttributeBuffer.volume_uuid.offset == 56


def test_statfs_binder_prefers_inode64_and_has_exact_signature() -> None:
    preferred = _Function()
    plain = _Function()
    requested: list[str] = []

    class _LibC:
        def __getattr__(self, name: str) -> object:
            requested.append(name)
            return preferred if name == "statfs$INODE64" else plain

    bound = _bind_statfs(_LibC())

    assert cast("object", bound) is preferred
    assert requested == ["statfs$INODE64"]
    assert bound.argtypes == (
        ctypes.c_char_p,
        ctypes.POINTER(_DarwinStatFS),
    )
    assert bound.restype is ctypes.c_int


def test_statfs_binder_falls_back_to_plain_symbol() -> None:
    plain = _Function()
    requested: list[str] = []

    class _LibC:
        def __getattr__(self, name: str) -> object:
            requested.append(name)
            if name == "statfs$INODE64":
                raise AttributeError(name)
            return plain

    assert cast("object", _bind_statfs(_LibC())) is plain
    assert requested == ["statfs$INODE64", "statfs"]


def test_getattrlist_binder_uses_lp64_unsigned_int_options() -> None:
    function = _Function()

    class _LibC:
        getattrlist = function

    bound = _bind_getattrlist(_LibC())

    assert bound.argtypes == (
        ctypes.c_char_p,
        ctypes.POINTER(_DarwinAttrList),
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint,
    )
    assert bound.restype is ctypes.c_int
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert bound.argtypes[4] is ctypes.c_uint
        assert ctypes.sizeof(ctypes.c_uint) == 4
        if ctypes.sizeof(ctypes.c_ulong) == 8:
            assert id(bound.argtypes[4]) != id(ctypes.c_ulong)


def test_volume_attribute_parser_requires_returned_bits_and_extents() -> None:
    assert _parse_volume_attributes(_attribute_result()) == (_VOLUME_UUID, True)
    assert _parse_volume_attributes(_attribute_result(case_sensitive=False)) == (
        _VOLUME_UUID,
        False,
    )
    assert _parse_volume_attributes(_attribute_result(returned=0)) == (None, None)
    assert _parse_volume_attributes(_attribute_result(length=23)) == (None, None)
    assert _parse_volume_attributes(_attribute_result(length=55)) == (None, None)
    assert _parse_volume_attributes(_attribute_result(valid_case=False)) == (
        _VOLUME_UUID,
        None,
    )

    zero_uuid = _attribute_result()
    zero_uuid.volume_uuid[:] = bytes(16)
    assert _parse_volume_attributes(zero_uuid) == (None, True)


def test_getattrlist_syscall_failure_reports_captured_errno(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Failure(_Function):
        def __call__(self, *_args: object) -> int:
            ctypes.set_errno(errno.EIO)
            return -1

    monkeypatch.setattr(
        "storage.platform.macos._getattrlist_function",
        lambda: _Failure(),
    )

    with pytest.raises(MountInspectionError, match=os.strerror(errno.EIO)):
        _read_volume_attributes(tmp_path)


def test_required_c_strings_stop_at_nul_and_reject_empty() -> None:
    assert (
        _decode_required_c_string(
            b"APFS\0ignored",
            name="filesystem type",
            filesystem_type=True,
        )
        == "apfs"
    )
    with pytest.raises(MountInspectionError, match="empty"):
        _decode_required_c_string(b"\0ignored", name="Mount Point")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("/dev/disk4", ("disk4", "disk4")),
        ("/dev/disk4s2", ("disk4s2", "disk4")),
        ("/dev/disk4s2s1", ("disk4s2s1", "disk4")),
    ],
)
def test_bsd_source_parser_derives_whole_disk(
    source: str,
    expected: tuple[str, str],
) -> None:
    assert _bsd_identifiers(source) == expected


def test_bsd_source_parser_rejects_non_bsd_sources() -> None:
    with pytest.raises(MountInspectionError):
        _bsd_identifiers("map auto_home")


def test_mount_flag_constants_do_not_exchange_nofollow_and_noatime() -> None:
    assert _MNT_NOFOLLOW == 0x08000000
    assert _MNT_NOATIME == 0x10000000
    assert _MNT_NOFOLLOW != _MNT_NOATIME


def test_complete_reinspection_uses_only_two_statfs_and_one_getattrlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path, flags=_MNT_RDONLY)
    retained = _observation_from_kernel(
        snapshot,
        volume_uuid=_VOLUME_UUID,
        case_sensitive=False,
    )
    statfs_calls: list[Path] = []
    attribute_calls: list[Path] = []

    def read_statfs(path: Path) -> _DarwinStatFS:
        statfs_calls.append(path)
        return snapshot

    def read_attributes(path: Path) -> tuple[str | None, bool | None]:
        attribute_calls.append(path)
        return _VOLUME_UUID, False

    def fail_diskutil(_path: Path) -> dict[str, object]:
        pytest.fail("diskutil reached the complete kernel fast path")

    def fail_ioreg() -> dict[str, HardwareIdentifiers]:
        pytest.fail("IOKit reached reinspection")

    monkeypatch.setattr("storage.platform.macos._read_statfs", read_statfs)
    monkeypatch.setattr(
        "storage.platform.macos._read_volume_attributes",
        read_attributes,
    )
    monkeypatch.setattr(
        "storage.platform.macos._diskutil_info",
        fail_diskutil,
    )
    monkeypatch.setattr(
        "storage.platform.macos._ioreg_hardware_index",
        fail_ioreg,
    )

    current = MacOSPlatformAdapter().reinspect(retained)

    assert statfs_calls == [tmp_path, tmp_path]
    assert attribute_calls == [tmp_path]
    assert current.mount_instance == "macos-vfs:disk4s2:12345678:fffffffe"
    assert current.volume.total_bytes == 409600
    assert current.volume.available_bytes == 102400
    assert current.volume.capabilities.allocation_unit_size == 4096
    assert current.volume.capabilities.case_sensitive is False
    assert not current.volume.capabilities.writable


def test_reinspection_reuses_hardware_enrichment_only_for_same_physical_device(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_snapshot = _snapshot(tmp_path)
    base = _observation_from_kernel(
        first_snapshot,
        volume_uuid=_VOLUME_UUID,
        case_sensitive=False,
    )
    enriched_device = replace(
        base.physical_device,
        display_name="John's iPod",
        bus=DeviceBus.USB,
        removable=True,
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1261,
            transport_serial="TRANSPORT",
        ),
    )
    retained = replace(base, physical_device=enriched_device)
    snapshots = iter((first_snapshot, first_snapshot))

    def read_same_snapshot(_path: Path) -> _DarwinStatFS:
        return next(snapshots)

    def read_case_insensitive_attributes(
        _path: Path,
    ) -> tuple[str | None, bool | None]:
        return _VOLUME_UUID, False

    monkeypatch.setattr(
        "storage.platform.macos._read_statfs",
        read_same_snapshot,
    )
    monkeypatch.setattr(
        "storage.platform.macos._read_volume_attributes",
        read_case_insensitive_attributes,
    )

    same = MacOSPlatformAdapter().reinspect(retained)

    assert same.physical_device is enriched_device
    assert same.volume.label == retained.volume.label

    replacement_snapshot = _snapshot(tmp_path, source=b"/dev/disk5s2")
    replacement_snapshots = iter((replacement_snapshot, replacement_snapshot))

    def read_replacement_snapshot(_path: Path) -> _DarwinStatFS:
        return next(replacement_snapshots)

    monkeypatch.setattr(
        "storage.platform.macos._read_statfs",
        read_replacement_snapshot,
    )

    replacement = MacOSPlatformAdapter().reinspect(retained)

    assert replacement.physical_device.id.value == "macos:disk5"
    assert replacement.physical_device.identifiers == HardwareIdentifiers()
    assert replacement.physical_device.bus is DeviceBus.UNKNOWN
    assert replacement.volume.label == ""


def test_full_inspection_resolves_nested_path_before_diskutil_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nested = tmp_path / "folder"
    nested.mkdir()
    snapshot = _snapshot(tmp_path)
    statfs_calls = 0
    diskutil_targets: list[Path] = []

    def read_statfs(_path: Path) -> _DarwinStatFS:
        nonlocal statfs_calls
        statfs_calls += 1
        return snapshot

    def diskutil(target: Path) -> dict[str, object]:
        diskutil_targets.append(target)
        return {
            "DeviceIdentifier": "disk4s2",
            "DeviceNode": "/dev/disk4s2",
            "ParentWholeDisk": "disk4",
            "MountPoint": str(tmp_path),
            "VolumeUUID": _VOLUME_UUID.lower(),
            "FilesystemType": "apfs",
            "VolumeName": "iPod",
            "RemovableMedia": True,
        }

    def read_missing_attributes(_path: Path) -> tuple[str | None, bool | None]:
        return None, None

    monkeypatch.setattr("storage.platform.macos._read_statfs", read_statfs)
    monkeypatch.setattr(
        "storage.platform.macos._read_volume_attributes",
        read_missing_attributes,
    )
    monkeypatch.setattr("storage.platform.macos._diskutil_info", diskutil)
    monkeypatch.setattr("storage.platform.macos._ioreg_hardware_index", dict)

    observation = MacOSPlatformAdapter().inspect(nested)

    assert statfs_calls == 2
    assert diskutil_targets == [Path("/dev/disk4s2")]
    assert observation.mount_point.path == tmp_path
    assert observation.volume.id.value == f"macos:{_VOLUME_UUID}"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("DeviceIdentifier", "disk5s2"),
        ("DeviceNode", "/dev/disk5s2"),
        ("ParentWholeDisk", "disk5"),
        ("MountPoint", "/Volumes/Replacement"),
        ("VolumeUUID", "87654321-4321-8765-CBA9-876543210FED"),
    ],
)
def test_diskutil_fallback_rejects_each_identity_mismatch(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    snapshot = _snapshot(tmp_path)
    info: dict[str, object] = {
        "DeviceIdentifier": "disk4s2",
        "DeviceNode": "/dev/disk4s2",
        "ParentWholeDisk": "disk4",
        "MountPoint": str(tmp_path),
        "VolumeUUID": _VOLUME_UUID,
    }
    info[key] = value

    with pytest.raises(MountInspectionError):
        _validate_diskutil_fallback(info, snapshot, kernel_uuid=_VOLUME_UUID)


def test_diskutil_timeout_and_malformed_output_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("diskutil", 10)

    monkeypatch.setattr("storage.platform.macos.subprocess.run", timeout)
    with pytest.raises(MountInspectionError, match="Could not run diskutil"):
        _diskutil_info(tmp_path)

    def malformed_output(
        *_args: object,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            ["diskutil"],
            0,
            stdout=b"not a plist",
            stderr=b"",
        )

    monkeypatch.setattr(
        "storage.platform.macos.subprocess.run",
        malformed_output,
    )
    with pytest.raises(MountInspectionError, match="parse diskutil"):
        _diskutil_info(tmp_path)


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("fsid", (11, 13)),
        ("source", b"/dev/disk5s2"),
        ("filesystem", b"hfs"),
    ],
)
def test_snapshot_identity_changes_fail_closed(
    tmp_path: Path,
    change: str,
    value: object,
) -> None:
    first = _snapshot(tmp_path)
    second = _snapshot(tmp_path)
    if change == "fsid":
        fsid = cast("tuple[int, int]", value)
        second.f_fsid.val[0], second.f_fsid.val[1] = fsid
    elif change == "source":
        second.f_mntfromname = cast("bytes", value)
    else:
        second.f_fstypename = cast("bytes", value)

    with pytest.raises(MountInspectionError, match="changed"):
        _require_same_snapshot(first, second)


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin Libc and SDK")
def test_live_darwin_statfs_matches_active_sdk_layout(tmp_path: Path) -> None:
    xcrun = shutil.which("xcrun")
    if xcrun is None:
        pytest.skip("the active macOS SDK toolchain is unavailable")

    snapshot = _read_statfs(tmp_path)
    mount_point = Path(
        _decode_required_c_string(bytes(snapshot.f_mntonname), name="Mount Point")
    ).resolve()
    assert tmp_path.resolve().is_relative_to(mount_point)

    helper = tmp_path / "statfs-size"
    compiled = subprocess.run(
        [xcrun, "clang", "-x", "c", "-", "-o", os.fspath(helper)],
        input=(
            b"#include <stdio.h>\n#include <sys/mount.h>\n"
            b'int main(void) { printf("%zu", sizeof(struct statfs)); }\n'
        ),
        capture_output=True,
        timeout=30,
        check=False,
    )
    if compiled.returncode != 0:
        pytest.skip(compiled.stderr.decode("utf-8", errors="replace"))
    executed = subprocess.run(
        [os.fspath(helper)],
        capture_output=True,
        timeout=10,
        check=True,
    )
    assert int(executed.stdout) == ctypes.sizeof(_DarwinStatFS)
