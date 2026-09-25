# ADR-0063: Scan Host media into common Library Snapshots

- Status: Accepted
- Date: 2026-09-18
- Extends: ADR-0005 and ADR-0019

## Context

Sync needs an in-memory Host Media Library before it can compare source media with
the Active iPod. The user already chooses recursive folders and enabled media types,
but repeatedly reading metadata from every audio, video, Photo, and Playlist file is
too slow for a routine Sync entry point. Playlists can also name files outside the
chosen scope; silently following those references would exceed the user's selection,
while silently dropping them would hide a consequential omission.

The existing common Library API is intended to keep consumers independent of source
formats. Creating a second Host-only model would duplicate Track, Photo, and Playlist
semantics and make later comparison source-aware.

## Decision

Pressing Sync in the media-folder dialog starts a cancellable Host Media Scan on an
owned background worker. It does not start library comparison, planning, copying, or
device mutation. When scanning completes, the application retains an immutable Host
Media Library in memory and reports its contents and cache use.

The scanner uses the Backup capture pattern: enumerate a canonical metadata catalog,
reuse prior work only for entries whose normalized path, media kind, byte size, and
modification time match, inspect new or changed entries, then repeat the metadata-only
enumeration before publishing. A changed tree fails the scan. The bounded,
versioned JSON cache is stored in the application cache location, written atomically,
and protects its canonical entry catalog with SHA-256. Invalid cache data is ignored.
The cache accelerates inspection but is never the authority for the Host Media
Library.

New and changed files are inspected by a bounded pool of at most eight workers.
The pool allows independent `fpcalc` processes and metadata reads to overlap while
the owning scan worker remains responsible for ordered progress publication, cache
updates, and the final tree validation. The in-flight queue is bounded, and every
inspection receives the same cooperative cancellation check.

Cache format v6 (see ADR-0074) uses a strict common file envelope plus a media-kind-specific
metadata object. Audio and video entries retain only Track metadata, Photo entries
retain image dimensions, and Playlist entries retain their title and ordered file
references. Track metadata also retains the raw Chromaprint algorithm-2 fingerprint
that `fpcalc` calculates from at most the first 120 seconds. This bounded form follows
the Original iOpenPod matching behavior and remains available to the later Sync
matcher without rerunning the decoder. This discriminated structure prevents one
media kind from silently accepting another kind's fields. Earlier cache formats are
intentionally rebuilt.

Track inspection also records one bounded, content-derived artwork identity without
placing image bytes in the snapshot or cache. A valid embedded image is authoritative;
otherwise the scanner selects one case-insensitive common folder image in the order
`cover`, `front`, `folder`, `albumart`, `album art`, `album`, then `artwork`, with a
deterministic supported-extension order. The Host source adapter retains the selected
path or embedded-media reference, observed file facts, and SHA-256 digest. Folder
artwork participates in final scan validation and cache reuse, including when Photos
are not enabled for that folder. Explicitly accepted external Playlist files may use
their own embedded artwork but do not authorize reading neighboring folder images.

Audio and video become common `Track` records, images become common `Photo` records,
and supported Playlist documents become common `Playlist` and `PlaylistEntry`
records. The result is an `iPodDB.library.LibrarySnapshot`; source paths, observed
file metadata, warnings, and cache statistics remain in the Host source adapter.
Stable source-derived identities are opaque within the snapshot.

Local Playlist references outside the selected media catalog are collected after the
selected tree passes final validation. The GUI presents one virtualized review table
with per-file choices and Accept All and Deny All actions. Unavailable files cannot
be accepted. Denied files remain outside the snapshot and their Playlist occurrences
are omitted. Accepted supported files are inspected and may participate in Playlist
membership. ADR-0074 further constrains indirect file access through Storage and
includes media-type and recursion exclusions in the review boundary. Network
Playlist references are not followed.

## Consequences

Repeated scans avoid metadata parsing for unchanged files while still noticing file
catalog changes. The Host source and the iPod source expose the same immutable Library
records to later workflows, but source access authority remains separate. Choosing
media folders does not implicitly authorize reading arbitrary Playlist targets.

Path, size, and modification time are the deliberate fast-cache discriminator; this
is not content authentication. The final enumeration rejects ordinary concurrent
tree changes, but a hostile or unusual edit that preserves all discriminator values
is outside this cache's guarantees. Full media capture, compatibility inspection,
Sync comparison, review, and publication remain separate workflows.

An audio or video file that cannot produce an Acoustic Fingerprint remains visible
with a scan issue, but its incomplete cache record is not reused on the next scan.
The scan cannot begin fingerprinting when `fpcalc` is unavailable. Fingerprinting is
cancellable, time-bounded, output-bounded, and never writes tags into source media.
Artwork pixels remain lazy and byte-bounded. The Host artwork loader revalidates the
recorded source facts and digest before downsampling for display; it never modifies
the media file or folder image.
