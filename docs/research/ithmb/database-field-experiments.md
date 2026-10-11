# Unknown database-field experiments

Research date: **2026-10-11**. This investigation follows the
[local emulator artwork experiments](ipod-emulator-experiments.md). The initial
target is the same synthetic Video 5G / Apple `iPod_20.1.3` configuration, with
iTunesDB version `0x19` and a retained **`0x148`-byte MHIT header**. Nineteen runs
completed. Controls pass, and changing F1029's MHNI `0x24` to `1`, `5000`, `10000`, or `0xFFFFFFFF`
changes the final Now Playing view under the same input sequence. The finite
values and `0xFFFFFFFF` produce different outcomes; a fresh baseline restores the
original views. Traces establish field consumption in a thumbnail selector;
caller analysis strongly supports playback-position milliseconds on this firmware
path. Full behavior, other workloads, and other firmware remain unresolved.
Source hypotheses and measured
results are distinguished below. No
format definition, writer default, or shard cap changes are implied.

These are local emulator observations for formats 1028 and 1029. They do not
validate physical Video devices, other firmware releases, Classic/nano models,
or the format 1061 questions that motivated the wider investigation.

## Candidate fields and existing evidence

Offsets below are **relative to the start of the named Chunk**, including its
marker and length words. They are not database-file offsets or runtime-object
offsets. iOpenPod presently retains these fields under unknown names; all are
unsigned 32-bit values except MHIT `0xB3`, which is one byte. The six candidates
fit the existing short MHIT/ArtworkDB headers without extending them.
[Current MHNI definition][current-mhni], [MHII definition][current-mhii],
[MHIT definition][current-mhit].

| Candidate | Existing implementation evidence | Hypothesis to test, not established semantics |
| --- | --- | --- |
| MHNI `0x24`, u32 | Original iOpenPod reads `unk1`. libgpod's declared MHNI fields stop after width at `0x22`. foo_dop reads/writes `display_start_time_ms` at `0x24` and supplies chapter start positions. [Original reader][original-mhni], [libgpod structure][gpod-struct], [foo_dop assignment][foo-chapters], [serialization][foo-mhni-write]. | Start time for selecting timed/chapter artwork; strongest named hypothesis among these candidates. |
| MHII `0x1C`, u32 | libgpod calls it `unknown4`; foo_dop `unk4`; Original calls it `unk1` with an “always 0” comment. [libgpod structure][gpod-struct], [foo_dop serialization][foo-mhii-write], [Original parser][original-mhii]. | No supported meaning found. Zero in an implementation's observations does not establish reserved/ignored behavior. |
| MHII `0x24`, u32 | libgpod calls it `unknown6`; foo_dop `unk6`; Original calls it `unk2` with the same zero comment. [libgpod structure][gpod-struct], [foo_dop serialization][foo-mhii-write], [Original parser][original-mhii]. | No supported meaning found. It is distinct from MHNI `0x24` despite sharing an offset. |
| MHIT `0x84`, u32 | libgpod reads/writes `unk132`; foo_dop serializes `unk11`; Original preserves `unk0x84`. [libgpod parser][gpod-mhit-read], [foo_dop writer][foo-mhit-write], [Original definitions][original-mhit]. | No supported meaning found. Its position after artwork size is not evidence that it controls artwork. |
| MHIT `0x94`, u32 | libgpod calls it `unk148`, with a tentative comment associating Store DRM songs with `0x01010100`. foo_dop names the word `store_key_versions`. Original retains `unk0x94`. [libgpod field documentation][gpod-mhit-doc], [foo_dop writer][foo-mhit-write], [Original definitions][original-mhit]. | Store/key-version metadata, possibly independently meaningful byte lanes. Neither the name nor the repeated-byte example establishes a bitmask or a universal encoding. |
| MHIT `0xB3`, u8 | libgpod calls it `unk179`, unknown and zero in its observations; foo_dop `unk37`; Original `unk0xB3`. [libgpod field documentation][gpod-mhit-doc], [foo_dop writer][foo-mhit-write], [Original definitions][original-mhit]. | No supported meaning found. Adjacency to lyrics/video/played markers does not establish another Boolean flag. |

