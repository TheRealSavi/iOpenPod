# Finder compatibility after Play Counts ingestion

## Inputs and attribution

The user identified `D:\iPod_Control\iTunes` as Finder-accepted and supplied
`C:\Users\JohnG\Desktop\New folder\iPod_Control\iTunes` for comparison.
Verified Host copies identify the same Nano 5 and the same 15 Podcast Episode
persistent IDs. This is separate from the earlier Classic 6.5 experiments.

The earlier `Podcast Research\Nano 5` capture and `New folder` have equal logical
CDB lengths of 87,732 bytes. Their logical byte differences are confined to 29
playback date fields and root signing fields: 149 changed bytes in total. Podcast
metadata, show references, artwork references, and chapter records are unchanged
in that comparison. Consequently, those Podcast features do not explain this
particular ingestion delta.

## Date evidence

| Field | Accepted capture | After ingestion |
| --- | --- | --- |
| CDB last played, 14 Episodes | 0 | 3,061,137,600 |
| CDB last skipped, all 15 Episodes | 0 | 3,061,137,600 |
| SQLite corresponding played/skipped dates | 0 | 3,600 |
| Completed play and skip counts | All zero | All zero |
| Nonzero bookmarks | 12,005 ms and 7,596 ms | Same |
| One real CDB last-played date | 3,875,145,178 | Same |

`Play Counts.bak` contains the exact offending values. Subtracting the Mac epoch
offset and the captured database offset of -14,400 seconds gives Unix 978,307,200:
2001-01-01 00:00 UTC. Apple documents that instant as the
[Foundation reference date](https://developer.apple.com/documentation/foundation/date/timeintervalsincereferencedate).
Interpreting the raw value through January's New York offset instead produced
01:00 UTC, explaining SQLite's 3,600 rather than zero.

The paired files support treating this exact binary Play Counts value as an
absent-date sentinel. They do not establish that every January 2001 date in every
format should be discarded. The fix compares raw values using the captured
database offset, preserves existing history, and retains real playback dates even
when no play has completed. Previously committed bad Track dates are not globally
rewritten without their sidecar provenance.

## Difference policy

| Difference | Decision |
| --- | --- |
| Valid HASH72 with stale HASH58; scheme 2 instead of Apple's dual scheme 1 | Fix changed HASH72 publications to generate and verify both signatures under scheme 1. |
| SQLite `version_info` minor 111/device level 1104 replacing 117/1100 | Retain the complete existing version row and schema, including platform and unknown version columns. |
| Native `db_id` used for SQLite Library identity | Use `db_persistent_id`, falling back only when absent. Use the native Master playlist ID and dates. |
| `has_been_played` based only on completed-play count | Include native played state. The accepted capture has 14 set flags despite zero completed plays. |
| Eleven lyrics rows and 15 store rows erased | Retain unrepresented metadata; explicit edits, clears, media replacement, and deletions still take effect. |
| SQLite-only video, rental, UI, or Genius metadata erased | Preserve it within the supported retained-schema contract. |
| Three newer calculated columns in Library and one in Dynamic | Existing firmware schemas win; these columns are optional during projection. |
| Additional dataset-5 category containers | Keep the deliberate CDB projection policy; validate membership and references. |
| Different positive browse IDs, generated sort ranks, additional calculated values | Accept as internal projection differences when known references resolve. Source-specific collation is not claimed to be identical. |
| Absent strings represented as empty text rather than NULL in some fields | Retain current semantic projection; no observed broken reference or metadata loss. |
| Artwork status derived from actual artwork and native sample/gapless facts supplied | Keep the existing authored behavior. Apple's missing artwork is not a requirement. |
| SQLite page layout, counters, writer-engine marker, compression size | Not required to be byte-identical after changes; validate integrity and checksums. |

“Accept” is an implementation decision, not proof of Finder compatibility. The
empty iTunesDB compatibility placeholder and additional category containers remain
possible independent experiment variables if Finder still rejects a new write.
Episode/season numbers, explicit-content flags, artwork, chapters, and repaired
show links remain intentional improvements under ADR-0149.

## Host replay

Replayed the captured Play Counts over both Apple Nano 5 baselines and explicitly
refreshed SQLite through the public preparation API. No connected device was
modified, and hashes confirmed that source captures remained unchanged.

- The 14 missing played dates and 15 missing skipped dates remain zero.
- The real last-played date and both bookmarks survive. For this input, the fixed
  overlay introduces no native edits, so both CDBs remain byte-identical to their
  source. Both signatures validate; a separate changed-output regression verifies
  that publication regenerates both.
- All five schemas and version rows remain unchanged. The accepted capture retains
  `(1, 1, 117, 0, 0, 1100, 2)`; the earlier capture retains its platform value 1.
- Eleven lyrics rows, 15 store rows, and Genius records survive exactly. SQLite
  playback and location rows match the accepted capture by persistent Track ID.
- Library and Master IDs are 1821498617957353918 and 3341984075397570597.
  The Master dates now project the corresponding native playlist timestamps.
- All five databases pass integrity and application relationship checks; Locations
  Checksum Books verify. Eight containers intentionally project the CDB categories.

Local evidence is under `.scratch/finder-podcast-compat/playcounts-comparison/`
and `.scratch/finder-podcast-compat/playcounts-fixed/`, including hashes, structured
diffs, and replay output. Private device captures are not committed. The durable
policy is [ADR-0150](../adr/0150-retain-firmware-sqlite-metadata-and-dual-signatures.md).
The comparison narrows the causes but does not isolate which discrepancy made
Finder reject the prior output; physical acceptance remains unverified.

Final focused validation passed 252 tests across SQLite generation/retention,
signing, playback projection, reconciliation, and Application Layer publication.
Mypy, Ruff, Rumdl, and the dependency lock check passed. The user requested stopping
the full suite; it was interrupted after two failure markers, before detailed
failure reports were emitted. Those untriaged failures are not represented as a
passing full-suite result.
