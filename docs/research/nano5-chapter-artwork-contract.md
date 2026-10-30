# Nano 5 Chapter artwork contract

Research date: 2026-10-30. The pre-fix nano 5 producer left Chapter artwork
disabled even when it wrote valid timed images. Nano 5 RetailOS reads a separate
Chapter artwork bit from the Extras Chapter blob. The Device Profile omitted
Chapter formats, so preparation left that bit clear. Declaring native F1073 as a
Chapter format now enables it without changing any image bytes.

The initial investigation changed no product behavior or device files. Its
subsequent product adoption and regression checks are recorded below. The finding
is an executed native contract violation, not a physical playback acceptance result.

## Firmware identity and evidence

| Property | Inspected value |
| --- | --- |
| Model family | iPod nano 5th generation, N33 / S5L8730 |
| RetailOS | 1.0.2 / 34A20020 |
| Plaintext OSOS length | 7,284,288 bytes |
| OSOS SHA-256 | `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49` |
| Ghidra program | `Nano5FW/ghidra-final-keys/Nano5FinalKeys.gpr`, `osos.raw.bin` |
| Runtime DRAM mapping | Raw `+0x2e27c` becomes `0x08000000` |

The [map receipt][map] checks all three initialized runtime regions against the
exact plaintext image. Exports were made with Ghidra 12.2 in read-only mode.
Addresses below are runtime addresses; the earlier flat import is unsuitable.
See the [previous independent nano 5 investigation](phase-nano5-firmware-contract.md)
for the startup map and release provenance. Function descriptions are analyst
interpretations, not recovered Apple symbols.

## The native Chapter format is F1073

The firmware's capability emitter at `08007120` writes `ChapterImageSpecs` when
its capability byte at object `+0x676` is one. It emits one format: literal
`08007214` is `0x431`, or F1073. It obtains its descriptor through `0819435c`.
The [capability export][capability] contains the complete emitter.

Executing the actual descriptor routine produces width 240, height 240, and row
stride 480. Executing selector mapping `0825a7cc` maps internal selector 13 to
F1073. Selector 23 maps to ordinary F1056, 128 by 128. These selector numbers
must not be copied from Classic firmware, where the Chapter pair differs.
The [native receipt][native] records the full tested selector domain and all four
current nano 5 cover descriptors. The selector and descriptor probes execute
native instructions without call adapters, including the inline-switch helper.
Their linear Ghidra pseudocode does not correctly recover every switch branch.

F1073 already belongs to nano 5's ordinary cover set. The missing Chapter
declaration therefore does not necessarily mean missing pixels. This distinction
is decisive in the producer experiment below.

## Extras has independent navigation and artwork flags

The firmware contains this Chapter query at `0853d075`:

```sql
SELECT item_pid, data FROM chapter WHERE data NOT NULL AND item_pid=?1;
```

The Track wrappers obtain that blob through `08248d24` / `0812e71c` and parse it
with `08248c90`. That parser finds the first `hedr`, copies up to eight payload
bytes, and converts both words from big endian. The serialized flags at
`hedr +0x18` become parsed object `+0x0c`. `08248d42` returns that flags word.
Sources: [native parser][parser], [blob accessor][blob-accessor], and
[flag accessor][flag-accessor].

| Header masks | Named Chapter count | Chapter artwork flag |
| --- | --- | --- |
| 0 | 0 | false |
| 1 | Available from name-bearing Chapters | false |
| 2 | 0 | true |
| 3 | Available from name-bearing Chapters | true |

`08116c24`, reached by Track wrapper `0827a904`, requires mask 1 and builds a
name-bearing Chapter index through `0822a110`. `0822f088` independently returns
whether mask 2 is set. It reads the Extras header directly; the Classic importer
rule that creates native Track masks `0x840` is not the implementation of this
nano 5 gate. Sources: [named count][count], [index builder][index], and
[artwork flag wrapper][gate].

`081313f0` reads starts in the retained named-index order and normalizes raw
start 1 to zero. Player transition `08202e48` tests named count and the Chapter
artwork flag together when deciding whether to rebuild artwork state; its old
Track virtual calls use slots `+0x144` and `+0xec`. Completion helper `081765b4`
also branches on the Chapter artwork flag and compares the current Chapter index
with the completed image index. These are native consumers, not merely unused
metadata accessors. Sources: [start accessor][starts], [transition][transition],
and [completion helper][completion]. This pass does not prove every provider,
view, asynchronous update time, or codec path.

## Reproduced output and a controlled alternative

At investigation time, the nano 5
[catalog entry](../../src/device_registry/data/catalog.py) declared cover formats
F1056/F1078/F1073/F1074 but omitted Chapter support and formats.
The [format adapter](../../src/iOpenPod/app/artwork_policy.py) consequently
supplied an empty Chapter set. The
[reconciler](../../src/iPodDB/library/_reconcile.py) only passes explicit timed
assets to Chapter flag coordination when the target has Chapter formats.
[Chapter writing](../../src/iPodDB/library/_track_writing.py) otherwise leaves
the navigation-only header value 1.

The executed producer probe uses the real MC046 profile and Library preparation,
two named Chapters at 0 and 500 ms, and red/blue timed images at those same times.
It also runs the actual SQLite projection and database generator. A second run
changes only the write target's Chapter formats to its existing F1073 layout.
Sources: [producer audit script][producer-script] and [receipt][producer].

