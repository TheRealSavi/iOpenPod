# ADR-0250: Prefer device write policy over source signature markers

- Status: Accepted
- Date: 2026-11-09
- Amends: ADR-0021

A fifth-generation iPod can contain an iTunesDB whose hashing-scheme marker
conflicts with its unsigned device write policy. Treating that marker as a signing
requirement blocked selection when pending playback sidecars needed committing.

The explicit Write Target, composed from the selected Device Profile, owns the
output signature scheme. A conflicting or unknown retained marker produces a log
warning during changed iTunesDB preparation rather than a blocking Write Issue.
Unsigned targets publish scheme zero; signed targets use their existing signers
and verification. Required signing identities and material remain mandatory.
Retained signature bytes on unsigned targets remain Unknown Data. Shared Chunk
definitions continue to own field layout; no new positional format knowledge is
introduced.

Playback history and On-The-Go Playlists follow the normal preparation,
verification, transaction, and archive workflow. This changes no sidecar error or
recovery policy. Pure serialization and unchanged preparation retain the source
bytes exactly, including a conflicting marker. Authored virtual-device tests
cover Video 5/5.5 selection, history and Playlist publication, later edits, and
reload without duplicate playback application; physical device acceptance remains
separate.
