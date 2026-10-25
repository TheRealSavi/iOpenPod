# ADR-0192: Pin Linux search-only ancestors

- Status: Accepted
- Date: 2026-10-25
- Extends: ADR-0074, ADR-0168, and ADR-0190

## Context and decision

A known readable file can be reached through a directory that grants search
permission without granting permission to list its contents. Storage nevertheless
opened every ancestor with `O_RDONLY`, so Linux rejected otherwise permitted Host
and device reads. The same issue prevented listing a readable directory beneath a
search-only ancestor. Native Ubuntu tests reproduced all four cases while ordinary
file reads succeeded.

Storage uses `O_PATH` for Linux ancestor descriptors, retaining `O_DIRECTORY` and
`O_NOFOLLOW` on every component. `O_DIRECTORY` is required because `O_PATH` with
`O_NOFOLLOW` alone can return a descriptor for a symbolic link. Subsequent opens
remain relative to the pinned descriptors, and every ancestor stays open until the
operation ends. Platforms without `O_PATH` retain their existing `O_RDONLY` behavior;
Windows retains its native handle and sharing policy.

The actual file still opens read-only with no-follow and nonblocking protections.
The directory being enumerated, including the filesystem root, still opens with
`O_RDONLY`: an `O_PATH` descriptor cannot supply a directory listing. File identity,
bounded reads, final named-path validation, Connection Generation, cancellation,
and handle cleanup remain unchanged. Flush handles also retain their existing
readable descriptors; `O_PATH` is not a replacement for a durability handle.

This permits access already allowed by the Host. It grants no new permissions,
changes no user filesystem modes, and requires no elevation or new dependencies.
Missing search permission, unreadable files, and unreadable selected directories
remain errors. udev setup and physical-backing recovery validation are separate.

## Validation

Tests run as an unprivileged Linux process with real temporary-directory modes.
They cover Host streams, device reads and fingerprints, directory enumeration,
denied permissions, ancestor replacement before and after pinning, and descriptor
closure after successful reads or cancellation. A replacement cannot redirect
reads or provisional enumeration to the unapproved tree; final named-path checks
still reject the changed path. Tests restore only their own temporary permissions.

The Health workflow offers a Storage-only run across Linux, Windows, and both macOS
architectures. Its default continues to run the full suite. This keeps native path
validation available independently of GUI test crashes. The permission tests skip
on non-Linux or root runs; synthetic flag checks do not replace native evidence.

See the [Linux open contract](https://man7.org/linux/man-pages/man2/open.2.html)
for `O_PATH`, directory permissions, and descriptor-relative access.
