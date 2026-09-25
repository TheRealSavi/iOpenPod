# ADR-0065: Index iPod media for Sync correlation

- Status: Accepted
- Date: 2026-09-18
- Extends: ADR-0005, ADR-0011, ADR-0029, and ADR-0063

## Context

The Host Media Scan produces matching evidence before Sync planning, but the iPod
side also needs content identities. Recalculating every iPod fingerprint on every
Sync would repeatedly read removable media and decode unchanged Tracks. The Original
iOpenPod used an on-device mapping between Acoustic Fingerprints and persistent Track
IDs; iOpenPod 2.0 needs the same behavioral advantage without treating that mapping
as Library authority or exposing a Mount Point to the Application Layer.

The correlation record must also retain facts established by a successful Sync, such
as its time and the Host file's size and modification time at that point. Existing
media discovered on an iPod has no proven Sync history, so the scan must not invent
those facts. A damaged helper may contain the only surviving Sync provenance and
must not be silently replaced.

## Decision

After a completed Host Media Scan, the pre-Sync workflow scans the Active iPod's
Library files. It stores a versioned, checksummed
`iPod_Control/iOpenPod/library-sync-helper.json` document that maps persistent iPod
database Track IDs and Photo image IDs to matching evidence and optional Sync
Details. The helper is an Application-owned optimization, not iTunesDB, ArtworkDB,
PhotosDB, or filesystem authority.

Each Track entry retains its persistent database Track ID, current Track ID,
validated Device Path, size, modification time, bounded raw Chromaprint algorithm-2
fingerprint, and optional Sync Details. Each Photo entry uses the Photo ID and the
SHA-256 content fingerprint of its retained full-resolution file. A Photo without a
full-resolution file remains visible in the iPod Library but reports that no exact
image fingerprint could be established. Future artwork matching may add a distinct
decoded-image identity; it must not pretend an iTHMB representation is byte-identical
to its Host source.

A helper fingerprint is reused only when the current Library identity, Device Path,
size, and filesystem-aware modification time match its entry. Missing or stale
entries alone are fingerprinted. Track decoding runs against a verified temporary
Host snapshot copied through Storage; the Application Layer never receives a Mount
Point. Image hashing runs through Storage. The iTunesDB or iTunesCDB fingerprint is
checked before publication, and the helper is atomically created or replaced using
the exact prior helper fingerprint as its precondition.

The scan writes no `last_synced_at` value for discovered media. Sync Details are
created or refreshed only after a successful Sync commit and include the Host path
hint, Host size and modification time, source and device formats, and whether the
media was transcoded. If a device file changes but recalculates to the same content
identity, its prior Sync Details may be retained. Invalid helper data is reported and
left unchanged rather than rebuilt automatically.

Host Media Scan cache format v4 adds a SHA-256 content fingerprint to each Host
Photo. Track Acoustic Fingerprints and Photo content fingerprints remain
source-specific matching evidence outside the common Library Snapshot.

## Consequences

Routine pre-Sync scans avoid rereading and decoding unchanged iPod media. A first
scan, a changed device file, or a missing helper entry still incurs the necessary
device read. The helper makes Host-to-iPod correlation fast without allowing cached
state to authorize deletion or mutation.

Filesystem metadata is a deliberate fast-cache discriminator, not hostile-change
detection. Final Sync planning and execution must still validate their captured
Library and file dependencies. Read-only iPods can be scanned in memory, but new
fingerprints cannot be reused on the next run until the helper can be safely written.

Exact SHA-256 Photo matching covers retained full-resolution copies. Correlating
resized or re-encoded Photos and cover artwork requires a separately specified image
identity and is not inferred from an iTHMB file hash.
