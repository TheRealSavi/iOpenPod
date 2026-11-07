"""Read-only Linux physical-backing evidence, separate from persisted identities.

Only understood, complete graphs prove separation. In particular a logical device
number, a udev serial, or a single Btrfs source is not proof of physical isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from storage.errors import MountInspectionError
from storage.platform.linux_btrfs import read_filesystem_info

if TYPE_CHECKING:
    from storage.platform.linux import LinuxMountRecord

_SINGLE_DEVICE_FILESYSTEMS = frozenset(
    {
        "ext2",
        "ext3",
        "ext4",
        "xfs",
        "vfat",
        "msdos",
        "exfat",
        "ntfs3",
        "hfs",
        "hfsplus",
        "hfsx",
    }
)
_EXTERNAL_DEVICE_OPTIONS = ("journal_dev=", "journal_path=", "logdev=", "rtdev=")
_MAX_DEPTH = 64


@dataclass(frozen=True)
class LinuxBacking:
    devices: tuple[frozenset[str], ...]
    # Include intermediate edges and attachment sequences, not just final leaves.
    evidence: frozenset[tuple[str, str]]


def capture_backing(
    paths: tuple[Path, ...], records: tuple[LinuxMountRecord, ...], sys_class: Path
) -> LinuxBacking:
    resolver = _BackingResolver(records, sys_class)
    devices = tuple(resolver.for_path(path, frozenset()) for path in paths)
    return LinuxBacking(devices, frozenset(resolver.evidence.items()))


class _BackingResolver:
    def __init__(self, records: tuple[LinuxMountRecord, ...], sys_class: Path) -> None:
        self.records = records
        self.sys_devices = (sys_class.parent.parent / "devices").resolve(strict=True)
        self.sys_btrfs = sys_class.parent.parent / "fs" / "btrfs"
        self.evidence: dict[str, str] = {}
        self.nodes: dict[str, set[Path]] = {}
        for entry in sys_class.iterdir():
            try:
                node = entry.resolve(strict=True)
                number = (node / "dev").read_text(encoding="ascii").strip()
            except OSError:
                # An unreadable unrelated device is harmless. A required edge
                # missing from this index will fail closed in for_block().
                continue
            self.nodes.setdefault(number, set()).add(node)

    def read(self, path: Path) -> str:
        value = path.read_text(encoding="ascii").strip()
        key = str(path)
        if key in self.evidence and self.evidence[key] != value:
            raise MountInspectionError("Linux physical backing changed while reading")
        self.evidence[key] = value
        return value

    def for_path(self, path: Path, visiting: frozenset[str]) -> frozenset[str]:
        requested = path.resolve(strict=True)
        if not requested.is_dir():
            raise MountInspectionError(f"Backing location is not a directory: {path}")
        self.evidence[f"path:{path}"] = str(requested)
        matching = [r for r in self.records if requested.is_relative_to(r.mount_point)]
        if not matching:
            raise MountInspectionError(f"No mounted Volume contains {requested}")
        # The last matching record wins for stacked mounts at the same path.
        record = max(reversed(matching), key=lambda r: len(str(r.mount_point)))
        visiting = self.enter(f"mount:{record.mount_id}", visiting)
        if record.filesystem_type == "ecryptfs":
            backing = Path(record.source)
            if not backing.is_absolute():
                raise MountInspectionError(
                    "eCryptfs backing must be an absolute directory"
                )
            return self.for_path(backing, visiting)
        if record.filesystem_type == "btrfs":
            return self.for_btrfs(requested, record, visiting)
        if record.filesystem_type not in _SINGLE_DEVICE_FILESYSTEMS or any(
            option.startswith(_EXTERNAL_DEVICE_OPTIONS) for option in record.options
        ):
            raise MountInspectionError(
                f"Physical backing is unsupported for {record.filesystem_type} at "
                f"{record.mount_point}; use recovery storage on a supported local filesystem"
            )
        return self.for_block(record.device_number, visiting)

    def for_btrfs(
        self, path: Path, record: LinuxMountRecord, visiting: frozenset[str]
    ) -> frozenset[str]:
        info = read_filesystem_info(path, record.mount_id)
        visiting = self.enter(f"btrfs:{info.fsid}", visiting)
        self.evidence[f"btrfs:{path}"] = repr(info)
        root = self.sys_btrfs / info.fsid
        if self.read(root / "exclusive_operation") != "none":
            raise MountInspectionError("Btrfs storage reconfiguration is in progress")
        members = tuple(sorted((root / "devinfo").iterdir()))
        self.evidence[f"btrfs-members:{root}"] = repr(tuple(p.name for p in members))
        if (
            len(members) != info.device_count
            or any(not p.name.isascii() or not p.name.isdecimal() for p in members)
            or any(int(p.name) < 1 for p in members)
            or max(int(p.name) for p in members) != info.max_device_id
        ):
            raise MountInspectionError("Incomplete Btrfs device membership")
        for member in members:
            if (
                self.read(member / "missing") != "0"
                or self.read(member / "replace_target") != "0"
                or self.read(member / "in_fs_metadata") != "1"
                or self.read(member / "fsid") != info.fsid
            ):
                raise MountInspectionError(
                    "Missing, replacing, or seed Btrfs device cannot establish recovery backing"
                )
        links = tuple(sorted((root / "devices").iterdir()))
        targets = tuple(p.resolve(strict=True) for p in links)
        self.evidence[f"btrfs-devices:{root}"] = repr(tuple(str(p) for p in targets))
        if len(targets) != info.device_count or len(set(targets)) != len(targets):
            raise MountInspectionError("Incomplete Btrfs block-device membership")
        leaves: set[str] = set()
        for target in targets:
            number = self.read(target / "dev")
            if self.nodes.get(number) != {target}:
                raise MountInspectionError("Unresolved Btrfs block-device backing")
            leaves.update(self.for_block(number, visiting))
        if read_filesystem_info(path, record.mount_id) != info:
            raise MountInspectionError("Btrfs membership changed during inspection")
        return frozenset(leaves)

    def for_block(self, number: str, visiting: frozenset[str]) -> frozenset[str]:
        visiting = self.enter(f"block:{number}", visiting)
        nodes = self.nodes.get(number, set())
        if not re.fullmatch(r"\d+:\d+", number) or len(nodes) != 1:
            raise MountInspectionError(
                f"Missing or ambiguous Linux block device {number}"
            )
        node = next(iter(nodes))
        self.evidence[f"block:{number}"] = str(node)
        if (
            not node.is_relative_to(self.sys_devices)
            or self.read(node / "dev") != number
        ):
            raise MountInspectionError(f"Inconsistent Linux block device {number}")
        if (node / "partition").exists():
            if not self.read(node / "partition").isdigit():
                raise MountInspectionError(f"Invalid Linux partition {number}")
            return self.for_block(self.read(node.parent / "dev"), visiting)
        sequence = self.read(node / "diskseq")
        if not sequence.isdigit():
            raise MountInspectionError(f"Unknown attachment sequence for {number}")
        slaves = tuple(sorted((node / "slaves").iterdir()))
        self.evidence[f"slaves:{node}"] = repr(
            tuple(str(p.resolve(strict=True)) for p in slaves)
        )
        if (node / "dm").is_dir():
            if self.read(node / "dm" / "suspended") != "0" or not slaves:
                raise MountInspectionError(
                    f"Incomplete or suspended device mapping {number}"
                )
        elif (node / "md").is_dir():
            count = self.read(node / "md" / "raid_disks")
            if (
                not count.isdigit()
                or int(count) < 1
                or len(slaves) < int(count)
                or self.read(node / "md" / "degraded") != "0"
            ):
                raise MountInspectionError(f"Incomplete RAID backing for {number}")
        elif slaves or node.is_relative_to(self.sys_devices / "virtual"):
            raise MountInspectionError(f"Unsupported Linux block backing for {number}")
        else:
            return frozenset({number})
        leaves: set[str] = set()
        for slave in slaves:
            target = slave.resolve(strict=True)
            child = self.read(target / "dev")
            if self.nodes.get(child) != {target}:
                raise MountInspectionError(
                    f"Unresolved Linux backing edge for {number}"
                )
            leaves.update(self.for_block(child, visiting))
        return frozenset(leaves)

    @staticmethod
    def enter(key: str, visiting: frozenset[str]) -> frozenset[str]:
        if key in visiting or len(visiting) >= _MAX_DEPTH:
            raise MountInspectionError(
                "Cyclic or excessively deep Linux physical backing"
            )
        return visiting | {key}
