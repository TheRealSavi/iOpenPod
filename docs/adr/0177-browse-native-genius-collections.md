# ADR-0177: Browse native Genius collections

- Status: Accepted
- Date: 2026-10-24
- Extends: ADR-0020 and ADR-0176
- Extended by: ADR-0186 permits structural membership and seed repair after Track deletion.

## Context

The format work in ADR-0176 did not expose nano Genius Mixes or saved sidecar
Playlists in iOpenPod. A fresh Classic 6.5G capture also shows its saved Airbag
Playlist as a canonical MHYP containing Smart MHODs and an MHOD 54 seed record.
Classifying any Playlist with Smart MHODs as Smart therefore misrepresents native
Genius behavior. The exact eight-byte MHOD 54 body matches the seed persistent
Track ID from the firmware-generated saved plist, not its Genius ID.

## Decision

Model the evidenced MHOD 54 seed field through the shared definition contract.
Its presence classifies the native record as `PlaylistKind.GENIUS` before the
ordinary Smart test. Unrecognized body lengths remain opaque and retain Genius
classification, preventing accidental Smart evaluation. Existing native Smart
records remain retained; this classification does not reinterpret them as rules
the application can evaluate.

Expose an immutable Genius Browse beside the semantic Library in Active iPod
state. iPodDB projects canonical Genius Playlists, saved Genius Playlist sidecars,
and SQLite kind-32 Mixes into named collections referencing existing semantic
Tracks. Preserve ordered repeated Playlist occurrences. Mix members are possible
starting Tracks and do not claim to be the firmware playback queue. Matching
native Playlist identities deduplicate the saved/native representations.

The application captures the optional SQLite Library bytes through Storage and
verifies the capture against the same selected session. Missing or malformed
optional sources do not replace or prevent loading the primary Library; localized
collection failures appear as browse diagnostics. iTunesCDB remains authoritative
for semantic Track facts. Refresh browsing state after selection and successful
publication, and clear it on disconnect or source changes.

A dedicated Genius page separates saved Playlists from Mixes and displays their
Tracks. It supports explicit playback of selected Tracks without pretending to
generate a native Mix on the Host. Canonical Genius Playlists stay in the retained
Library for lossless preparation, but are hidden from the ordinary Playlist tree
and excluded from ordinary creation, editing, moving, and Smart refresh. Sidecars
remain unconsumed. Browsing performs no device mutation.

## Consequences

This adds presentation of already-supported firmware data without introducing a
recommendation engine, a second editable Library authority, or Genius editing UI.
Unknown and malformed source data remains retained. Firmware-specific creation
and refresh workflows remain separate work. Tests use synthetic fixtures; private
Classic and nano captures provide format and end-to-end browse evidence.