The cited Original research independently reports `0xB3 = 0` in all 6,541 tracks
of one Classic 6.5G, firmware 2.0.1 database. That source explicitly limits its
claims to the sampled library and uses `0x248`-byte MHIT headers. It is background
evidence, not a Video 5G firmware result. Its Classic code addresses must not be
transferred to the Video firmware. [Original observation log][original-observations].

### MHNI timing needs an appropriate workload

foo_dop does more than attach a suggestive name. It assigns each chapter image's
start position to the MHNI field, maps a chapter position of `1` to `0`, and
chooses ordinary cover time `0xFFFFFFFF` when chapter art already starts at zero;
otherwise the cover time is zero. Its lookup distinguishes the same format ID by
time as well. This is concrete **producer behavior**, not direct confirmation of
Apple's consumer logic or of support in every firmware.
[Chapter creation and cover selection][foo-chapters], [lookup][foo-lookup].

A single static image at one playback position cannot discriminate that
hypothesis. A useful later workload has two distinguishable images of the same
format at times zero and ten seconds, appropriate chapter metadata, and playback
or seeking across the boundary. A valid chapter-bearing audio fixture should be
established as a positive control before a lack of switching is interpreted.
This is a proposed experiment derived from the producer behavior above.

## Proposed interventions

First record the baseline value and exact file offset of each target. Change one
field in one record per image; keep all other file bytes, record lengths, IDs,
payloads, and navigation inputs fixed. Choose values for the competing
interpretations rather than assuming every unknown word is a flag:

| Candidate | Initial values beyond baseline zero | Discriminating workload / limit |
| --- | --- | --- |
| MHNI `0x24` | `1`, `5000`, `10000`, `0xFFFFFFFF` | Static-cover tests detect gross selection changes; timed/chapter images and boundary crossing test milliseconds and sentinel behavior. |
| MHII `0x1C`, `0x24` separately | `1`, `2`, `0x80000000`, `0xFFFFFFFF` | Browse and play a covered track, switch small/large art, leave and revisit. Test PhotosDB separately if an image- or photo-specific use remains plausible. |
| MHIT `0x84` | `1`, `0x01000000`, `0x13579BDF` | Load, browse, play, switch artwork, and inspect read/branch traces. The distinctive word helps follow data; it has no claimed legitimate semantic value. |
| MHIT `0x94` | `0x01010100`, then `0x00000100`, `0x00010000`, `0x01000000` | Separates the historical repeated-byte pattern into lanes. A plain generated MP3 may never reach Store-related code; no visible change cannot refute that hypothesis. |
| MHIT `0xB3` | `1`, `2`, `0x80`, `0xFF`; refine to individual bits if behavior changes | Browse, play/pause, seek/bookmark, and revisit with separately validated music/podcast workloads. Values are probes, not claimed valid flags. |

Avoid adding a later field such as MHIT artwork link `0x160` to this experiment:
it lies outside a `0x148` header and would introduce a second intervention. For
Podcast experiments, account for the existing recognized marker at `0xA7` and
playback flags instead of treating `0xB3` as their substitute.
[Current MHIT definition][current-mhit],
[ADR-0092](../../adr/0092-enforce-podcast-and-video-playback-options.md).

## First campaign: actual method

The local campaign directory is
`C:\Users\JohnG\Coding\ipod-emulator-lab\field-lab`. `plan.json` maps fixture file
offsets through independently parsed FAT extents to disk offsets. `field_lab.py`
restores each worker from the same hashed pristine `baseline.img`, applies the
common pixel change and one case-specific patch, and verifies the resulting files
through an independent FAT reader. Two 8 GiB workers are reused; a worker pathname
is not a permanent artifact identity. Reports retain hashes, patch manifests,
input commands, captures, a copy of the harness, and post-run readback. Watched
runs additionally retain copies of their executable and address list. The two
initial display controls predate executable pinning, and have no address list
because no field watches were enabled; later pinned runs repeat their results.

All cases replace F1028's earlier quadrant image with a **distinct cyan-based
sentinel containing black and white markers**. F1029 retains the 200×200 quadrant
image. This avoids mistaking an enlarged F1028 fallback for correct large artwork.
The common-patch manifest has SHA-256
`399cbc9ba7df164ca827154f851f286e37866f5097c28d061ebb9204eb1ccf69`;
the resulting 20,000-byte F1028 file has SHA-256
`c12a671d2107ce9d5bc235c4b3072a8b90c1fe9145964c36f4714d0556841b77`.

