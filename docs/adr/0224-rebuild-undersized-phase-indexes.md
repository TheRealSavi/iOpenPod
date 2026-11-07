# ADR-0224: Rebuild undersized Phase indexes

- Status: Accepted
- Date: 2026-11-01
- Supersedes: ADR-0209's rejection of existing indexes shorter than 308 bytes.

Creating or designating a Phase Playlist must recover from an empty or undersized
Phase Library. These files cannot contain the required headers, yet previously
blocked preparation with "Unsupported Phase Library size." At the user's request,
Phase preparation treats them as having no reusable index records and builds the
index from the selected Playlist and its generated or verified gameplay charts.

iPodDB reports this specific condition through `IncompletePhaseLibraryError`;
the Application Layer owns the recovery policy. The codec still rejects the
input. Other unsupported layouts, including extended indexes with Unknown Data,
retain their existing rejection behavior.

The Phase Library has no application-imposed byte-size or Track-count cap. The
previous 8 MiB and 100,000-record limits were not evidenced game constraints and
are removed from reading, selection, parsing, and serialization at the user's
request. The declared record count must still match the serialized length, native
integer fields must remain representable, and lossless re-encoding still protects
Unknown Data. Storage continues to verify identity and concurrent modification
while reading the observed file size. Large indexes require proportionate Host
memory; no physical gameplay capacity is claimed by accepting them.

Preparation captures the original fingerprint and leaves the file untouched.
Storage replaces it in the same recoverable transaction as the Library and
Phase companions. Changed inputs still block publication, and transaction recovery
can restore the original bytes. No independent delete or device mutation is added.
Clearing a selected Phase Playlist also replaces an undersized index with a valid
empty index. Saves without a Phase selection change or an existing selection do
not repair unrelated game data.

Virtual Classic 7th gen tests cover creating and converting Playlists, publication,
restoration of empty and 307-byte originals, and rejection of changes after review.
Companion tests cover gameplay chart generation and reuse after rebuilding. Codec
and service tests cover indexes above 100,000 Tracks and 8 MiB. Physical-device
acceptance remains unverified.
