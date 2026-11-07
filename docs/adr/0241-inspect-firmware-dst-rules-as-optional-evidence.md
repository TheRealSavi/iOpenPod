# ADR-0241: Inspect Firmware DST Rules as optional evidence

- Status: Accepted
- Date: 2026-11-06
- Complements: ADR-0097, ADR-0196 and ADR-0240
- Qualification extended by: [ADR-0242](0242-qualify-the-latest-classic-calendar-targets.md), enabling observed updater-35/38 targets and documenting updater 24 separately

## Context

Static inspection of seven retained firmware images found different custom DST
file framing and transition selectors between Classic 2.0.1 and 2.0.4/2.0.5.
The verified Classic consumers read 205 ordered rows, accept nonzero enabled
bytes, and distinguish duplicate city rows by their position. Short reads can
succeed without establishing the remaining buffer contents. The later files
have an opaque two-byte prefix. See the
[format and identity research](../research/firmware-dst-data-and-city-identity-2026-11-06.md).

Firmware Calendar, Saved DST State, clock correction and the automatic predicate
cache are distinct observations. Annual rows contain no historical year ranges
or timezone offsets. They cannot reconstruct past clock settings or identify an
exact UTC instant in a repeated hour. The raw clock's time basis remains unknown;
see the [clock investigation](../research/clock-adjustments-and-date-comparisons-2026-11-06.md).

## Decision

Add a read-only `DSTTableDocument` to the public `iPodDB.preferences` contract.
Shared `BinaryStruct` fields own the row layout. Parsing requires an explicit
`DSTTableProfile`; the default is opaque even at a recognized length. The three
qualified profiles identify Classic 120GB 2.0.1, updater family 35 / 2.0.4, and
updater family 38 / 2.0.5. The latter identities do not imply a verified SKU map.

Retain source bytes, the opaque prefix, complete ordered rows, unused bytes,
partial suffixes and trailing data. Never pad missing rows, merge built-in rules,
or collapse duplicate cities. City zero is an ordinary row key. Full caller city
IDs are compared without narrowing. Model nominal transition selectors separately
from actual calculated dates: 2.0.1 uses week 4 for last; the later profiles use
4 for fourth and 5 for last. Unexpected values remain observations with diagnostics.

`serialize()` returns captured bytes only. There is no edit writer, device clock
setter, built-in firmware payload or runtime dependency on the research lab.

The Application Layer reads optional `iPod_Control/Device/dst` through Storage,
with the same size bound and stable-read check as Preferences. Automatic typed
qualification currently requires the existing Classic 120GB 2.0.1 device and
RetailOS evidence. It is independent of whether the main Preferences file parses.
Other device identities retain the file opaquely until qualification is justified.
Missing files add no display section. Present files have a read-only settings
summary; unavailable or incomplete observations cannot prevent Library loading,
playback reconciliation or saving. Disconnects still invalidate the session.

Keep ADR-0240's historical city/fixed-offset/UTC estimate policy. Saved rules never
alter Device Time Context or become publication preconditions. A file capture is
not proof that the running firmware currently uses that buffer. Keep ADR-0196's
Host rolling-period Smart preview policy; native calendar comparisons remain
separately documented research, not an unannounced cross-generation behavior change.

## Consequences and validation

Diagnostics can expose saved DST evidence without claiming exact clock history.
The parser supports explicitly qualified later Classic files, while application
auto-qualification remains narrower. Physical firmware acceptance and transport
identity mapping require further evidence.

Authored fixtures cover all three profiles, byte preservation, arbitrary prefixes,
short reads, trailing data, duplicate order, city width, week semantics and unusual
values. Virtual devices cover read-only inspection, unknown identity, optional-file
failure, playback commit, changes after preparation, and disconnect invalidation.
GUI checks cover selectable summaries without edit controls. Research checks are
static instruction verification and bounded reconstructions, not ARM execution.