The campaign uses the earlier fixed headless navigation sequence: language
selection, Music → Songs → `Corner Test`, small Now Playing art, then large art.
Clock, battery, and RTC remain pinned. Its base options are:

```text
30000000000 --boot-osos --osos-from-disk --sysinfo --bcm --pmu
--disk-writable --clock=5 --battery=100 --rtc=2026-10-11T12:00:00
--flash=<synth-5g.bin> --disk=<worker.img> --drive
```

This is still warm-entry RetailOS with synthesized BCM replies, not execution of
Apple's original NOR bootloader. Firmware, synthetic NOR, and pristine base-image
hashes are inherited from the [earlier experiment](ipod-emulator-experiments.md).

The recorded baseline bytes are zero at all seven target locations. MHNI `0x24`
is tested separately in the two representations:

| Target | File offset, decimal | Width | Initial campaign values |
| --- | --- | --- | --- |
| MHNI F1028 `0x24` | ArtworkDB 532 | 4 bytes | `0xFFFFFFFF` |
| MHNI F1029 `0x24` | ArtworkDB 696 | 4 bytes | `0xFFFFFFFF` |
| MHII `0x1C` | ArtworkDB 348 | 4 bytes | `1`, `0x80000000` |
| MHII `0x24` | ArtworkDB 356 | 4 bytes | `1`, `0x80000000` |
| MHIT `0x84` | iTunesDB 564 | 4 bytes | `1`, `0x80000000` |
| MHIT `0x94` | iTunesDB 580 | 4 bytes | `0x01010100` |
| MHIT `0xB3` | iTunesDB 611 | 1 byte | `1`, `0x80` |

These are the plan's initial cases, not a claim that all have finished. A separate
known-field sensitivity control changes F1029's **offset** at MHNI `0x14`, file
offset 680, from zero to 80,000: exactly EOF of its 80,000-byte file. It does not
change the unknown MHNI `0x24` field.

### Instrument validation and build provenance

The two initial display controls used trace SHA-256
`1df025c3cd6176efa0ff992b666dfb90dfba8af20bf1e2a9166c1559fa705236`
without enabled field-read watches. An attempted rebuild while they ran failed
because Windows locked the executable; its unchanged hash was verified. Their
`provenance-caution.json` records why they remain eligible as **display controls**,
not validated unknown-field read traces.

Subsequent watched runs use a copied, hash-checked executable. The completed
instrumentation build records:

```text
trace executable
d4f7410ce3e6854fc03a40481ae540256977f71fc6c92a5d54fe82c6f06ced03

field-instrumentation.patch
2d5b029a77af51090b1008919c4861eb2cef9dd080227d4a07917c6c7086b6bc

instrumentation-provenance.json
ba018dd2b61d25d9afaddf4bcb34be8071252b600f1fdc33648350dba169bddc
```

The recorded checks passed: six trace tests, four read-log tests, three fast-word
path tests, and 25 peek tests. The patch logs the actual returned bytes on fast
RAM word reads, makes machine watches inspect backing memory without dynamic
MMIO reads, excludes post-execution reporting/dumps from firmware read accounting,
and exports all ordered ATA read-DMA transfers. DMA ordinals are not instruction
timestamps. These changes are local research instrumentation; they do not change
iOpenPod format definitions.

`dma-field-map.json` supplies candidate watch addresses from DMA placements.
The same buffer can later hold unrelated data; an address hit does not retain
permanent provenance as an ArtworkDB or iTunesDB field. Alias addresses and copies
must be accounted for before interpreting a consuming PC. Instrument unit tests
also do not establish that every firmware access path is covered.
Watch lists grew during the campaign; total read-row counts across different
lists are not directly comparable measures of field use.

## Measurement standard

An observed memory read is not sufficient to name a field. Separate:

1. **Bulk loading/copying:** the byte range was fetched or copied along with a
   record. This establishes transport only.
2. **Field consumption:** a width-correct read from a known record or derived
   object reaches a comparison, bit operation, table lookup, or stored state.
3. **Behavioral effect:** a controlled value change alters the predicted branch,
   state, file access, or display, and a fresh baseline repeats the old result.

