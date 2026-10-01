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
| `Play Counts` | `mhdp` or reversed `pdhm`, a header of at least 96 bytes, and positional rows of at least 12 bytes. Plays, local Mac last-played date, bookmark milliseconds, optional rating, and optional skip count/date are exposed. Rows may cover a prefix of the Track table. |
| `iTunesStats` | Fully bounded 24-bit records with a 6-byte header or 32-bit records with an 8-byte header. Every record supplies its own length. Plays and bookmarks are projected; newer dates follow the reference reader's Unix-second interpretation. The separate `skipped` value remains diagnostic, not a skip count. |
| `PlayCounts.plist` | XML or binary plist with a `tracks` array. Records match `persistentID` to the Track's persistent database ID, preserving signed or unsigned 64-bit representations. Known counts, bookmark, rating, and local Mac dates are projected. Missing/duplicate IDs and incorrect value types are rejected. Unknown keys remain in the original document. |
| `OTGPlaylistInfo`, `_1`, `_2`, etc. | `mhpo` or reversed `ophm`, a header of at least 20 bytes, and positional rows of at least 4 bytes. Order, duplicates, and row extensions survive. Numbered files are interpreted only when the base file exists. |

Binary Play Counts rating zero clears a rating; `0xFFFFFFFF` or an absent field
leaves it unchanged. Plist rating zero is unspecified. Only nonzero bookmarks
replace retained positions. Plays and skips add to their respective cumulative
totals; plays also add to the existing unscrobbled count and mark the Track played.
Nonzero dates use the newer observed value. Local Mac dates require the captured
Device Time Context, never the Host timezone. Ambiguous dates block consumption.

OTG Playlists receive distinct temporary Library IDs and deterministic occurrence
IDs. Selection's Library preparation allocates their persistent IDs. The importer
does not merge Playlists merely because their names or contents match. Empty OTG
files are acknowledged without creating empty Playlists. Orphan numbered files and
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
[`playcounts_read`, `itunesstats_read`, `playcounts_plist_read`, and `process_OTG_file`](https://github.com/gtkpod/libgpod/blob/master/src/itdb_itunesdb.c).
Implementation uses independent typed Python readers, not a runtime dependency on
either project. The older Original OTG reader's reversed magic typo is not carried
forward. Numeric OTG gaps do not hide later captured Playlists. The newer Stats
reader advances by each record's declared length, unlike the referenced C loop.

Unknown flags, Shuffle skip semantics, and physical firmware behavior are not
inferred. Authored binary/XML fixtures and virtual devices verify the software;
real-device acceptance, Back Sync, and scrobbling remain separate work. See
[ADR-0100](adr/0100-reconcile-firmware-playback-sidecars-on-device-selection.md).
