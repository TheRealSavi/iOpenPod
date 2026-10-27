# Firmware playback sidecars

Device selection captures active files under `iPod_Control/iTunes` through Storage
and immediately commits understood playback changes and OTG Playlists before
publishing the Active iPod. No later user save, Draft application, or Sync is needed.
Discovery remains read-only. `IPodLibrary.with_sidecars` is the pure intermediate
step that projects their evidence into the Library Snapshot while
`serialize` continues to reproduce the original database bytes. Replacing the
overlay or changing the Device Time Context always reprojects from the database,
so it cannot add the same plays again.

`iPodDB.sidecars` owns the firmware formats: `models.py` contains the lossless
records, `codec.py` reads and recognizes the files, and `remapping.py` preserves
positional data across Track-table changes. The package has no dependency on
Library types, Storage, or iOpenPod. Every document's `serialize()` returns its
exact input, including Unknown Data. Bounds are validated before iterating records;
truncated records and unexplained tails are rejected. Capture limits are 16 MiB
per file, 64 MiB total, and 256 files.

`iPodDB.library._sidecar_projection` applies parsed evidence to Tracks and Playlists.
The public Library interface re-exports only the captured `PlaybackSidecar` input
and capture/preservation helpers needed by the Application Layer. Format readers
and raw document types are available from `iPodDB.sidecars` itself.

| File | Interpretation |
| --- | --- |
| `Play Counts` | `mhdp` or reversed `pdhm`, a header of at least 96 bytes, and positional rows of at least 12 bytes. Plays, local Mac last-played date, bookmark milliseconds, optional rating, played marker, and optional skip count/date are exposed. Rows may cover a prefix of the Track table. |
| `iTunesStats` | Fully bounded 24-bit records with a 6-byte header or 32-bit records with an 8-byte header. Every record supplies its own length. Plays and bookmarks are projected; newer dates follow the reference reader's Unix-second interpretation. The separate `skipped` value remains diagnostic, not a skip count. |
| `PlayCounts.plist` | XML or binary plist with a `tracks` array. Records match `persistentID` to the Track's persistent database ID, preserving signed or unsigned 64-bit representations. Known counts, bookmark, rating, and local Mac dates are projected. Missing/duplicate IDs and incorrect value types are rejected. Unknown keys remain in the original document. |
| `OTGPlaylistInfo`, `_1`, `_2`, etc. | `mhpo` or reversed `ophm`, a header of at least 20 bytes, and positional rows of at least 4 bytes. Order, duplicates, and row extensions survive. Numbered files are interpreted only when the base file exists. The base alone may be a zero-byte semaphore. |

Binary Play Counts rating zero clears a rating; `0xFFFFFFFF` or an absent field
leaves it unchanged. Plist rating zero is unspecified. A binary Play Counts
bookmark replaces the retained position, including zero to clear it. Stats and
plist retain the existing nonzero-bookmark policy. Plays and skips add to their
respective cumulative totals; plays also add to the existing unscrobbled count.
The total skip field is MHIT `+0x98`; the independent `+0x9c` secondary counter is
preserved. Its reset/consumer contract is unresolved.

Play Counts row byte `+0x11` explicitly sets played state for `1` and clears it
for `2`, independently of the lifetime play count. The reader exposes this raw
byte as `PlaybackEntry.played_marker`; other values and absent markers retain the
Host fallback of prior played state or positive total plays. Likewise, MHIT
`+0xb2` values `1` and `2` are authoritative; other values or a missing field use
the play-count fallback. Preparation and display preserve explicit false state.
These field corrections follow the
[Classic firmware evidence](research/classic201-itunesdb-semantics-2026-10-26.md);
the fallback and unscrobbled count remain Host policies.

