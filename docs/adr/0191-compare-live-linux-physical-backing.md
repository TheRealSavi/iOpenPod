# ADR-0191: Compare live Linux physical backing

- Status: Accepted
- Date: 2026-10-25
- Extends: ADR-0011, ADR-0167, and ADR-0190

## Context and decision

PR #283 reproduced a Host recovery safety gap: a Linux device mapping backed by
the selected iPod passed separation because its logical device number differed.
Comparing a udev serial with another path's block-number fallback can similarly
misidentify sibling partitions as separate devices. Changing persisted Device
Identity would also change the keys locating existing Host recovery journals.

Storage therefore compares live physical backing through a separate platform seam.
It retains the existing Device Identity, Volume Identity, journal keys, and selected
Connection Generation checks. Windows, macOS, and virtual adapters retain their
existing single-device lookup. Linux compares complete sets of kernel physical
leaves for both paths using one mount-table snapshot. It follows partition parents,
all device-mapper backing edges, complete non-degraded MD RAID graphs, bind aliases,
and absolute eCryptfs backing directories. Any shared leaf rejects the Host path.

The resolver uses kernel device numbers and sysfs relationships, independent of
udev serial availability and `/dev` aliases. It captures intermediate edges and
disk attachment sequences twice and checks the mount table again. Missing required
facts, suspended mappings, incomplete RAID, cycles, excessive depth, or observed
changes reject validation. These reads are preflight observations, not an atomic
kernel topology lock. Existing repeated recovery preflight and connection checks
remain required; privileged storage reconfiguration racing publication is not made
transactional by this change.

## Supported boundary and tradeoff

Understood filesystem types are ext2/3/4, XFS, VFAT/MSDOS, exFAT, NTFS3, HFS/HFS+,
and HFSX. Explicit external journal/log/realtime-device options are rejected.
Hardware block leaves must expose their attachment sequence. Unsupported virtual
devices and filesystem layouts fail closed with a diagnostic. In particular,
Btrfs (including apparently single-source mounts), loop images, ZFS, NFS, FUSE,
overlay, and tmpfs do not establish safe recovery storage through this resolver.
A Btrfs mount source does not establish the complete device set; a loop backing
filename alone does not establish a stable file-to-device relationship.

This deliberately narrows acceptance where the earlier identity-only comparison
could silently accept unsafe storage. Supporting these layouts needs trustworthy
complete backing evidence, not an exception to mandatory recovery preflight. No
privileges, dependencies, permissions, device mutations, or journal migrations are
introduced. Search-only ancestor access and discovery without udev remain separate
compatibility work from PR #283.

ADR-0192 subsequently handles search-only ancestors. udev remains a Linux
prerequisite; this work does not add a replacement discovery mechanism.
ADR-0193 extends the supported boundary to complete Btrfs member graphs. Loop-backed
recovery remains explicitly unsupported.

## Evidence and limits

Regression tests reach the real Storage recovery preflight using captured mounts,
real temporary directories, and a synthetic sysfs tree. They cover separate and
shared direct/sibling/bind/mapped/RAID paths, mixed identity formats, missing edges,
cycles, unsupported filesystems and loop devices, topology changes, attachment
changes, and remount invalidation. The original mapped-iPod case failed before the
change and now rejects recovery without creating its directory.

These are topology tests, not physical Linux acceptance. Actual encrypted/RAID
mounts, the released LMDE/Mint bundle, desktop launching, and interrupted physical
iPod transactions still require native acceptance.

Kernel interface references:

- [sysfs device hierarchy](https://www.kernel.org/doc/html/latest/filesystems/sysfs.html)
- [Block-device attachment sequences](https://www.kernel.org/doc/html/latest/admin-guide/abi-stable.html)
- [MD sysfs state](https://www.kernel.org/doc/html/latest/admin-guide/md.html)