For every result retain the exact firmware, emulator build and instrumentation
patch hashes; input image and changed-file hashes; relative and absolute offsets;
access width, PC and instruction count; commands; logs; and lossless captures.
Validate the read-logging instrument with a known-field positive control before
interpreting an absent trace. A monitor that misses fast reads, another core,
address aliases, or accesses after a copy cannot establish that a field is unused.

An unchanged final screenshot supports only “no visible difference under this
workload.” A crash with `0xFFFFFFFF` supports only rejection or disruption under
that intervention until the consuming operation is traced. Neither is a field
definition. A derived runtime offset must be recorded separately from the
on-disk Chunk offset.

## Results

`campaign-verification.json` records verification of all **19 completed runs**:
exit code 0, five intact PNG captures per run, unchanged tested database/media
files after execution, matching hashes for retained harness/executable/address
files, and no saturated read logs. All four baselines and the five cases with
no visible difference match all five original baseline PNGs. The three intervention
repeats reproduce their respective final captures. The verification report's
SHA-256 is `0eebdb92aabc8204da88657ba0438f7c7f3e3d38627e0b656fb3ad380756b67e`.

The last fresh baseline, `baseline-after-matrix`, again restores the exact cyan
small view and quadrant large view. It retains all 382,808 read rows with the
expanded watch list. Its `report.json` has SHA-256
`00976cc414c67fe32788b92ddbe0b0e26c58b736fcd671cb7e2410949954eb7a`.
These checks establish repeatability within the recorded emulator configuration;
they are not independent physical-device validation.

### Initial display controls

Both controls completed with trace exit code 0. Their captured large views were
visually inspected, and `pixel-analysis.json` records exact pixel comparisons:

| Case | Small view, 10,000 pixels | Large view, 40,000 pixels |
| --- | --- | --- |
| Common baseline | Exactly matches the cyan sentinel. | Exactly matches the expected quadrant image. |
| F1029 offset set to EOF | Exactly matches the same cyan sentinel. | All 40,000 pixels are black; every pixel differs from the expected quadrant image. |

The small comparison region is `[16,65,116,165)` and the large region is
`[60,32,260,232)`, expressed as left/top/right/bottom with exclusive right/bottom.
This establishes that the selected artwork screen reacts to a bad F1029 byte
range and does not simply enlarge the available cyan F1028 image in that case.
It does **not** identify any unknown field or establish why the large view becomes
black rather than showing another error presentation.

| Control artifact under `field-lab/runs/` | SHA-256 |
| --- | --- |
| `baseline/pixel-analysis.json` | `0cbc4f8006b13740d2e242c5f6cc9279a1fed8b3dba8a801df78a9b9af111dbd` |
| `bad-1029-offset/pixel-analysis.json` | `60614c2a5b937cc7df4a3d10d852175476282a8b65e6f7d0b90e0ef768376f31` |
| `baseline/large.png` | `86d7d445c0685d0ec24f7536c708a1778c37ff650db5bceafa093cc69fa0d8ef` |
| `bad-1029-offset/large.png` | `95766edca8f42d0549ff687f8877728516f4e87dfe8751b54b2d7476b2617f5e` |

`bad-1029-offset-traced` repeats that control with the corrected instrumentation
and expanded watch list. Its small and large captures are byte-identical to the
first bad-offset run, including the all-black large region. It exits with code
0 and retains all 375,478 reported read rows. Its `report.json` has SHA-256
`ca637611c6e6c543cf483e42df99d5143ee564b102cb2aedbf57caed93bac83b`.

A separate known-field control changes MHIT duration `0x28`, iTunesDB file
offset 472, from 30,000 to 60,000. The small Now Playing capture changes its
remaining-time label from `-0:30` to `-1:00`; both artwork regions remain exact
matches and the final large capture is unchanged. This provides a visible
iTunesDB-field sensitivity control. The run completed with exit code 0 under
the corrected instrumentation build. Its `mhit-duration-60000/report.json` has
SHA-256 `49c89e9afd4c4f98028c22765e0e99b0c8205ecc8a0c80b8951959c6f1e1bd6e`.
This observation alone does not validate watches for every unknown MHIT field.

### Unknown-field trials

The corrected-instrumentation baseline (`baseline-traced`) completed normally and
reproduced the original baseline's small and large captures byte for byte. The
following watched interventions each change only F1029 MHNI `0x24`, ArtworkDB
file offset 696, from zero. Every listed run exits normally with code 0.