Binary Play Counts replaces each present playback date with its supplied value,
including older dates after clock setbacks and zero to clear a date. An absent
optional skipped-date word remains absent (`PlaybackEntry.last_skipped=None`) and
preserves the retained date. No count delta is required for a date update. Stats
and plist keep their previous newest/nonzero policy. The exact binary Play Counts
missing-date sentinel remains an exception, evidenced in Nano 5 captures: the Mac plus Core Data
epoch offsets plus the captured database UTC offset. It contributes no new date
and never clears existing history. Detection precedes geographic timezone
conversion, avoiding a historical DST shift. Other real dates survive even with
zero completed plays. This does not reinterpret plist dates or ordinary Track
dates. See the [capture evidence](research/finder-playcounts-compatibility-2026-10-18.md)
and ADR-0150. Local Mac dates require the captured Device Time Context, never the
Host timezone. Ambiguous dates block consumption of the complete playback input;
valid earlier rows do not contribute partial updates. Nonzero incoming binary
dates that decode to semantic Unix zero also block consumption. So does an explicit
zero clear over a nonzero retained native date already projected as unavailable:
semantic equality cannot express that native clear. Both limitations keep the
original sidecar pending rather than consume an unapplied date change. See
[ADR-0196](adr/0196-adopt-firmware-clock-and-date-evidence.md).

Projection retains skip history even when the source MHIT ends before its fields.
Saving can expand an affected Track using the selected Device Profile's database
capability, while preserving the retained prefix and Unknown Data. Missing or
insufficient capabilities block consumption instead of dropping evidence. See
[ADR-0144](adr/0144-expand-track-headers-with-device-capabilities.md).

OTG Playlists receive distinct temporary Library IDs and deterministic occurrence
IDs. Selection's Library preparation allocates their persistent IDs. The importer
does not merge Playlists merely because their names or contents match. Empty OTG
documents are acknowledged without creating empty Playlists. A zero-byte base is
also consumed and archived verbatim; an empty numbered file or a nonempty malformed
base still fails validation. Orphan numbered files and
`.bak`/`.backup` files never generate duplicate Playlists.

## Selection, saving, and recovery

Selection prepares the projected Library through the same signing, resource,
verification, and Storage pipeline used for ordinary Library saves. It holds the
selection lock until publication finishes and returns the committed Snapshot and
new fingerprints. Preparation requires captured sidecar context; its success
alone does not modify any device file. No user edits are included in this step.
If there are no understood inputs to consume, selection does not save the Library.

The Application Layer binds consumption to its issued Review. Each consumed file
is written verbatim to `<filename>.bak`, then its active input is recoverably
removed after database publication. Backup replacement, Library publication, and
sidecar removal share one verified Storage Transaction. Fingerprint changes,
missing loaded files, and new sidecars stop publication. Interrupted transactions
use the existing device-scoped recovery workflow. A subsequent load reads the
committed totals and Playlists and ignores the inactive archives.

Malformed sidecars remain available on disk and fail selection with a diagnostic;
an uncommitted projected Library is never exposed. Competing playback files
are ambiguous: adding both or consuming just one could double-count history on a
future load. They therefore block reconciliation. Unsupported sidecars are not
consumed; positional changes retain the conservative preservation/remapping policy
from ADR-0085. Read-only devices with understood pending evidence cannot complete
selection. Cleanup or flush warnings after a verified commit do not undo successful
selection; retained journals remain available through the existing cleanup flow.

Restore and Keep Current Contents reload the actual database without projecting
or consuming sidecars, preserving the user's explicit recovery outcome. Their
fingerprints remain available for ordinary save protections. A later normal
selection resumes reconciliation. No physical device files are accessed outside
Storage.

## Evidence and limits

The Original iOpenPod readers (`itunesdb_parser/playcounts.py`, `otg.py`) and its
load/save flow supplied the behavioral baseline. Binary bounds, endian handling,
and the additional formats were checked against libgpod's
[`playcounts_read`, `itunesstats_read`, `playcounts_plist_read`, and `process_OTG_file`](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c).
Implementation uses independent typed Python readers, not a runtime dependency on
either project. The older Original OTG reader's reversed magic typo is not carried
forward. Numeric OTG gaps do not hide later captured Playlists. The newer Stats
reader advances by each record's declared length, unlike the referenced C loop.

The Classic 2.0.1 instruction trace supplies direct evidence for counter and
played/bookmark fields and supports the empty-base semaphore interpretation.
Applying those shared field meanings to other models is an explicit inference,
not a cross-model firmware test. Unknown flags and Shuffle skip semantics remain
unresolved. Authored binary/XML fixtures and virtual devices verify the software;
real-device acceptance of the changed output and Back Sync remain separate work.
Scrobbling now consumes
the committed playback evidence through [its own workflow](scrobbling.md). See
[ADR-0100](adr/0100-reconcile-firmware-playback-sidecars-on-device-selection.md).
