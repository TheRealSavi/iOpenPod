# Issue 333: Mini 2 type-10 text and database loading

Investigated 2026-11-15 against [issue 333][issue], the current iOpenPod source at
`95dc0c4b436e8cd4feba4c19ec947e5eb5cfb0af`, and the sibling firmware lab.
This is an investigation and implementation recommendation, not an adopted ADR
or a change to Library publication. No physical iPod was accessed.

## Conclusion

Stop authoring MHOD type 10 as an iOpenPod lyrics cache. The existing provenance
review never established that meaning, and Mini 2 firmware now supplies direct
evidence of a substantial cost: it retains the text in a dynamically grown pool,
without deduplicating identical strings. Buffer growth allocates the replacement
before freeing the previous buffer. A native-code probe confirms that allocation
failure propagates through the Track importer to the root database importer.
[Provenance][provenance], [Mini 2 investigation][mini2]

There is an important correction to the issue discussion: **type 10 is not ignored
by every iPod**. Mini 1/2 import it and have a text-comparison consumer; the studied
Classic skips it. Its original Apple semantic name remains unresolved. Native
import and comparison do not establish lyrics display, and the previously captured
HTML does not establish a universal podcast-description definition.
[Mini 2 investigation][mini2], [legacy comparison][legacy], [Classic investigation][classic]

The reporter's failure is consistent with this allocation mechanism. It is not
yet a reproduced diagnosis of their exact database. The evidence establishes
neither a universal 16 MiB database limit nor a safe 32 MiB acceptance threshold.

## What the issue establishes

These are the reporter's physical observations, not new lab measurements:

| Library | Serialized iTunesDB | Reported result |
| --- | ---: | --- |
| Approximately 2,119 Tracks | 8,301,284 bytes | Tracks visible |
| 4,268 Tracks | 17,608,942 bytes | Music and About show zero songs |
| Same 4,268 Tracks after removing type 10 and clearing the lyrics flag | 8,084,016 bytes | All Tracks visible |

The removed 2,523 Chunks account for 9,524,926 bytes, approximately 54.1% of the
failing file. The report identifies a flash-modified Mini 2, model M9802, but does
not state its RetailOS version or attach the before/after databases. Two variables
changed together: type-10 records and the MHIT lyrics flag. Their independent
effects must not be inferred from the report alone. [Issue][issue]

## Exact firmware evidence

The Mini 2 target is updater family 7, RetailOS **1.4.1**, OSOS SHA-256
`346504450c5201a632cafa38312093fc04b402b4ca37c79d7ca4a4167bb8f34d`.
The main code addresses below map directly to raw OSOS offsets; initialized
runtime regions use the independently verified startup map. This exact target
is not an assertion about the reporter's unidentified firmware release.
[Workspace and acquisition][mini2-workspace]

| Native path | Verified result |
| --- | --- |
| Track importer `0x000B02A4`, type-10 branch `0x000B07A4` | Calls the string importer, selecting database pool `+0x268` and Track token `+0x50`. |
| Pool setup `0x000871F0` and insertion `0x0003020C` | Duplicate lookup is disabled. Two identical 12,000-byte strings occupy 24,000 text bytes and receive distinct tokens. |
| String importer `0x000B2114` | Encoding-1 UTF-16 text follows the full-length import path; it is not reduced to 255 characters. |
| Handle resize `0x000967C0` | Allocates the entire new capacity, copies the old data, then frees the old allocation. |
| Root importer `0x000B0C70` | A fixture-induced replacement allocation failure returns -108 through native pool, string and Track import code; success finalization is bypassed. |
| Reader `0x0004B8D8` | Rejects a single read above 262,144 bytes. This is a per-read bound, not a total database limit. |
| Getter `0x00074FA4`, comparator `0x00040D8C` | Retrieve the type-10 UTF-16 text and compare it for selector `0x40000`; no user-facing field name follows from that selector alone. |

The [lab report][mini2] links the disassembly and the hash-bound native probe.
Ten cases cover full-text retention, duplicate text, flag independence, allocation
failure, the per-read boundary, and skipped unknown metadata. A synthetic database
of exactly 17,608,942 bytes containing skipped type-11 metadata imports successfully
in the supplied heap. Thus its serialized length alone does not trigger a fixed
16 MiB rejection in this exercised path. This specimen is not the reporter's
Library and does not reproduce their live memory use.

The harness executes original ARM importer, pool, resize and copy instructions.
It supplies a synthetic filesystem, initial Track allocation, lowest-level heap
operations and final notifications. It does not emulate the complete operating
system, physical heap fragmentation, boot, display or audio playback. The outer
loader's retry/fallback path was inspected statically; a zero-song screen was not
reproduced. [Harness][probe], [execution receipt][receipt]

