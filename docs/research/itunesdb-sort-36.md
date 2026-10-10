# iTunesDB MHOD 52 sort type 36

## Scope and location

Sort type 36 (`0x24`) is the `sort_type` value at offset `0x18` of an MHOD
type-52 Library index under a Master Playlist (MHYP) in playlist datasets 2/3.
The following entries are zero-based **Master Playlist occurrence positions**.
They are not MHIT-table positions, Track IDs, or the playlist's `sort_order`.

This investigation addresses that index only. It does not change album/artist
equivalence policy or implement other database families.

## Evidence

The investigation used local captured bytes, not another writer's output as a
correctness oracle. Original iOpenPod and earlier research supplied hypotheses.
The user reports that most captures were produced by iTunes; individual files'
last writers are not independently established.

| Capture | SHA-256 | Tracks | Contiguous album groups in sort 36 |
| --- | --- | ---: | ---: |
| Historical `20mb_iTunesDB` | `c242701f0da0893b61d9d9605d6c3782d61d983fac759a6d400df23be732ef8b` | 6541 | 1059 |
| Classic A | `1e1abac446e120cfceb70986e12109dc1c71e35304e3bdeac94cefece727d284` | 5630 | 482 |
| Classic A, revision 2 | `b0008450fbc823a87fdcc9ed6bbb2507031405158a7e1db7e94367844dad4457` | 5641 | 483 |
| Classic A, revision 3 | `5348897d2b77498f04169529eeafa6cf1030129d6accac7ddf4d7ad7e3c7c6da` | 5630 | 482 |
| iPod third generation | `de80d81f5278016a1968156de70087889dfd2eab307c20b3d4cd855c28d40f84` | 193 | 91 |
| Nano first generation | `9b5614404f8be6fd71fac23baccc4a9eb7ae16e1d2fba432731b70009f5e1fe1` | 184 | 91 |
| Photo | `06b2968824d81457311c6c9ed9545c0680c6e762490b38025e2dd86b24ed146f` | 191 | 93 |
| Reported failure supplied 2026-10-08 | `99826cf0c63e449ccc4cc2675ccb4c3a0baa0fb40f3d12f71ac2b891ba86e95a` | 687 | 160 |
| Separate user's failure supplied 2026-10-09 | `abe7d177a326cb0b569d08f998be62a521cd87468eff614d0435650986eb65f3` | 569 | 52 |

The historical database is from a different iPod than the connected-device capture.
It was used alone, without that device's ArtworkDB or media. Three other captured
databases contain empty sort-36 indexes. Related revisions of one Library are not
independent evidence of additional firmware support.

The earlier investigation incorrectly indexed the MHIT table. In the historical
capture, 6407 of 6541 Master Playlist positions differ from that table. Conclusions
drawn from those incorrect Track pairs, including the previous raw-artist versus
Sort Artist comparison, are withdrawn.

## Observed structure and implemented policy

Every populated capture keeps each native album together in this index. Artist
names on individual Tracks may differ within those groups. Treating type 36 as
another ordinary per-Track artist sort does not explain the captured sequence.

For the historical source, all 1059 album groups are consistent with sorting by
the representative Track's effective Album Artist and effective Album sort values.
The representative is supplied by the album record's persistent Track reference.
Effective Album Artist uses Sort Album Artist, Album Artist, Sort Artist, then
Artist; effective Album uses Sort Album, then Album. The representative's values
matter when Tracks in one album disagree on their album sort override. Choosing
the first Track in the MHIT table introduces an ordering inversion in this source.
The samples do not distinguish every possible representative-selection algorithm.
The implementation uses the retained native reference; where it is absent, it uses
the first member by disc/track ordering. Invalid nonzero references block rebuilding.

Disc and track numbers explain every strict within-album comparison in the
examined captures when missing disc numbers follow numbered discs. Titles are not
a reliable tie-breaker: the historical capture has seven albums whose tied members
do not follow Master Playlist order, and thirteen that do not follow a title sort.
Existing tie order is retained explicitly. New tied members follow existing ones
in their submitted order. Missing track numbers are also placed last; the corpus
does not independently distinguish that case from all other missing-number rules.

The captures disagree on punctuation comparisons even where MHBD platform and
language values match. The implementation does not infer collation from the Host
OS or equate an implementation comment with a format rule. Unchanged group sort
values keep their captured order, including when Tracks are added to an existing
album or removed. Rebuilding group order first checks the complete source group
sequence against the supported observed comparison profiles: punctuation retained,
artist hyphens ignored, or punctuation ignored. The profiles fold case/diacritics,
normalize curly apostrophes, and place numeric names after letter names. Empty
artists sort after named artists.

The 2026-10-08 capture distinguishes additional rules that the earlier reduced
fixture did not exercise. Its profile retains a leading `The` in explicit sort
overrides, places empty albums after named albums within an artist, and places
compilations without an Album Artist or Sort Album Artist after ordinary albums.
Those compilations use the album value within their final section, rather than
their representative Track's artist. The capture contains only one such compilation,
so ordering between several such albums remains an extension of the album-title
policy, not an independently captured comparison. Compilation Tracks with a named
Album Artist stay in that artist's ordinary position. Display-name fallbacks still
ignore a leading `The`; explicit sort values retain their article.

This profile is preferred when it explains the complete retained sequence. The
previous profiles remain available for sources requiring the historical policy
(strip `The` even from overrides, empty albums first, no compilation section).
Punctuation handling remains independently selected from the three captured variants.
A source inconsistent with every profile now uses an explicit default when group
sorting must be rebuilt, with a `library.album_index` warning. That default uses
the 2026-10-08 rules with punctuation retained. Selecting a matching profile
establishes consistency with the captured comparisons, not a universal claim about
iTunes locale collation. See [ADR-0137](../adr/0137-warn-and-default-unrecognized-album-collation.md).

