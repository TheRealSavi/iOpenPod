"""Btrfs membership must be complete before Host recovery can be accepted."""

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from tests.storage.linux_mount_test_support import (
    LinuxRecoveryLayout,
    add_linux_block,
    linux_recovery_layout,
)

from storage import HostPathOnPhysicalDeviceError, MountInspectionError
from storage.platform.linux import LinuxMountRecord
from storage.platform.linux_backing import LinuxBacking, capture_backing
from storage.platform.linux_btrfs import BtrfsFilesystemInfo

_FSID = "12345678-1234-5678-9abc-123456789abc"


@dataclass
class BtrfsLayout:
    recovery: LinuxRecoveryLayout
    root: Path
    info: BtrfsFilesystemInfo

    def add_member(self, node: Path, devid: int) -> None:
        member = self.root / "devinfo" / str(devid)
        member.mkdir(parents=True)
        for name, value in {
            "missing": "0",
            "replace_target": "0",
            "in_fs_metadata": "1",
            "fsid": _FSID,
        }.items():
            (member / name).write_text(value, encoding="ascii")
        (self.root / "devices").mkdir(exist_ok=True)
        (self.root / "devices" / node.name).symlink_to(node, target_is_directory=True)
        ids = [int(p.name) for p in (self.root / "devinfo").iterdir()]
        self.info = BtrfsFilesystemInfo(_FSID, len(ids), max(ids))


@pytest.fixture
def btrfs_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BtrfsLayout:
    recovery = linux_recovery_layout(tmp_path, monkeypatch)
    recovery.records[1] = replace(
        recovery.records[1],
        device_number="0:42",
        filesystem_type="btrfs",
        source="/dev/a-source-alias-that-is-not-used",
        options=("rw", "subvol=/@home"),
    )
    root = tmp_path / "sys/fs/btrfs" / _FSID
    root.mkdir(parents=True)
    (root / "exclusive_operation").write_text("none", encoding="ascii")
    layout = BtrfsLayout(recovery, root, BtrfsFilesystemInfo(_FSID, 1, 1))
    layout.add_member((tmp_path / "sys/class/block/fixture-host1").resolve(), 1)

    def info(path: Path, device_number: str | None = None) -> BtrfsFilesystemInfo:
        assert path.is_relative_to(recovery.home)
        assert device_number in {None, "0:42"}
        return layout.info

    monkeypatch.setattr("storage.platform.linux_backing.read_filesystem_info", info)
    return layout


@pytest.mark.parametrize("kind", ["single", "multiple", "mapped", "subvolume", "bind"])
def test_complete_btrfs_recovery_is_accepted(
    btrfs_layout: BtrfsLayout, tmp_path: Path, kind: str
) -> None:
    layout = btrfs_layout.recovery
    sysfs = tmp_path / "sys"
    if kind in {"multiple", "mapped"}:
        extra = add_linux_block(sysfs, "other-host", "8:32")
        if kind == "mapped":
            extra = add_linux_block(
                sysfs, "dm-0", "253:0", virtual=True, slaves=(extra,)
            )
        # Device IDs need not be contiguous after device removal.
        btrfs_layout.add_member(extra, 17)
    elif kind in {"subvolume", "bind"}:
        subvolume = layout.home / "nested"
        subvolume.mkdir()
        if kind == "bind":
            layout.records.append(
                replace(layout.records[1], mount_id="4", mount_point=subvolume)
            )
        assert not layout.adapter.paths_share_physical_device(subvolume, layout.ipod)
        assert layout.adapter.paths_share_physical_device(subvolume, layout.home)
    mounted = layout.storage.discover().volumes[0]
    assert mounted.physical_device.id.value == "linux:Apple_iPod_fixture"
    with layout.storage.open_session(mounted) as session:
        assert session.host_transaction_journals() == ()
    assert not (layout.home / "TransactionRecovery").exists()