For Classic 120GB RetailOS 2.0.1, OSOS SHA-256
`220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`,
type-10 dispatch instead branches from `0x080744A0` to `0x080749F0` and discards
the payload. The existing 4,124-byte instruction audit and lyrics metadata audit
were rerun successfully. Native lyrics use the separate MHIT low bit and media
ULT/USLT or MP4 `©lyr` route. [Classic type-10 evidence][classic],
[adopted lyrics contract][adoption]

An independent Nano 1 **1.3.1** byte audit also confirms type-10 skipping and a
separate lyrics path: the imported MHIT low bit reaches a getter, embedded-media
readers, cached bytes, decoding, and a text data provider. Mini 1 **1.4.1** instead
has the retained type-10 pool/getter/comparison path. The comparison does not
complete a Nano screen-renderer trace or prove that every Mini firmware path lacks
lyrics support. Exact hashes and the 29-function audit are in the
[legacy comparison][legacy].

## What type 10 is actually used for

The strongest established description is **an unidentified Track text field,
retained and comparable on Mini 1/2, skipped by the studied Classic importer**.
This separates a demonstrated operation from an unsupported semantic name.
[Mini 2 investigation][mini2], [legacy comparison][legacy], [Classic investigation][classic]

The comparison takes **Track A's type-10 string and Track B's type-10 string**,
then invokes the shared text-ordering routine. It is an available field in the
generic ordered-comparison machinery. It does not compare type 10 against
MHOD 14 or embedded lyrics, and it is not pool deduplication. A shipped menu or
workflow that requests ordering by this particular field has not been identified.
[Mini 1 getter and ordered comparison][legacy], [Mini 2 comparator][mini2]

Other fields can feed the same Mini 2 text helper: Title (MHOD 1), Album (3),
Artist (4), Genre (5), File type (6), EQ setting (7), Comment (8), Category (9),
Composer (12), Grouping (13), and Description (14), plus an alternate artist
representation. This identifies type 10 as another comparable text slot; it
does not narrow its meaning to lyrics or descriptions. The enclosing dispatcher
also has separate comparisons for numeric fields. The
[getter map and additional 21-function byte audit][mini2] document these routes.

Earlier captured type-10 records contained HTML closely matching the same Tracks'
plain MHOD 14 podcast descriptions. Their producing application was not established;
known iOpenPod output can itself create this field. Those records are evidence
about their contents, not proof of Apple's intended definition. The prior
investigation also found independently identified Apple captures with no type 10.
Neither its presence nor its absence supplies a universal definition.
[Capture and provenance review][classic]

Consequently, neither renaming it to a definitive podcast-description field nor
deleting every retained instance follows from this investigation. A traced
semantic consumer or independently produced Apple record with controlled source
metadata would be needed to settle the name.

### Further consumer audit

The follow-up explicitly tests the stronger question of whether comparison is
the field's only use. It does **not** establish that the firmware does nothing
else with type 10.

- Mini's generic sorting machinery contains an internal mode `0x13` that selects
  type-10 text first and Title as a tie-breaker. This supplies an actual ordering
  path, rather than just an isolated string-comparison branch.
- The examined Playlist sort importer does not translate any supported on-disk
  sort value to that internal mode. The corresponding Mini 1/2 Smart Playlist
  predicate field is rejected. Available internal sorting must not be presented
  as an established stock menu or supported Smart rule.
- Mini 2's Track-cloning path copies the type-10 string between database pools;
  Track release and database reset also manage its allocation. These are further
  uses of the stored bytes, but they do not reveal the field's original meaning.
- The examined Mini 2 field-descriptor consumer reads the field's cache index,
  discarding the getter pointers placed in that temporary descriptor. Merely
  finding those pointers was insufficient evidence of an indirect display or
  search consumer.

No stock playback, lyrics-display, or user-selected type-10 sort workflow has
been established by this pass. This is a bounded result for the exact images,
not a proof about every possible indirect call or every iPod firmware.
[Mini 2 indirect-consumer audit][mini2-consumers],
[Mini 1 sort and predicate follow-up][mini1-consumers]

Native Mini 1 comparisons confirm nonempty/absent ordering and the Title
tie-breaker without mocked native calls. Mini 2's native sorter independently
orders a nonempty type-10 value before an absent value; its clone-helper cases
preserve complete 510-, 512-, 514- and 12,000-byte strings. The latter two need
a temporary heap buffer. These selected cases establish working internal paths,
not arbitrary Unicode collation or a stock menu trigger. Both reports retain
hash-bound reproducers, explicit synthetic inputs and execution receipts.

## Implications for current iOpenPod decisions

1. **Remove new type-10 lyrics authoring and its authoritative lyrics projection.**
   The enum still assigns `LYRICS = 10`; the Library field policy maps `lyrics`
   through that enum and the Track writer authors it. The current projection also
   treats its text as lyrics, so description-like retained content can become
   misleading Host text. Preserve existing unidentified records and distinguish
   any proven application cache during migration. [Enum][enum], [field policy][fields],
   [writer][writer], [projection][projection]
