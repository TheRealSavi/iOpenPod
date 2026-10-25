"""Exercise physical separation through the real Storage recovery preflight."""

import hashlib
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from tests.storage.linux_mount_test_support import (
    add_linux_block,
    linux_recovery_layout,
)

from storage import (
    AccessMode,
    DevicePath,
    FileContent,
    FlushResult,
    HostPathOnPhysicalDeviceError,
    MountInspectionError,
    StorageTransaction,
    TransactionWrite,
    VolumeIdentityChangedError,
)
from storage.models import VolumeObservation
from storage.platform.linux import (
    LinuxMountRecord,
    LinuxPlatformAdapter,
    parse_mountinfo,
)
from storage.platform.linux_backing import LinuxBacking, capture_backing


@pytest.mark.skipif(sys.platform != "linux", reason="requires native Linux sysfs")
def test_native_linux_local_mount_resolves_its_physical_backing(tmp_path: Path) -> None:
    """Read real kernel facts without mounting, opening, or writing block devices."""
    records = parse_mountinfo(Path("/proc/self/mountinfo").read_text())
    record = max(
        (
            r
            for r in reversed(records)
            if tmp_path.resolve().is_relative_to(r.mount_point)
        ),
        key=lambda r: len(str(r.mount_point)),
    )
    if record.filesystem_type not in {"ext2", "ext3", "ext4", "xfs"}:
        pytest.skip(f"Native test location uses unsupported {record.filesystem_type}")
    assert LinuxPlatformAdapter().paths_share_physical_device(tmp_path, tmp_path)


def test_mapped_recovery_backed_by_the_ipod_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = linux_recovery_layout(tmp_path, monkeypatch)
    sysfs = tmp_path / "sys"
    ipod_partition = (sysfs / "class/block/fixture-ipod1").resolve()
    add_linux_block(sysfs, "dm-0", "253:0", virtual=True, slaves=(ipod_partition,))
    layout.records[1] = replace(
        layout.records[1],
        device_number="253:0",
        filesystem_type="ext4",
        source="/dev/dm-0",
    )
    mounted = layout.storage.discover().volumes[0]
    with (
        layout.storage.open_session(mounted) as session,
        pytest.raises(HostPathOnPhysicalDeviceError, match="Host recovery storage"),
    ):
        session.host_transaction_journals()
    assert not (layout.home / "TransactionRecovery").exists()


@pytest.mark.parametrize(
    "kind", ["direct", "alias", "sibling", "dm", "nested", "raid", "ecryptfs"]
)
@pytest.mark.parametrize("shared", [False, True])
def test_complete_backing_graphs_compare_all_physical_leaves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, shared: bool
) -> None:
    layout = linux_recovery_layout(tmp_path, monkeypatch)
    sysfs = tmp_path / "sys"
    partition = (
        sysfs / "class/block" / ("fixture-ipod1" if shared else "fixture-host1")
    ).resolve()
    number = (partition / "dev").read_text()
    source = f"/dev/{partition.name}"
    if kind == "alias":
        source = "/dev/disk/by-uuid/an-alias-not-used-for-backing"
    elif kind == "sibling":
        number = "8:18" if shared else "8:2"
        add_linux_block(sysfs, "sibling2", number, parent=partition.parent)
        source = "/dev/sibling2"
    elif kind in {"dm", "nested", "raid", "ecryptfs"}:
        inner = add_linux_block(
            sysfs, "dm-0", "253:0", virtual=True, slaves=(partition,)
        )
        number, source = "253:0", "/dev/dm-0"
        if kind == "nested":
            add_linux_block(sysfs, "dm-1", "253:1", virtual=True, slaves=(inner,))
            number, source = "253:1", "/dev/dm-1"
        elif kind == "raid":
            other = add_linux_block(sysfs, "other-host", "8:32")
            add_linux_block(sysfs, "md0", "9:0", virtual=True, slaves=(other, inner))
            number, source = "9:0", "/dev/md0"
    index = 0 if kind == "ecryptfs" else 1
    layout.records[index] = replace(
        layout.records[index],
        device_number=number,
        filesystem_type="ext4",
        source=source,
    )
    mounted = layout.storage.discover().volumes[0]
    # Udev serial persistence is deliberately independent of live block numbers.
    assert mounted.physical_device.id.value == "linux:Apple_iPod_fixture"
    with layout.storage.open_session(mounted) as session:
        if shared:
            with pytest.raises(HostPathOnPhysicalDeviceError):
                session.host_transaction_journals()
        else:
            assert session.host_transaction_journals() == ()
    assert not (layout.home / "TransactionRecovery").exists()