| MHNI F1029 `0x24` | Initial small Now Playing checkpoint | Final checkpoint under the same inputs |
| --- | --- | --- |
| `0`, baseline | Cyan sentinel. | Expanded 200×200 quadrant art. |
| `0xFFFFFFFF` | Byte-identical to baseline. | Ordinary Now Playing layout, cyan small art, track text, and progress/seek bar. |
| `1` | Byte-identical to baseline. | Ordinary Now Playing layout with a blank white small-art box. |
| `5000` (`0x1388`) | Byte-identical to baseline. | Same final capture byte for byte as value `1`. |
| `10000` (`0x2710`) | Byte-identical to baseline. | Same final capture byte for byte as value `1`. |
| `0`, fresh `baseline-revert` | Byte-identical to baseline. | Restores the expanded quadrant view byte for byte. |
| `0xFFFFFFFF`, fresh repeat | Byte-identical to baseline. | Reproduces the first `0xFFFFFFFF` final capture byte for byte. |

The final states were visually inspected. **They are different UI states, not
malformed 200×200 images.** For example, the automated fixed-crop comparison for
`0xFFFFFFFF` reports 39,600 differing pixels, but that rectangle now includes
controls and text; it must not be described as 39,600 corrupted artwork pixels.

These display observations establish that this word affects the observed
selection path, and that the tested nonzero values do not all behave alike.
Screenshots alone do not establish a millisecond timestamp, signed integer,
flag mask, or general interpretation of `0xFFFFFFFF`. In particular, the initial and
final checkpoints also differ in playback position and button history. The
fresh baseline makes a persistent effect from earlier runs less plausible.
Additional values and consuming caller dataflow remain to be investigated.

| Artifact under `field-lab/runs/` | SHA-256 |
| --- | --- |
| `baseline-traced/report.json` | `bebd6509142c252c798ffa65bada825f1eb063e780afe122ed09225fd551d7ba` |
| `mhni-1029-24-ffffffff/report.json` | `8b1b35d91eac5a29b1c5190f3c22d1cd9e73e4c884eb6620bccb8f6c681c6921` |
| `mhni-1029-24-ffffffff/large.png` | `560eb8d99d038cc96a13d7eaf4b86845276a067cfcaf8d6ebbac105981aa37c1` |
| `mhni-1029-24-00000001/report.json` | `0445258e32bf13cc9e0362ce141c4ed8f92b0fad20e11efa1dbd7091cd5f098c` |
| `mhni-1029-24-00001388/report.json` | `87dd9a2d26a9428baf7d79f984248bec3a21a349d3ce34888d88ae55d9822b2a` |
| `mhni-1029-24-00002710/report.json` | `09907a495bc2d91c4e012947c6589bbc67ce23c0b1f8f3ba6d6291a3b21c69c8` |
| `baseline-revert/report.json` | `366282d141509903bcaaf18caff4b7e98a844bbd6686456b63d83ed752b3aacc` |
| `mhni-1029-sentinel-repeat/report.json` | `631f0faef313fe78feaf739033ba773f3131446bb443d37f5c0b0fac6a5f7602` |
| All three finite-value `large.png` captures | `e2d308aa06aab6a913d8bbf4e0cd5ef930087c8532c92a26954c02f8039abcfb` |
| All four intervention `playing.png` captures | `d24d17eb33d281616958837fb188814775d502e21538298d063a985aff55b964` |

Changing **F1028's** MHNI `0x24` to `0xFFFFFFFF` is a separate intervention at
ArtworkDB file offset 532. The initial Now Playing capture has no small-art box:
track text shifts left into the space previously occupied by artwork. The final
checkpoint retains that
text-only layout with playback paused around 11 seconds; it does not reach the
expanded image. Both captures were visually inspected. The run exits with code
0 and preserves the five tested files. Its `mhni-1028-24-ffffffff/report.json`
has SHA-256 `b5b5db7cbb187fe6fb597f22eebc1561d11894ca828897d48a3e0aab177d7f5b`.
This further shows why a fixed coordinate crop cannot identify artwork corruption
without first checking the screen layout.

### Other candidates: bounded negative results