| Observation | Pre-fix profile | Isolated F1073 Chapter target |
| --- | --- | --- |
| CDB `hedr` flags | 1 | 3 |
| Extras `hedr` flags | 1 | 3 |
| Named Chapters seen by native parser | 2 | 2 |
| Native Chapter artwork flag | false | true |
| Artwork Display Times | 0, 500 ms | 0, 500 ms |
| All generated image paths, lengths, and SHA-256 hashes | Identical | Identical |

The actual alternative Extras blob equals the pre-fix blob with only flags 1
changed to 3. The blobs are 164 bytes, with these SHA-256 hashes:

- Pre-fix: `bba1185140d290bc06918d02d575299b200138de21de98ca0d3fa9f829700746`.
- Flags 3: `27374996078d39418befb47eea7bf373dea2262e289926070680e0df35d94fe4`.

Both exact blobs were passed through native `08248c90`, its atom search,
big-endian conversion, named-index builder, start accessor, and the actual
`0822f088` artwork gate. Navigation succeeds for both; the artwork flag is false
for pre-fix output and true for the alternative. Allocation, container ownership,
model validity/context, and SQLite blob delivery have explicit Host adapters.
The parser, flag test, and named-index logic execute unmodified firmware bytes.
The [native probe script][native-script] and [receipt][native] list every adapter.

## Adopted correction and boundaries

Device Registry now declares nano 5 Chapter image support and F1073 with the
Chapter artwork role. This lets the existing explicit-timeline workflow enable masks
1 and 2 in CDB and Extras while reusing the existing pixels. Setting only the
support boolean would leave the empty-format gate in place. The catalog regression
now permits the evidenced nano 5 set alongside Classic while retaining empty
Chapter sets for other profiles. The evidence
supports this nano 5 release; it does not establish the other nano generations.

This changes the evidence behind [ADR-0139's](../adr/0139-complete-timed-artwork-formats-and-counts.md)
Classic-only Chapter set. Its general separate-format policy and
[ADR-0202's](../adr/0202-adopt-native-artwork-and-chapter-semantics.md) explicit
flag-coordination policy remain appropriate. Both records now include the nano 5
adoption. A normal virtual-device prepare/save/reload regression checks CDB and
Extras flags, retained unknown bits, unchanged Chapter metadata, timed F1073
pixels, and byte-identical image files against a cover-only target. Ordinary
cover replacement preserves the existing Chapter flags.

The Original iOpenPod baseline at local `origin/1.x`, commit
`a20242428b93b672d14b37230772dbad75139c69`, also omits nano 5's Chapter support in
`src/iopenpod/device/capabilities.py`. Its Extras writer builds Chapter blobs
through the same MHOD-body representation. This baseline is producer history,
not evidence against the native capability.

Eight retained nano 5 Host captures had empty Extras Chapter tables, so none was
a known-working Chapter artwork control. Their differing `artwork_status` values
also correlate with differing image associations and do not establish that value
2 enables Chapter artwork. The executed Chapter gate explains the reproduced
contract failure without changing that field, MHIT artwork counts, media
classification, timestamps, or raster layouts. Physical display acceptance and
the user's exact affected media remain unverified.

## Reproduction and adoption checks

From this repository, the regression tests use synthetic bytes and a virtual
device without requiring firmware:

```powershell
uv run pytest tests/device_registry/test_artwork_profiles.py tests/iOpenPod/app/services/test_nano5_chapter_artwork_save.py
```

The new tests failed before the catalog correction: timed output retained flags
1, and the catalog had no Chapter capability. They pass after adoption. The
original private producer audit's `--check` run also exited 1 on the pre-fix MC046
output after verifying the controlled alternative. Its retained receipts and
exact blob hashes above describe that investigation state.

From the sibling `ipod-firmware-lab`, `uv run scripts/probe_nano5_chapter_artwork.py`
replays the retained pre-fix and flags-3 blobs through the pinned native routines.
It passes 53 cases: two complete blob cases, 41 selector cases, four raster
descriptors, and six flag-matrix cases. It never accesses an iPod. Regenerating
producer artifacts from changed product code is a new experiment and must retain
those historical inputs separately. Generated
firmware exports and binary artifacts remain in the private firmware lab; the
application gains no runtime dependency on them.

[map]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/map-check.json
[capability]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/deep/08007120.c
[native]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/native-probes.json
[parser]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/chapter-atoms/08248c90.c
[blob-accessor]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/flags/08248d24.asm.txt
[flag-accessor]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/flags/08248d42.c
[count]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/chapter-atoms/08116c24.c
[index]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/chapter-atoms/0822a110.c
[gate]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/track-vtable/0822f088.asm.txt
[starts]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/chapter-atoms/081313f0.c
[transition]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/flags/08202e48.c
[completion]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/player/081765b4.c
[producer-script]: ../../../ipod-firmware-lab/scripts/audit_nano5_chapter_output.py
[producer]: ../../../ipod-firmware-lab/artifacts/nano5-chapter-artwork/producer/nano5-chapter-output-probe-2026-10-30.json
[native-script]: ../../../ipod-firmware-lab/scripts/probe_nano5_chapter_artwork.py
