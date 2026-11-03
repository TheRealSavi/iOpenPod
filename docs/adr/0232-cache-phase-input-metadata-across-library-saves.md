# ADR-0232: Cache Phase input metadata across Library saves

- Status: Accepted
- Date: 2026-11-03
- Supersedes: ADR-0210 and ADR-0231's full audio checks for unchanged chart reuse
- Extends: ADR-0227's bounded capture path for inputs needing analysis

Creating an unrelated Playlist caused a minute-long pass over 96 Phase Tracks.
Avoiding captures still streamed all audio and retained it as a transaction
dependency, causing further full reads during validation and publication. Ordinary
Library edits must instead reuse already published Phase charts incrementally.

## Decision

Keep the existing content provenance file and add the versioned, bounded
`iPod_Control/iOpenPod/phase-validation-v1.json` metadata cache. Each per-Track
record binds the exact provenance string to the audio Device Path and its observed
size, modification time, device number and inode, plus the chart path and identity.
Both cache files publish with the Phase Library and changed charts in the same
recoverable Storage Transaction. Missing, damaged or unsupported metadata receipts
fall back to full content verification. Older applications can continue reading
the existing provenance; changes to that provenance invalidate the new receipts.

Preparation compares analyzer identity, Track duration, final persistent IDs,
paths and file metadata. It excludes any input with an incoming media write from
metadata reuse. Unchanged inputs cause no audio reads, captures, model work or
chart-content reads. New chart receipts initially omit chart identity because
publication assigns it. The next save verifies only that small chart against its
content provenance and records the published identity. Incoming media similarly
receives its final device identity through content validation on the next save.
Legacy provenance therefore needs one content-validation pass to populate receipts;
matching charts survive this migration without musical reanalysis.

Only Tracks requiring content verification or analysis enter the bounded input
queue and analysis progress/ETA. Metadata-only changes, unrelated Playlists and
Phase Playlist names do not alter chart inputs. Membership, selection and ordering
rebuild the companion index using retained records; only changed index bytes are
published. Removed entries are pruned from both caches without deleting old charts.
Already validated charts from the preferred provider remain reusable if another
Track falls back to acoustic analysis during the same preparation.

## Verification policy

Retained audio and charts that are reused through matching metadata are not
transaction content dependencies. They are not being rewritten. Keeping those
dependencies would turn an unrelated edit back into a full media scan. New or
changed analysis retains full source verification and transaction preconditions;
incoming media retains its existing verified publication. The index, provenance
and receipt files remain content-checked transaction inputs.

This explicitly adopts ordinary filesystem metadata cache semantics. External
edits that preserve every recorded identity field, including size and modification
time, are not detected by routine reuse. A missing/invalid receipt restores full
content checking. It is not a background integrity scan. Cache reads use the
current identity-bound Filesystem Session; no session or absolute Host path is
persisted or reused across disconnection. A changed filesystem identity causes
revalidation. No Storage verification rule is weakened for files being mutated.

## Evidence

The unrelated-Playlist regression initially failed with two full audio hashes and
now passes with zero. Virtual-device tests cover settled reuse after reconnect,
renaming, reorder/removal/reselection, incoming replacements, changed content,
duration and provider invalidation, damaged receipts, and full verification for
newly generated charts. Index-only transactions perform no retained-media hashes.

Three read-only runs against the connected 96-Track device, with populated receipts
simulated in memory, take 0.1796, 0.1780 and 0.1787 seconds. Each performs four small
file reads, 192 metadata checks, zero audio/chart-content reads and zero writes.
The private harness and raw results are under `.scratch/phase-cache/`. This measures
warm-cache preparation through actual Storage; it excludes initial migration,
whole-Library save time, cold filesystem-cache behavior and physical gameplay.