@pytest.mark.parametrize(
    "failure",
    [
        "empty",
        "missing_edge",
        "partial",
        "cycle",
        "suspended",
        "degraded",
        "missing_sequence",
        "unknown_virtual",
    ],
)
def test_incomplete_or_unsupported_block_graphs_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    layout = linux_recovery_layout(tmp_path, monkeypatch)
    sysfs = tmp_path / "sys"
    host_partition = (sysfs / "class/block/fixture-host1").resolve()
    node = add_linux_block(
        sysfs,
        "md0" if failure == "degraded" else "dm-0",
        "253:0",
        virtual=True,
        slaves=() if failure == "empty" else (host_partition,),
    )
    if failure in {"missing_edge", "partial"}:
        (node / "slaves/missing").symlink_to(
            sysfs / "missing", target_is_directory=True
        )
        if failure == "missing_edge":
            (node / "slaves" / host_partition.name).unlink()
    elif failure == "cycle":
        (node / "slaves/cycle").symlink_to(node, target_is_directory=True)
    elif failure == "suspended":
        (node / "dm/suspended").write_text("1")
    elif failure == "degraded":
        (node / "md/degraded").write_text("1")
    elif failure == "missing_sequence":
        (host_partition.parent / "diskseq").unlink()
    elif failure == "unknown_virtual":
        (node / "dm/suspended").unlink()
        (node / "dm").rmdir()
    layout.records[1] = replace(
        layout.records[1],
        device_number="253:0",
        filesystem_type="ext4",
        source=f"/dev/{node.name}",
    )
    mounted = layout.storage.discover().volumes[0]
    with (
        layout.storage.open_session(mounted) as session,
        pytest.raises(MountInspectionError, match="Host recovery storage"),
    ):
        session.host_transaction_journals()
    assert not (layout.home / "TransactionRecovery").exists()


@pytest.mark.parametrize(
    "filesystem", ["btrfs", "zfs", "nfs", "fuse", "overlay", "tmpfs"]
)
def test_filesystems_with_unproven_backing_fail_even_with_a_source_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filesystem: str
) -> None:
    layout = linux_recovery_layout(tmp_path, monkeypatch)
    layout.records[1] = replace(
        layout.records[1],
        device_number="8:1",
        filesystem_type=filesystem,
        source="/dev/fixture-host1",
    )
    mounted = layout.storage.discover().volumes[0]
    with (
        layout.storage.open_session(mounted) as session,
        pytest.raises(MountInspectionError, match=f"unsupported for {filesystem}"),
    ):
        session.host_transaction_journals()


@pytest.mark.parametrize("shared", [False, True])
def test_loop_backing_cannot_masquerade_as_an_independent_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shared: bool
) -> None:
    layout = linux_recovery_layout(tmp_path, monkeypatch)
    image = (layout.ipod if shared else layout.host) / "disk.img"
    image.write_bytes(b"captured loop image")
    node = add_linux_block(tmp_path / "sys", "loop0", "7:0", virtual=True)
    (node / "loop").mkdir()
    (node / "loop/backing_file").write_text(str(image))
    layout.records[1] = replace(
        layout.records[1],
        device_number="7:0",
        filesystem_type="ext4",
        source="/dev/loop0",
    )
    mounted = layout.storage.discover().volumes[0]
    with (
        layout.storage.open_session(mounted) as session,
        pytest.raises(MountInspectionError, match="Unsupported Linux block backing"),
    ):
        session.host_transaction_journals()