2. **Separate native lyrics capability from Host lyrics support.** Device Registry
   currently has no lyrics capability, and preparation only distinguishes Classic
   native verification from the generic path. A capability can prevent native-only
   lyric preparation on unsupported targets while retaining Host reading, export
   and explicitly requested metadata behavior. Missing evidence should remain
   unknown, following the existing `FeatureSupport` vocabulary. Merely clearing
   `lyrics_flag` does not avoid the Mini's type-10 allocation. [Registry models][models],
   [preparation][preparation], [Mini probe][mini2], [legacy comparison][legacy]
3. **Qualify the existing database-size guard.** ADR-0143 and the source architecture
   call the 32/64 MiB serialized-size values hardware limits. The actual write guard
   compares artifact lengths; it does not account for native pools, temporary
   copies or available contiguous heap. Passing it cannot establish firmware
   acceptance. Do not replace it with an inferred 16 MiB constant from one report.
   [ADR-0143][size-adr], [architecture][architecture], [catalog][catalog],
   [write guard][guard]
4. **Keep optional application caches separate from firmware databases.** If fast
   Host lyrics access needs a cache, it should not consume a native Track field
   with unresolved meaning. Existing lazy file-first reading and the distinction
   between application catalogs and firmware databases provide appropriate
   starting points. Removing cache emission does not require deleting embedded
   lyrics already present in copied media. [ADR-0075][lyrics-adr], [ADR-0143][size-adr]

The implementation baseline described above preceded PR 334. These recommendations
are now adopted in [ADR-0270](../adr/0270-keep-lyrics-out-of-mhod-10.md): stop
type-10 lyrics authoring/projection, preserve its unidentified bytes, and gate
automatic preparation by native display or Rockbox policy. ADR-0075's media-tag
requirement and ADR-0206's qualified Classic verifier retain their firmware basis;
native tag verification never validated the old database mapping.
[ADR-0075][lyrics-adr], [ADR-0206][native-adr], [adoption limits][adoption]

## Remaining evidence needed

- The reporter's exact firmware identity and before/after database bytes, including
  the largest individual type-10 payload and its framing.
- Separate specimens that remove only known application-authored type 10 or change
  only the presence flag, with other bytes and media held constant.
- Actual heap state or a controlled physical reproduction to distinguish aggregate
  allocation pressure from an oversized individual string or another import error.
- Model-qualified native lyrics behavior before treating all pre-Video or all Nano
  generations as one capability group. Shuffle remains outside this repository's
  product scope; the issue's mention of it does not expand that scope.
- Regression coverage for new emission, retained Unknown Data, provenance-aware
  repair, native capability gating, and byte-exact unchanged databases when the
  implementation policy is adopted.

[issue]: https://github.com/TheRealSavi/iOpenPod/issues/333
[provenance]: mhod-10-provenance.md
[mini2]: ../../../ipod-firmware-lab/notes/mini2-mhod10-database-loading.md
[legacy]: ../../../ipod-firmware-lab/notes/legacy-lyrics-capabilities-2026-11-15.md
[mini2-workspace]: ../../../ipod-firmware-lab/notes/mini2-firmware-workspace.md
[classic]: ../../../ipod-firmware-lab/notes/itunesdb/mhod10-identity.md
[probe]: ../../../ipod-firmware-lab/scripts/check_mini2_mhod10.py
[receipt]: ../../../ipod-firmware-lab/artifacts/mini2-mhod10-20261115-final/receipt.json
[adoption]: lyrics-firmware-adoption.md
[enum]: ../../src/iPodDB/iTunesDB/shared/constants.py
[fields]: ../../src/iPodDB/library/_field_policy.py
[writer]: ../../src/iPodDB/library/_track_writing.py
[projection]: ../../src/iPodDB/library/_projection.py
[models]: ../../src/device_registry/models.py
[preparation]: ../../src/iOpenPod/app/services/library_resources.py
[catalog]: ../../src/device_registry/data/catalog.py
[guard]: ../../src/iPodDB/library/_write_preparation.py
[architecture]: ../source_architecture.md#common-library-interface
[size-adr]: ../adr/0143-separate-scan-cache-size-from-firmware-database-limits.md
[lyrics-adr]: ../adr/0075-publish-lyrics-with-media-file-tags.md
[native-adr]: ../adr/0206-validate-native-lyrics-publication.md
[mini2-consumers]: ../../../ipod-firmware-lab/notes/mini2-mhod10-indirect-consumers.md
[mini1-consumers]: ../../../ipod-firmware-lab/notes/mini1-mhod10-consumer-followup.md