These completed cases each produce the same five PNG captures as the baseline,
byte for byte. They exit with code 0 after 755,118,195 CPU instructions, retain
all 375,620 reported read rows, and leave the five tested files unchanged:

| Field | Value tested | Run under `field-lab/runs/` | `report.json` SHA-256 |
| --- | --- | --- | --- |
| MHII `0x1C` | `1` | `mhii-1c-00000001` | `09a99195f3d3618b80d01b246db4e030290f6febc79a9ca2624da2b4748d2d7e` |
| MHII `0x24` | `1` | `mhii-24-00000001` | `21cffbe6a2d02d141f03083b37d32e478dc22554c95bf1e23031db1b25343d86` |
| MHIT `0x84` | `1` | `mhit-84-00000001` | `45ce82a96bb6e9555b072dda5bad716b4e426faa087dd8bd78e2dfb42a5b9727` |
| MHIT `0x94` | `0x01010100` | `mhit-94-01010100` | `96fb1caac96df548b483563ffdbd4a17f2828ccca4f36473f1930f39abec2455` |
| MHIT `0xB3` | `1` | `mhit-b3-01` | `fcc7b57cb90262fbbc25704046b742c8381b07960e07f0274f29f8ebfc73fadd` |

This establishes **no observed difference under this plain-MP3 workload**.
It does not name these fields, establish valid value ranges, or show that they
are universally ignored. In particular, this workload does not exercise a Store
or DRM-specific track path. The high-bit probes prepared in the initial plan
were **not executed**: MHII `0x1C`/`0x24` and MHIT `0x84` at `0x80000000`, and
MHIT `0xB3` at `0x80`. The broader values and feature workloads proposed earlier
also remain untested unless explicitly listed in these results.

The local `itunes-consumer-analysis.md` adds a narrower parser finding. Breakpoint
`0x000D79C4` identifies the temporary MHIT header at `0x13E61B94`; the later
716-address watch list covers the three candidate ranges and a duration control
through four SDRAM aliases. Parser PC `0x000D7A40` actually reads duration
`30 75 00 00` from raw MHIT `0x28`. No PC in the inspected main-parser range
`0x000D7800..0x000D8AFF` reads the watched raw `0x84`, `0x94`, or `0xB3` ranges
in these trials. Static decoding likewise skips those bytes; a neighboring load
at `0x000D7B88` reads `0xB2`, not `0xB3`.

The changed bytes do reach the firmware through bulk-copy PCs `0xFC`/`0x104`.
Later reads at the same stack addresses contain unrelated data after stack reuse
and are not MHIT field consumers. This supports **non-consumption by the observed
parser path**, not universal non-use. The earlier 656-address runs did not watch
these temporary-header locations, so their absent rows cannot support that
negative finding. Raw on-disk offsets, temporary stack addresses, and derived
track offsets must remain distinct.

The final baseline allows a direct trace comparison: filtering its expanded
908-address watch set down to each MHIT trial's original 716 addresses yields
exactly 375,620 rows. Each ordered sequence matches the corresponding trial in
PC, address, value, and instruction count except for the deliberately changed
bulk-copy bytes: one byte for `0x84`, three for the `0x01010100` word, and one
for `0xB3`. The semantic duration read and subsequent stack reuse match too.
This is stronger evidence for the bounded non-consumption finding than screenshot
equality alone; it still does not cover other media or firmware paths.

### MHNI parsing and selection: static and dynamic evidence

The local `artwork-consumer-analysis.md` records disassembly from the baseline's
SDRAM dump, SHA-256
`cbd6e31c124612f5e4d2edd2e7bb6b1138034ff8775738b3fe965cc4790e248d`.
The decoder is the emulator's own `dis.exe`, not an independent disassembler.
For this firmware, parser `0x000DDD64` loads raw MHNI `0x24` as a constructor
argument; constructor `0x000A9164` stores it at **runtime node `0x0C`**. These
offsets name different layouts. Format ID is runtime node `0x08`, with file
offset and length at `0x18` and `0x1C`.

The statically decoded selector beginning at `0x0009A27C` first matches format,
then reads node `0x0C` at PC `0x0009A2A0`. Its exact-match path requires equality
with the requested key; its other path selects an exact match or the greatest
unsigned key no larger than the request. Wrapper `0x0009A270` requests an exact
zero key, while `0x0009B100` allows the other path. This establishes how the
decoded routine uses a key; it does not establish the key's unit or every caller.

