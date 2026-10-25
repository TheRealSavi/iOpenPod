# ADR-0193: Resolve Btrfs recovery through all member devices

- Status: Accepted
- Date: 2026-10-25
- Extends: ADR-0191

## Context and decision

Rejecting every Btrfs recovery location excludes ordinary Linux installations,
including a single internal disk. A mount source still cannot establish the full
device set. Storage therefore uses the read-only `BTRFS_IOC_FS_INFO` interface on
an open directory to obtain the filesystem UUID, device count, and maximum device
ID. The open descriptor's `/proc/self/fdinfo` mount ID must match the captured
mount-table entry. Filesystem device numbers are unsuitable for this comparison:
Btrfs subvolumes and bind aliases can report different values. Open descriptors
are always closed, and named directory identity is checked after the query.

The filesystem UUID selects `/sys/fs/btrfs/<uuid>`. Its `devinfo` entries and
`devices` links must both match the kernel device count, with unique resolved block
targets and the expected maximum device ID. Sparse device IDs are permitted.
Every member must be present, recorded in filesystem metadata, owned by that
filesystem, and outside device replacement. Each block target must match the
kernel block index and resolve through ADR-0191's existing partition, mapping,
and RAID checks. Any physical leaf shared with the selected iPod rejects recovery.

The filesystem query brackets member inspection; complete backing observations
are still repeated with a final mount-table check. An active exclusive operation
(including a paused balance), changed membership, missing evidence, or a seed
filesystem layout rejects validation. These checks detect observed changes; they
do not lock out privileged storage reconfiguration during later publication.

## Supported boundary and consequences

This supports ordinary single-device and multi-device Btrfs, subvolumes, and bind
aliases when every member has supported physical backing. Loop-backed recovery
remains explicitly unsupported, including Btrfs on loop images. Unsupported
virtual devices and degraded or incomplete member graphs remain refused.

Inspection requires no elevation, block-device opens, external commands, or new
runtime dependencies. It uses the generic Linux ioctl ABI on x86, ARM, and RISC-V
architectures listed by the adapter. Other ioctl ABIs fail with a diagnostic.
Required sysfs fields include per-device `fsid`, available since Linux 5.17;
unavailable fields fail closed. Persisted Device Identity, Volume Identity,
Connection Generation, recovery paths, and journal keys are unchanged.

## Validation

Synthetic topology tests exercise real recovery preflight with single and multiple
members, mapped members, subvolume/bind aliases, sparse IDs, and shared iPod backing
hidden in a second member. Missing, duplicated, unresolved, replacing, seed, and
changing membership fail before recovery writes. Existing loop rejection remains.

Linux Health validation compiles the installed kernel header contract and mounts a
disposable two-member Btrfs filesystem with a subvolume and bind alias. Test-only
fixture setup uses privileges and loop images; application inspection runs as the
ordinary CI user. It verifies actual filesystem queries and sysfs membership,
then confirms that recovery still rejects the loop leaves. Physical Btrfs disks,
encrypted Btrfs installations, and interrupted iPod transactions still need hardware
acceptance; this fixture does not claim that coverage.

References:

- [Btrfs ioctl contracts](https://btrfs.readthedocs.io/en/latest/btrfs-ioctl.html)
- [Btrfs sysfs device membership](https://btrfs.readthedocs.io/en/latest/Administration.html#uuid-devinfo)
- [Linux Btrfs UAPI](https://github.com/torvalds/linux/blob/v6.8/include/uapi/linux/btrfs.h)
- [Linux Btrfs sysfs implementation](https://github.com/torvalds/linux/blob/v6.8/fs/btrfs/sysfs.c)
- [Descriptor mount identity](https://man7.org/linux/man-pages/man5/proc_pid_fdinfo.5.html)