@pytest.mark.parametrize(
    "option",
    ["journal_dev=8:17", "logdev=/dev/fixture-ipod1", "rtdev=/dev/fixture-ipod1"],
)
def test_external_filesystem_devices_need_complete_backing_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, option: str
) -> None:
    layout = linux_recovery_layout(tmp_path, monkeypatch)
    layout.records[0] = replace(layout.records[0], options=("rw", option))
    mounted = layout.storage.discover().volumes[0]
    with (
        layout.storage.open_session(mounted) as session,
        pytest.raises(MountInspectionError, match="unsupported"),
    ):
        session.host_transaction_journals()


@pytest.mark.parametrize(
    "change", ["mapping", "attachment", "host_remount", "device_remount"]
)
def test_backing_changes_during_preflight_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    import storage.platform.linux as linux

    layout = linux_recovery_layout(tmp_path, monkeypatch)
    sysfs = tmp_path / "sys"
    host_partition = (sysfs / "class/block/fixture-host1").resolve()
    node = add_linux_block(
        sysfs, "dm-0", "253:0", virtual=True, slaves=(host_partition,)
    )
    layout.records[1] = replace(
        layout.records[1],
        device_number="253:0",
        filesystem_type="ext4",
        source="/dev/dm-0",
    )
    capture = capture_backing
    calls = 0

    def capture_then_change(
        paths: tuple[Path, ...], records: tuple[LinuxMountRecord, ...], sys_class: Path
    ) -> LinuxBacking:
        nonlocal calls
        result = capture(paths, records, sys_class)
        calls += 1
        if calls == 1:
            if change == "mapping":
                (node / "slaves" / host_partition.name).unlink()
                ipod = (sysfs / "class/block/fixture-ipod1").resolve()
                (node / "slaves" / ipod.name).symlink_to(ipod, target_is_directory=True)
            elif change == "attachment":
                (host_partition.parent / "diskseq").write_text("9999")
            else:
                index = 2 if change == "device_remount" else 1
                layout.records[index] = replace(layout.records[index], mount_id="99")
        return result

    monkeypatch.setattr(linux, "capture_backing", capture_then_change)
    mounted = layout.storage.discover().volumes[0]
    expected = (
        VolumeIdentityChangedError
        if change == "device_remount"
        else MountInspectionError
    )
    with (
        layout.storage.open_session(mounted) as session,
        pytest.raises(expected, match="changed"),
    ):
        session.host_transaction_journals()
    if change == "device_remount":
        with pytest.raises(VolumeIdentityChangedError):
            layout.storage.open_session(mounted)


def test_linux_host_recovery_keeps_existing_journal_identity_and_restoration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = linux_recovery_layout(tmp_path, monkeypatch)

    def flush(_observation: VolumeObservation) -> FlushResult:
        return FlushResult(True, "fixture flush")

    monkeypatch.setattr(layout.adapter, "flush", flush)
    mounted = layout.storage.discover().volumes[0]
    original, replacement = b"original", b"replacement"
    path = DevicePath("track.bin")
    (layout.ipod / "track.bin").write_bytes(original)
    with layout.storage.open_session(mounted, access=AccessMode.READ_WRITE) as session:
        plan = StorageTransaction(
            (
                TransactionWrite(
                    path,
                    replacement,
                    FileContent(
                        len(replacement), hashlib.sha256(replacement).hexdigest()
                    ),
                    session.fingerprint(path),
                ),
            ),
            host_recovery=True,
        )
        published = session.execute_transaction(plan)
        identity = hashlib.sha256(
            (mounted.physical_device.id.value + "\0" + mounted.volume.id.value).encode()
        ).hexdigest()
        assert (layout.home / "TransactionRecovery" / identity).is_dir()
        assert session.read(path) == replacement
    with layout.storage.open_session(mounted, access=AccessMode.READ_WRITE) as session:
        assert session.host_transaction_journals() == (published.recovery.journal_path,)
        restored = session.restore_transaction(
            session.inspect_transaction(published.recovery.journal_path)
        )
        assert session.read(path) == original
        session.finalize_transaction(restored.recovery)
        assert session.host_transaction_journals() == ()
