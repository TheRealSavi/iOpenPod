# ADR-0138: Edit artwork by display time

- Status: Accepted
- Date: 2026-10-11
- Extends: ADR-0012, ADR-0019, ADR-0021, and ADR-0033
- Extended by: ADR-0139 for chapter formats and authored artwork counts
- Extended by: ADR-0202 for raw key naming, native Chapter diagnostics and explicit flags
- UI superseded by: ADR-0204 for Chapter-based selection and Host playback preview

## Context

The Artwork Index discarded MHNI offset `0x24`, while the writer treated every
repeated format ID as a duplicate. The Metadata Editor consequently exposed only
one cover. Controlled Video 5G firmware 1.3 emulator experiments demonstrate
playback-time selection, order-sensitive refresh, and different representations
within each time group. The evidence does not establish every device or firmware's
playback behavior. See [the timing investigation](../research/ithmb/artwork-timing-experiments.md).

## Decision

An Artwork Display Time is an unsigned millisecond position associated with the
representations of one image within an ArtworkDB image item. iPodDB projects this
value and exposes a metadata-only list of display times and an exact-group read
selector. Ordinary cover requests retain their default-cover behavior. Application
requests and caches distinguish the requested time as well as the artwork identity
and resolution. The GUI never inspects Chunks or reads device paths directly.

`TimedArtworkAsset` describes an explicitly edited complete sequence. Each
`TimedArtworkFrame` supplies pixels or an `ArtworkGroupReference` to a retained
source group. Retained references preserve original representations and Unknown
Data without decoding and re-encoding unaffected images. Newly authored sequences
have unique times, a zero-time entry, and every target cover representation for
each new image. Preparation emits groups in ascending time order and verifies
their times, formats, and image ranges before normal transactional publication.

The existing `ArtworkAsset` remains the ordinary cover-edit contract. Replacing a
cover updates time zero while preserving retained later groups. An explicit
timeline edit controls removal or retiming; clearing artwork removes the Track's
entire relationship. This prevents routine cover refreshes from silently erasing
timed images. Source references do not authorize regeneration of unreadable
retained shards as though every frame supplied fresh pixels.

Existing special value `0xFFFFFFFF` is retained and can be inspected; the editor
does not invent new images or timing semantics for that value. Unedited databases
remain byte-exact. The raw Chunk field name and binary layout, Device Registry
pixel-format definitions, and shard cap remain unchanged.

The Artwork tab lets users select, preview, add, replace, retime, and remove images
by display time. Changes remain in the revision-checked Library Draft until the
existing review and save workflow succeeds. Mixed Track selections require an
explicit shared artwork choice. Playback support is described as dependent on the
iPod and firmware; authoring does not manufacture a universal Device Profile
capability from the emulator observation.

## Consequences

Timed artwork becomes usable without adding chapter metadata or decoding all
images when opening a Library. Existing Sync and ordinary cover callers keep their
small interface, while timeline edits carry explicit preservation references.
Tests must cover time-specific reads and caches, sorted complete output, retained
bytes, draft cancellation and validation, and save/reload. Software verification
does not replace physical-device testing or settle reverse-seek behavior.

## Subsequent compatibility evidence

On 2026-10-11, a user reported that a 15-second image did not replace the cover on
a physical Classic 6.5G. [Read-only inspection](../research/ithmb/classic-timed-artwork-readback.md)
found ordered zero/15,000-ms groups with distinct payloads and valid ranges. The
writer supplied the existing Classic cover formats, as this decision specifies.
[Historical producers](../research/ithmb/artwork-count-and-classic-timing.md)
distinguish chapter formats from cover formats; their Classic chapter set includes
F1029, which this writer does not supply for that profile. This is an unresolved
compatibility gap, not proof that adding F1029 fixes playback. The source evidence
and successful Video experiment both permit MHIT `artwork_count = 1`.

Neither successful serialization nor the Video experiment establishes Classic
playback support. [ADR-0139](0139-complete-timed-artwork-formats-and-counts.md)
records the subsequent user-requested chapter-format and count policy for another
device test; it does not establish a successful firmware fix.
