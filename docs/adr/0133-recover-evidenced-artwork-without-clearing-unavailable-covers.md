# ADR-0133: Recover evidenced artwork without clearing unavailable covers

- Status: Accepted
- Date: 2026-10-08
- Amends: ADR-0021, ADR-0033, ADR-0111, ADR-0116, ADR-0123 and ADR-0124
- Extends: ADR-0119, ADR-0120, ADR-0125 and ADR-0131

## Context

A report of artwork disappearing after Sync prompted a complete lifecycle audit.
Reproductions showed folder-cover read failures being interpreted as removal and
media replacement clearing covers despite unchanged reviewed artwork intent.
Another reproduction showed complete MHII records hidden by an incorrect MHLI
count. The user's request explicitly includes automatic repair, not only refusal
or cover deferral. The [research](../research/artwork-sync-loss-2026-10-08.md)
distinguishes corroborated format rules from assumptions and hardware reports.

Existing strict parsing and unchanged serialization must retain their lossless
contract. Recovery must not turn arbitrary unknown bytes into guessed records,
overwrite recoverable pixels, or depend on optional Backup Snapshots.

## Decision

Host artwork observations distinguish absence from unavailability. Failed reads,
invalid embedded or folder images and incomplete folder observations cannot
request cover removal. Valid alternate embedded and folder covers remain usable.
The Host cache persists embedded availability and rechecks older no-cover records
that lacked this distinction. Successful metadata remains reusable even when
artwork cannot be inspected. Changed or retried source observations can update the cover. Media
replacement and embedded-artwork updates honor the reviewed artwork-change flag.

iPodDB provides an explicit, byte-only ArtworkDB recovery operation. It corrects
an MHLI count only when a contiguous sequence of complete MHII records exactly
fills the enclosing image dataset. Registered definitions establish boundaries,
and the ordinary parser validates the recovered records and complete candidate.
It does not search for markers, infer new lengths, borrow from adjacent datasets,
or interpret opaque dataset tails. Only the proved count word changes.

`IPodLibrary.with_artwork` uses that recovered view to expose surviving covers,
while `serialize()` returns the exact original source. Typed repair evidence
becomes an explicit ArtworkDB-only change in preparation. A repair-only Sync is
reviewable and available even without media changes. It publishes through the
ordinary fingerprint-checked Storage Transaction. When no other changes require
them, iTunesDB, SQLite and iTHMB files remain unchanged. Verification compares
against independently patched original bytes, not another serialization of the
candidate. Unsupported signature requirements still apply.

A malformed format ID in one bounded MHNI omits only that display location. Its
MHII identity and full original record remain; independent covers stay available.
This does not authorize discarding or arbitrarily replacing unknown representations.

Retained fixed-size rasters use the primary MHNI size. A zero secondary size means
the allocation was not separately recorded, as in libgpod and ipod-sharp. A
nonzero secondary size describes allocation, which may include padding, as in
foo_dop. Allocation must be at least the validated raster length, fit the captured
file and satisfy overlap checks. F1061 retains its two known raster heights and
existing output-layout selection; padding does not invent another raster layout.
Retained sizes and pixels are not normalized merely to match newly encoded art.

Fresh supplied artwork can replace a damaged image when no desired Track still
references that image. Missing or truncated thumbnail allocations then cease to
be layout evidence for that superseded image. Healthy retained images still
constrain the output layout. New images go into usable shards or fresh filenames;
damaged or unreadable shards are reserved against writes, including filenames in
typed representations omitted from the display index. Old image records and any
surviving bytes remain. The independent verifier enforces these reservations.
Later edits also exclude a physically damaged orphan from layout evidence when
it has no original or desired Track association and no reverse owner. This keeps
retained repair evidence from obstructing every subsequent artwork write.

An ordinary read failure during resource capture can permit regeneration only
when every originally covered surviving Track explicitly receives a supplied
replacement asset. Reserved names convey no invented content or fingerprint and
grant no overwrite authority. Cancellation and disconnected Filesystem Sessions
still stop capture. A remaining owner of damaged artwork prevents this recovery
from silently publishing broken retained associations.

New single-cover assignments write MHIT artwork count one, independently of the
number of generated device representations. Existing source-image counts are not
globally rewritten. A valid explicit Track artwork link takes precedence over a
stale reverse owner; missing explicit links can still resolve a retained legacy
owner. This projection also supplies SQLite artwork associations.

## Consequences

Evidenced structural damage is repaired rather than merely warning or withholding
new covers. Original bytes remain available until the verified publication commits;
cancellation or source changes do not publish repairs. Repair is idempotent and
does not introduce filesystem access into iPodDB or a second generic parser.

Unknown trailing bytes, malformed record extents, ambiguous identities and missing
source pixels are not evidence for invented contents. Synthetic tests and local
capture round trips establish software behavior; they do not establish the cause
of the reported incident or universal physical-firmware compatibility.