## Reported failure reproduced on 2026-10-08

Both Master Playlists in the supplied 1,203,015-byte database have the same ID.
Their sort-36 sequences contain the same 160 album groups.
The old implementation rejected both with the reported diagnostic. Each punctuation
profile had exactly three adjacent ordering inversions. The following labels are
fabricated equivalents; original names and identifiers are omitted:

| Retained sequence | Old interpretation | Missing rule |
| --- | --- | --- |
| The Zeta, then Thistle | `zeta` sorts after `thistle` | Preserve `The` in explicit Sort Album Artist |
| Fixture Album E, then an unnamed album, both with no artist | An empty album sorts before `fixture...` | This capture places the unnamed album last within its artist section |
| Unnamed album, then a compilation | Representative Fixture Artist A sorts before an empty artist | Compilation without an album artist occupies the final section |

Each correction independently removes one inversion. Together they explain every
album comparison in both full indexes. Changing Album Artist versus Sort Artist
fallback precedence cannot resolve these three pairs: their selected values are
unchanged by that swap.

A public Library preparation test editing one album's Sort Album Artist reproduced
the two errors before the fix and successfully prepared after it. The original
687-Track capture remained unchanged, and no-op preparation reproduced its bytes
exactly. This was an in-memory test using a test signing identity; no generated
database was published to an iPod. The separate unavailable-dates warning remained.
The user's exact 681-change draft was not provided and was not replayed.

## Separate user's failure reproduced on 2026-10-09

The new 1,026,696-byte database belongs to a different user. Both Master indexes
cover all 569 Tracks and keep 52 native album groups contiguous. Its last successful
writer is unknown. The supplied log reports ten additions reaching reconciliation,
then both indexes failing the supported-collation check. A single album edit
reproduced those same errors against the full database on current code.

Each preferred profile has three adjacent inversions. A single-artist compilation
with no Album Artist appears in its artist section; two groups whose artist begins
with `The` remain together despite differing sort-override presence; and two
compilations with Album Artists occur at the end. These observations conflict with
our earlier profile's assumptions. Literal names plus a section for compilations
whose album artist matches no member artist explains this source, but does not
explain the previous user's source. The capture does not distinguish that hypothesis
from all other possible rules or establish a device-specific policy. No speculative
profile was added.

The user chose a nonblocking fallback instead of requiring the original ordering
rule to be determined. The full-source reproduction now prepares an album edit
and, separately, ten fabricated Track additions, each with two warnings. The output
passes independent verification; adding Tracks produces a 579-Track candidate.
No-op output remains byte-exact, original files remain untouched, and generated
bytes stay in memory with a test signing identity. The user's actual media and exact
Sync draft were not replayed, and no physical iPod write was performed.

## Writing and verification

Resolution recognizes MHOD 52/36 and reports its dependent edits. Native album
records and Master membership are reconciled before its final positions are
calculated. Existing prefixes and trailing data remain retained. No new type-36
index or speculative MHOD-53 counterpart is added to a source that lacks one.

Because other indexes on the same Master address the same occurrence sequence,
regenerated standard indexes also use Master Playlist coordinates. Structural
edits usually make the Master order match the submitted Library; metadata edits
must not assume that equivalence. The previous handling of incomplete source
Masters remains with existing source diagnostics and structural validation.

The independent verifier does not call the index writer. It checks permutation,
album contiguity, group order, disc/track order, retained ties, and trailing bytes.
For an unrecognized source collation it verifies group order under the explicit
default, so the fallback warning does not become a verification error.
The existing native group verifier separately checks the album references and
representative ownership on which this index depends. Unrelated edits retain an
unchanged index exactly.

## Reproducible regression evidence

`tests/fixtures/iTunesDB/captured-album-index-36.b64` reconstructs 60 Tracks across
nine native album groups from the historical capture. Its manifest records source
and fixture hashes and the captured Track sequence using synthetic IDs. All text
and identifiers are fabricated. The fixture preserves sorting comparisons and
membership relationships while omitting unrelated metadata and opaque bytes; see
the fixture README for the transformations.

Run the public-API regression cases with:

```shell
uv run pytest tests/iPodDB/library/test_album_index.py
```

They exercise no-op preservation, metadata and album-sort changes, coordinate
remapping, retained ties, additions to existing/new albums, removal, number edits,
review effects, and injected writer corruption. Host-only checks also prepared
title and album-sort edits on the complete historical, Classic A,
and Nano 1 captures. Candidates stayed in memory. This is captured-format and
preparation evidence; physical firmware execution was not tested.

`captured-album-index-36-overrides.b64` reconstructs seven selected representative
Tracks and their album records from the reported failure. Fabricated sorting strings
and identifiers preserve the relevant field presence, compilation flags, album
ownership, representative relationships, and relative Master/sort-36 order in fresh
unsigned test Chunks. Its manifest records synthetic Track IDs, captured sequences,
and hashes. Unrelated metadata, account information, media paths, and opaque data are
omitted. This fixture reproduces the three comparisons without retaining original
names or identifiers. The privacy transformation preserves all 780 pairwise album
comparisons across the two fixtures and six supported profiles.
Tests also cover removing an explicit override without changing its text, changing
compilation status, literal Album sort overrides, and independent index verification.
An intentionally reordered copy of that anonymized fixture exercises default
ordering and warnings for metadata edits and Track additions, no-op/unrelated-edit
preservation, malformed-index rejection, and verification of corrupted fallback
output. The 2026-10-09 original database and log are not stored as fixtures.