def test_btrfs_descendant_must_match_the_captured_mount(
    btrfs_layout: BtrfsLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = btrfs_layout.recovery
    descendant = layout.home / "different-filesystem"
    descendant.mkdir()

    def info(path: Path, _device_number: str | None = None) -> BtrfsFilesystemInfo:
        if path == descendant:
            return replace(
                btrfs_layout.info, fsid="87654321-1234-5678-9abc-123456789abc"
            )
        return btrfs_layout.info

    monkeypatch.setattr("storage.platform.linux_backing.read_filesystem_info", info)
    with pytest.raises(MountInspectionError, match="does not match"):
        layout.adapter.paths_share_physical_device(descendant, layout.ipod)


@pytest.mark.parametrize("kind", ["direct", "sibling", "mapped"])
def test_btrfs_second_member_on_ipod_is_rejected(
    btrfs_layout: BtrfsLayout, tmp_path: Path, kind: str
) -> None:
    sysfs = tmp_path / "sys"
    ipod = (sysfs / "class/block/fixture-ipod1").resolve()
    if kind == "sibling":
        ipod = add_linux_block(sysfs, "ipod2", "8:18", parent=ipod.parent)
    elif kind == "mapped":
        ipod = add_linux_block(sysfs, "dm-0", "253:0", virtual=True, slaves=(ipod,))
    btrfs_layout.add_member(ipod, 2)
    layout = btrfs_layout.recovery
    mounted = layout.storage.discover().volumes[0]
    with (
        layout.storage.open_session(mounted) as session,
        pytest.raises(HostPathOnPhysicalDeviceError, match="Host recovery storage"),
    ):
        session.host_transaction_journals()
    assert not (layout.home / "TransactionRecovery").exists()


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "replace_target",
        "in_fs_metadata",
        "seed",
        "unreadable",
        "missing_info",
        "missing_link",
        "extra_link",
        "duplicate_link",
        "broken_link",
        "unindexed_link",
        "count",
        "max_id",
        "invalid_id",
        "zero_id",
        "empty",
        "replacement",
        "addition",
        "removal",
        "loop",
    ],
)
def test_unproven_btrfs_membership_fails_before_recovery_writes(
    btrfs_layout: BtrfsLayout, tmp_path: Path, failure: str
) -> None:
    root = btrfs_layout.root
    member = root / "devinfo/1"
    link = root / "devices/fixture-host1"
    if failure in {"missing", "replace_target", "in_fs_metadata"}:
        (member / failure).write_text("0" if failure == "in_fs_metadata" else "1")
    elif failure == "seed":
        (member / "fsid").write_text("87654321-1234-5678-9abc-123456789abc")
    elif failure == "unreadable":
        (member / "missing").unlink()
    elif failure == "missing_info":
        member.rename(root / "absent-info")
    elif failure == "missing_link":
        link.unlink()
    elif failure in {"extra_link", "duplicate_link"}:
        target = (
            link.resolve()
            if failure == "duplicate_link"
            else (tmp_path / "sys/class/block/fixture-ipod1").resolve()
        )
        (root / "devices/extra").symlink_to(target, target_is_directory=True)
    elif failure in {"broken_link", "unindexed_link"}:
        link.unlink()
        target = tmp_path / "unindexed"
        if failure == "unindexed_link":
            target.mkdir()
            (target / "dev").write_text("8:1")
        link.symlink_to(target, target_is_directory=True)
    elif failure in {"count", "max_id"}:
        btrfs_layout.info = replace(
            btrfs_layout.info,
            device_count=2 if failure == "count" else 1,
            max_device_id=2,
        )
    elif failure in {"invalid_id", "zero_id"}:
        member.rename(
            root / "devinfo" / ("invalid" if failure == "invalid_id" else "0")
        )
    elif failure == "empty":
        member.rename(root / "absent-info")
        link.unlink()
    elif failure in {"replacement", "addition", "removal"}:
        (root / "exclusive_operation").write_text(f"device {failure}")
    elif failure == "loop":
        loop = add_linux_block(tmp_path / "sys", "loop0", "7:0", virtual=True)
        btrfs_layout.add_member(loop, 2)
    layout = btrfs_layout.recovery
    mounted = layout.storage.discover().volumes[0]
    with (
        layout.storage.open_session(mounted) as session,
        pytest.raises(MountInspectionError, match="Host recovery storage"),
    ):
        session.host_transaction_journals()
    assert not (layout.home / "TransactionRecovery").exists()


@pytest.mark.parametrize(
    "change", ["fsid", "membership", "device", "operation", "attachment"]
)
def test_btrfs_changes_between_observations_are_rejected(
    btrfs_layout: BtrfsLayout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    calls = 0

    def capture_then_change(
        paths: tuple[Path, ...], records: tuple[LinuxMountRecord, ...], sys_class: Path
    ) -> LinuxBacking:
        nonlocal calls
        result = capture_backing(paths, records, sys_class)
        calls += 1
        if calls == 1:
            if change == "fsid":
                btrfs_layout.info = replace(
                    btrfs_layout.info, fsid="87654321-1234-5678-9abc-123456789abc"
                )
            elif change == "membership":
                extra = add_linux_block(tmp_path / "sys", "other-host", "8:32")
                btrfs_layout.add_member(extra, 2)
            elif change == "device":
                link = btrfs_layout.root / "devices/fixture-host1"
                link.unlink()
                link.symlink_to(
                    (tmp_path / "sys/class/block/fixture-ipod1").resolve(),
                    target_is_directory=True,
                )
            elif change == "operation":
                (btrfs_layout.root / "exclusive_operation").write_text("device replace")
            else:
                node = (tmp_path / "sys/class/block/fixture-host").resolve()
                (node / "diskseq").write_text("1000")
        return result

    monkeypatch.setattr("storage.platform.linux.capture_backing", capture_then_change)
    layout = btrfs_layout.recovery
    mounted = layout.storage.discover().volumes[0]
    with (
        layout.storage.open_session(mounted) as session,
        pytest.raises(MountInspectionError),
    ):
        session.host_transaction_journals()


def test_btrfs_changes_within_one_observation_are_rejected(
    btrfs_layout: BtrfsLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def info(_path: Path, _device_number: str | None = None) -> BtrfsFilesystemInfo:
        nonlocal calls
        calls += 1
        return (
            btrfs_layout.info
            if calls == 1
            else replace(btrfs_layout.info, device_count=2, max_device_id=2)
        )

    monkeypatch.setattr("storage.platform.linux_backing.read_filesystem_info", info)
    layout = btrfs_layout.recovery
    with pytest.raises(MountInspectionError, match="membership changed"):
        layout.adapter.paths_share_physical_device(layout.home, layout.ipod)
