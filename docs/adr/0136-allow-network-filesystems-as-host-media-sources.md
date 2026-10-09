# ADR-0136: Allow network filesystems as Host media sources

- Status: Accepted
- Date: 2026-10-09
- Amends: ADR-0074, ADR-0083, and ADR-0132 for network filesystem inputs

## Context

The Host Media Library may live on a NAS that Windows exposes through an SMB share
or mapped drive. The Original iOpenPod supported this arrangement. V2 rejected
both forms before enumeration: UNC paths failed its spelling validation, and
mapped drives failed its local-drive check.

ADR-0074 restricted untrusted Playlist references and then applied the same
Storage boundary to general Host media access. The resulting network ban extended
too far: it treated a selected filesystem location like an unsupported streaming
URL. ADR-0083 and ADR-0132 retained that restriction. The intended product policy
allows network filesystems as Host media sources.

## Decision

On Windows, ordinary UNC paths such as `\\server\share\Music` and mapped network
drives are supported Host media sources. Explicit selections, directory
enumeration, metadata and artwork reads, and Sync captures use the same Storage
observations and validation as other Host media. Network filesystems mounted at
ordinary POSIX paths retain their existing support. Access uses the Host's mounted
filesystem and credentials; this does not introduce an application SMB client.

Playlist filesystem references may name an ordinary Windows UNC path or mapped
drive, or resolve relative to a Playlist on a network filesystem. The existing
selected-catalog boundary still applies: supported media outside the selected
catalog requires explicit review before inspection. On Windows, file URLs such as
`file://server/share/song.mp3` resolve to the corresponding UNC filesystem path.
This also preserves relative XSPF and ASX references resolved against a network
Playlist's file URL. POSIX Hosts continue to reject remote file authorities;
network media there uses mounted filesystem paths. Non-file URLs, including
streaming and `smb://` URLs, remain rejected. A filesystem reference does not
authorize nested Playlists, indirect symbolic links, or XML entity expansion.

Host media operations opt into network filesystem access. Shared path-validation
and directory-pinning helpers retain a local-only default for installation
operations. Device Paths and device mutation authority are unchanged.

Explicit extended-length or device-namespace path syntax remains rejected,
including named pipes. When an authorized symbolic link returns a native Windows
extended UNC target, Storage normalizes that target to ordinary UNC spelling
before applying the same validation. Alternate data streams, reserved or ambiguous
Windows names, unsupported reparse points, and special files remain unavailable.

Resolution still grants no read authority. Storage retains no-link observations,
pinned reads, file identity and size/time checks, bounded reads, and cancellation
checkpoints. A disconnected share, unreadable source, or changed file is reported
through the existing scan and Sync failure handling; cached metadata cannot grant
access or validate a stale source.

## Consequences

Users can keep their Host Media Library on a NAS without first copying the entire
library to a local drive. Existing per-file capture, preparation, and staging may
still need temporary Host disk space. Network availability and latency affect
scanning and preparation; permitting a share does not promise uninterrupted reads
or equivalent behavior from every server implementation.

Host Media Scan Cache v13 discards cached Playlist interpretations when migrating
versions 9 through 12, while retaining reusable Track and Photo records. Unchanged
Playlists are parsed once again after upgrading so newly allowed network
references appear without requiring a user to edit the Playlist. The normal
source-fact and artwork checks still determine whether retained media can be
reused.

Regression coverage must include UNC and mapped-drive selection, enumeration,
reads and captures, relative and absolute filesystem Playlist references,
Windows UNC file URLs, authorized symbolic-link targets, and Playlist cache
migration without unrelated media rereads. It must retain
rejection of unsupported URLs, device namespaces and unsafe path components,
source-change checks, and the installation boundary. Native SMB validation remains necessary for server-specific
identity and file-sharing behavior.