The `baseline-revert` and `10000` runs validate part of this path dynamically:

- Constructor stores identify the same F1029 node at `0x13DCA10C`, with parent
  `0x13DCFEC4`, format 1029, and key at `0x13DCA118`. The key is zero in the
  baseline and `0x2710` in the intervention.
- Selector PC `0x0009A2A0` reads the F1028 key once in the baseline, and 52 times
  in the intervention. It reads the F1029 key once in the intervention.
  Getter PC `0x0012CA84` reads both keys once in each run.
- Each word read produces four byte rows. The entire logs retain respectively
  13,048 and 14,912 rows, matching their reported totals. These are semantic
  object reads, unlike the earlier DMA-address hits in a bulk-copy routine.

The reports also verify that the five tested database/media files remain
unchanged after both runs. Together with the reversible display effect, this
supports a **thumbnail-selection key** interpretation for this firmware. Further
copies and cached objects must be followed before claiming that this one selector
accounts for the entire final-screen difference.

| Dynamic artifact under `field-lab/runs/` | SHA-256 |
| --- | --- |
| `baseline-revert/reads.tsv` | `7c0fb875f51ddea4d4f9ef40ff1ec4f647418c9c88221886ebca599901738957` |
| `baseline-revert/stores.tsv` | `81cda5864d3e3b477d32df5ff3682558fecbfe4f79d3a7447087977949f4d437` |
| `mhni-1029-24-00002710/reads.tsv` | `b86c3b70c1a70297424f49f172c0fadb63835ab3a1abbcedf3f27c2822ef36e0` |
| `mhni-1029-24-00002710/stores.tsv` | `09af7f226e2447d95951b48e38a3160786535fd7076f67514aab5683b0fe034b` |

### Playback-position evidence and remaining semantic limits

The sentinel repeat adds four full register snapshots immediately after the
selector loads the key, at `0x0009A2A4`. All identify the F1029 node, stored key
`0xFFFFFFFF`, and non-exact selection mode. Requested keys in r4 are 13,322,
14,236, 15,177, and 14,785; r11 carries the same values. The last value decreases,
so these snapshots should not be described as a monotonically increasing clock.
The preserved source is `mhni-1029-sentinel-repeat/trace.log`, lines 905–924,
SHA-256 `e6b5465e3a31299d6af8bdaa3c8463f56ced694d18823908488e003c74b019a9`.

Static caller analysis connects this request to playback state:

1. At `0x001EB508`, r11 is passed to wrapper `0x0009B100` as the selection key.
   Its enclosing function receives r11 through its fifth argument.
2. Caller `0x001E88AC` supplies the result of getter `0x001E9BC4` as that argument.
3. The getter's normal path reaches `0x0009BB30`, which returns the smaller of
   two engine fields at `0x2778` and `0x2998`, subject to another state flag.

Final RAM contains respectively 14,733 and 30,000 in the baseline, and 15,673 and
30,000 in the `10000` run, for the known 30-second fixture. The visible playhead
is around 14–15 seconds. Combined with the duration control, actual requested
keys, unsigned nearest-prior selection, and foo_dop's independently documented
producer behavior, this **strongly supports a playback-start position measured
in milliseconds for this firmware path**.

The register snapshots prove the selector's inputs; the complete caller chain
above is statically decoded, not an instruction-by-instruction dynamic trace for
every snapshot. No paired-image boundary-switching experiment has yet established
all timing rules. `0xFFFFFFFF` exceeds the observed requested positions under an
unsigned comparison, but a universal sentinel meaning or special-case branch has
not been established. Chapter-art support, PhotosDB use, and other firmware still
require separate evidence.

### Cache groups and the finite-value effect

Static analysis follows getter `0x0012CA84` into a cached object's `0x1C` field
and then a group's `0x04` field. This getter returns the key; it is not itself a
display-mode gate. Final RAM, interpreted with that construction path, contains
one zero-key group with both formats in the baseline. The `10000` intervention
instead has a zero-key group containing F1028 and a 10,000-key group containing
F1029.

The decoded cache pipeline selects a key group before looking for the requested
format within that group. No search back through older groups is visible in that
decoded format-miss path. This is a plausible explanation for losing small art
after reaching a nonzero key whose group contains only the large representation.

