# ADR-0195: Adopt firmware database field semantics

- Status: Accepted
- Date: 2026-10-26
- Amends: ADR-0100 playback projection and ADR-0144's skip-field boundary
- Retains: ADR-0008's shared definitions and lossless preservation;
  ADR-0035/0142's Smart Playlist Host evaluation policies
- Amended by: [ADR-0196](0196-adopt-firmware-clock-and-date-evidence.md) for binary date replacement after clock changes

## Context

Instruction-checked Classic 120 GB RetailOS 2.0.1 contradicts inherited field
labels in Original iOpenPod and libgpod. The Track importer, skip event, sidecar
reader/writer, and counter consumers agree that MHIT `+0x98` holds total skips;
`+0x9c` is a separately incremented counter. The existing application called the
former a Genius category and updated the latter when consuming skip deltas.
Playlist MHYP `+0x28` controls a repeat override in this firmware, while text edits
treated it as a string count. Byte-exact unchanged round trips could not expose
either semantic error.

The [research report](../research/classic201-itunesdb-semantics-2026-10-26.md)
records the firmware hash, runtime addresses, reference comparison, and remaining
uncertainty. These are direct static observations of one release. They outweigh
inherited names, but do not establish execution results on other iPods.

## Decision

Adopt the evidenced counter mapping in the shared Chunk definitions without a
model/version gate. This is an explicit cross-model inference; no database-version
cutoff is established by the evidence. Common `TrackMetadata.skip_count` maps to
MHIT `+0x98`; `IPodTrackDetails.secondary_skip_count` exposes retained `+0x9c`.
Remove the unsupported Genius-category name. Skip edits and Play Counts deltas
change the total and preserve the secondary word. Do not name the secondary
counter unscrobbled, reset it, or derive it from the total. A total of 7, secondary
of 11, and sidecar delta of 2 prepares 9 and 11. A 156-byte MHIT can hold the total
but cannot hold the secondary counter or last-skipped date.

Retain MHYP `+0x28` as the raw u16 `unk_mhyp_0x28`. Every retained value survives
Playlist text edits, independently in each dataset copy, including unknown values
and zero. New Playlists explicitly default to 1 regardless of string count,
matching the established one-title/Master authoring baseline. In the inspected
firmware 1 means repeat off; it is not a neutral override. Do not expose a global
repeat enum or UI until its broader contract is established. Actual MHOD child
counts continue to come from the shared codec's child counting.

For binary Play Counts, zero bookmarks clear previous positions and row byte
`+0x11` values 1/2 explicitly set/clear played state. Preserve this independently
of lifetime plays through preparation and the Track display. MHIT `+0xb2` values
1/2 are authoritative when present. Unknown/absent markers retain the existing
Host play-count fallback; short headers continue to require an adequate capability
when their count alone cannot represent an intended played state. Stats/plist
bookmark policy, newest-date policy, Finder missing-date handling, and Host
unscrobbled-play accounting remain unchanged.

Header expansion must account for required field presence as well as nondefault
values: storing marker 2 can be necessary even though 2 is the schema default,
because absence instead derives played state from the count. Native verification
derives this requirement independently from the requested state. A changed count
may likewise require an explicit marker when the retained byte is unknown;
unrelated edits and no-ops preserve that byte.

Accept a zero-byte `OTGPlaylistInfo` base as a semaphore, activate valid numbered
files in numeric order, and create no Playlist for the marker itself. This follows
the firmware recreate path and the already established base-file activation
contract. Numbered files still require valid framing, as does a nonempty base.
Archive every consumed input verbatim through the existing Storage Transaction;
preserve occurrence order and duplicates and reject malformed active inputs.

Keep Smart Playlist Host evaluation explicit: saved reference membership,
folder-descendant unions, deterministic preview, cycle handling, oversized-candidate
skipping, and existing date/string rules are not silently replaced with one
firmware's runtime evaluator. Corrected common skip metadata reaches its existing
rules and sorts. The report records remaining differences for subsequent work.
Retain Storage verification and recovery even where inspected firmware ignores
write/close failures.

## Consequences and validation

The parser and writer still use one set of offsets. Unchanged inputs remain
byte-exact, including Unknown Data; this introduces no firmware or Original
iOpenPod runtime dependency. Existing miswritten secondary counters are preserved,
not guessed back into historical totals. New reconciliation uses the corrected
word, so old mistakes are not propagated by adding future deltas to it.

Independent literal-offset fixtures cover skip edits, delta merges, short-header
boundaries, and preservation. Playlist fixtures cover both dataset copies,
unknown values, text additions/removals, no-ops, and partial fields. Sidecar tests
cover played state with zero/positive totals, bookmark clearing, malformed OTG
files, and lossless readers. Virtual-device selection verifies empty-base archives,
numbered Playlist publication, and reselect idempotence. Physical acceptance of
these changed outputs and other firmware versions remains untested.
