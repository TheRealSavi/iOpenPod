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
| Classic `beanoblubiTunesDB` | `1e1abac446e120cfceb70986e12109dc1c71e35304e3bdeac94cefece727d284` | 5630 | 482 |
| Classic `beanoblub2 iTunesDB` | `b0008450fbc823a87fdcc9ed6bbb2507031405158a7e1db7e94367844dad4457` | 5641 | 483 |
| Classic `beanoblub3 iTunesDB` | `5348897d2b77498f04169529eeafa6cf1030129d6accac7ddf4d7ad7e3c7c6da` | 5630 | 482 |
| iPod 3 `skepiTunesDB` | `de80d81f5278016a1968156de70087889dfd2eab307c20b3d4cd855c28d40f84` | 193 | 91 |
| Nano 1 `skep_iTunesDB` | `9b5614404f8be6fd71fac23baccc4a9eb7ae16e1d2fba432731b70009f5e1fe1` | 184 | 91 |
| Photo `skepiTunesDB` | `06b2968824d81457311c6c9ed9545c0680c6e762490b38025e2dd86b24ed146f` | 191 | 93 |

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
normalize curly apostrophes, ignore a leading `The`, and place numeric names after
letter names. Empty artists sort last; empty albums sort first within an artist.
A source inconsistent with every profile blocks a changed group sort with a
specific diagnostic. Selecting a matching profile establishes consistency with
the captured comparisons, not a universal claim about iTunes locale collation.

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
The existing native group verifier separately checks the album references and
representative ownership on which this index depends. Unrelated edits retain an
unchanged index exactly.

## Reproducible regression evidence

`tests/fixtures/iTunesDB/captured-album-index-36.b64` retains 60 Tracks across nine
complete native albums from the historical capture. Its manifest records source
and fixture hashes and the expected Track sequence extracted from each original
index. The fixture is reduced, not a whole untouched device database; see the
fixture README for the transformations.

Run the public-API regression cases with:

```shell
uv run pytest tests/iPodDB/library/test_album_index.py
```

They exercise no-op preservation, metadata and album-sort changes, coordinate
remapping, retained ties, additions to existing/new albums, removal, number edits,
review effects, and injected writer corruption. Host-only checks also prepared
title and album-sort edits on the complete historical, Classic `beanoblubiTunesDB`,
and Nano 1 captures. Candidates stayed in memory. This is captured-format and
preparation evidence; physical firmware execution was not tested.