The `mhni-1029-10000-cached-repeat` run reproduces the earlier `10000` captures
byte for byte and supplies dynamic evidence of this cache path:

- Store PC `0x00205FD0` writes keys zero and 10,000 into the respective cached
  objects; PC `0x002060F0` writes those keys into their groups.
- PC `0x00205D7C` reads the 10,000 group key 226 times and the zero group key
  115 times. Early traversals inspect 10,000 followed by zero; later comparisons
  inspect only 10,000. All 391,313 reported read rows are retained.
- The run records 341 hits at the subsequent comparison, `0x00205D80`. Those
  include two retained full-register snapshots with group key 10,000 in r1,
  requested key 15,673 in r6, and non-exact mode in r7. These inputs satisfy the
  decoded rule for selecting the 10,000 group. Adjacent original-node selector
  snapshots request the same playback position.

Thus propagation and a cache comparison accepting key 10,000 at playback
position 15,673 are observed. The trace retains only a subset of full register
dumps, so it is not a complete numerical selection history. Responsibility for
each UI transition remains partly inferred. Separate exact-zero helpers retrieve
dimensions and file information; the visible results must not all be attributed
to a single selector.

| Cached-repeat artifact | SHA-256 |
| --- | --- |
| `report.json` | `05422740c27f3e8ff43d4def977643acfdddabb1d847da1be8312d8ce3304175` |
| `stores.tsv` | `1d303daef4e7518a5ccd68ce1d800065ad3146a46c0af388f64acc48f4a994d3` |
| `reads.tsv` | `79e6510c8c68394bba47e7856cf94de95730f0ce4d041694358257143f851975` |
| `trace.log` | `507ce05546d120d303e856783a2676658a50907caca1d64549e5c3cfde8e668a` |

## Repository implications

Keep unknown names, widths, and retained bytes unchanged unless stronger evidence
supports a separate reviewed decision. ADR-0006 requires byte-exact unchanged
round trips; ADR-0116 distinguishes bounded Unknown Data from malformed input.
ADR-0008 keeps format facts in one shared definition path, and ADR-0025 requires
verification of retained native fields after unrelated edits. A successful
emulator probe is research evidence, not authorization to normalize unknown
values. [ADR-0006](../../adr/0006-require-lossless-ipoddb-round-trips.md),
[ADR-0116](../../adr/0116-retain-bounded-unknown-data-with-log-only-diagnostics.md),
[ADR-0008](../../adr/0008-require-one-definition-driven-ipoddb-path.md),
[ADR-0025](../../adr/0025-resolve-library-edits-before-reconciliation.md).

Equal MHII/MHNI layouts in ArtworkDB and PhotosDB do not make those artifacts or
their workloads interchangeable. Photo-specific hypotheses need a PhotosDB
experiment. [ADR-0052](../../adr/0052-model-photosdb-as-a-distinct-artifact.md).

[current-mhni]: https://github.com/TheRealSavi/iOpenPod/blob/b246a6c26c1402c79b690febdcb914862ce0a8bc/src/iPodDB/ArtworkDB/shared/chunk_defs/mhni.py#L12-L23
[current-mhii]: https://github.com/TheRealSavi/iOpenPod/blob/b246a6c26c1402c79b690febdcb914862ce0a8bc/src/iPodDB/ArtworkDB/shared/chunk_defs/mhii.py#L13-L23
[current-mhit]: https://github.com/TheRealSavi/iOpenPod/blob/b246a6c26c1402c79b690febdcb914862ce0a8bc/src/iPodDB/iTunesDB/shared/chunk_defs/mhit.py
[original-mhni]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/artworkdb_shared/mhni.py
[original-mhii]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/artworkdb_parser/mhii_parser.py
[original-mhit]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/mhit_defs.py#L98-L128
[original-observations]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/docs/research/classic65g-itunesdb-field-observations.md
[gpod-struct]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-itunes-parser.h#L556-L590
[gpod-mhit-read]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L2538-L2568
[gpod-mhit-doc]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb.h#L1432-L1491
[foo-chapters]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L735-L815
[foo-lookup]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.h#L80-L90
[foo-mhni-write]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L1149-L1163
[foo-mhii-write]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L1182-L1193
[foo-mhit-write]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/writer_itunesdb.cpp#L629-L655
