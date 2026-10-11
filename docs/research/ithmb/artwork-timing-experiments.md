# Artwork timing experiments

Research date: **2026-10-11**. This is a follow-up to the separate
[19-run database-field campaign](database-field-experiments.md). That campaign
established reversible display effects from MHNI `0x24`, runtime propagation,
and comparisons against values strongly supported as playback milliseconds.
It did not demonstrate a complete pair of artwork representations switching
across a time boundary. **Eight new runs** show automatic small-art switches during
ordinary MP3 playback, with no added chapter metadata, and order-dependent selection.
Selection precedes the visible image change; a backward-seek attempt did not move
the playhead backward. This report
separates new measurements from the earlier runs and from still-proposed cases.

The target remains Apple `iPod_20.1.3` in the synthetic Video 5G emulator
configuration, using F1028 and F1029. This is not physical-device validation,
evidence for every Video firmware, or a result about Classic/nano F1061.
No application behavior, format definition, writer default, or shard cap changes
are part of this investigation.

A subsequent [physical Classic readback](classic-timed-artwork-readback.md)
documents a reported failure to switch at 15 seconds despite persisted timed
groups. See [the count and chapter-format comparison](artwork-count-and-classic-timing.md)
before applying this Video result to Classic authoring policy.

## Source constraints

The pinned foo_dop implementation supplies a useful production hypothesis:

- It adds chapter images as image-name records under the track's existing image
  item. Each eligible chapter-artwork format receives the chapter's position as
  MHNI `display_start_time_ms`. Chapter formats come from a separate capability
  list and pass media-type filters; ordinary cover formats are handled separately.
  [Artwork production][foo-artwork].
- MP4 chapter positions are calculated as sample time × 1000 / track timescale.
  The extractor replaces position zero with one and merges text/image samples
  at equal positions. JPEG entries retain image data and a `ploc` reference.
  [Chapter extraction][foo-extraction].
- Artwork production converts chapter position **1 to MHNI key 0**. That branch
  also causes the ordinary cover to receive `0xFFFFFFFF`. Literal input position
  zero does not set this flag in the inspected code. These are precise producer
  choices, not universal normalization rules. [Artwork production][foo-artwork].

foo_dop writes chapter metadata separately as iTunesDB MHOD type 17. Its chapter
writer emits a `sean` container with `chap` entries, optional name/URL/location
children, and a `hedr` entry. The chapter's position is stored in the `chap`
header; the payload is not an MHNI list. libgpod also documents the first chapter
position as one, with positions measured in milliseconds.
[MHOD writer][foo-mhod], [type identifier][foo-type],
[chapter payload writer][foo-chapter], [libgpod chapter model][gpod-chapter].

In its import flow, foo_dop extracts and serializes this chapter list in the
`mp4 || m4a` branch, then passes the track's list into artwork production.
This does not provide a tested MP3 chapter-artwork example.
[Import path][foo-import], [artwork call][foo-artwork-call].

These sources establish what producers write. They do **not** establish that
MHOD 17 or an embedded MP4 chapter track is required for this firmware to select
timed ArtworkDB images. An artwork-only test with an otherwise unchanged MP3
can answer that narrower question. A negative result would not rule out timed
artwork with valid chapter metadata.

The source's image-name lookup also treats requested time `0xFFFFFFFF` as a
wildcard while matching a format; updates and new-item construction therefore
need separate scrutiny. This lookup behavior must not be mistaken for Apple's
runtime interpretation of an on-disk `0xFFFFFFFF` value.
[Lookup][foo-lookup], [new versus existing image handling][foo-update].

## Hypotheses and proposed comparisons

The earlier firmware analysis found a cache that groups representations by the
MHNI key, then selects a format within the chosen group. Giving only F1029 a
nonzero key separated it from the zero-key F1028 representation. This motivates
testing complete pairs at each time, rather than treating the earlier blank
small-art result as a malformed raster. The underlying measurements and their
limits remain in the [prior campaign](database-field-experiments.md).

| Hypothesis | Discriminating comparison | Evidence needed |
| --- | --- | --- |
| The key is an artwork start position in playback milliseconds. | Two distinguishable images of each format at keys 0 and 10,000; observe playback before and after the boundary. | Parsed records, actual firmware playhead/requested key, selected group, and exact displayed pixels. |
| Every needed format must be present in the selected time group. | Compare a complete pair at the second key with the earlier split-format case. | Small and large views, with group/format lookup traces; distinguish absent artwork from changed screen layout. |
| Timed artwork selection can operate without chapter metadata. | Keep the MP3 and iTunesDB chapter metadata unchanged while adding the time-indexed ArtworkDB records. | A verified timed switch under that input; record explicitly whether MHOD 17 exists. |
| Selection uses playback position rather than elapsed emulator time. | Pause or seek across the boundary with controlled inputs. | Actual requested key and selected representation, not a wall-clock estimate. |
| Cache behavior depends on representation order. | Reverse time groups without changing their keys/pixels; separately reverse duplicate same-key images. | Actual MHNI order, cache vector order, selected entries and displayed pixels. |

These hypotheses defined the experiment design. Executed cases, exact key
values, image identities, and command sequences are recorded in the saved
timing-lab manifest and run reports below. Chapter-bearing audio, PhotosDB, other
models, and further ordering/duplicate-key combinations require their own controls.

The local independent analysis, `timing-lab/artwork-timing-analysis.md`, supplies
specific static predictions for this firmware. Original-node selector
`0x0009A27C` finds the largest eligible key for a format; cache selector
`0x00205D48` scans the group vector backward and accepts the first eligible key.
Those algorithms can disagree when insertion order is not ascending. Construction
appends new groups and discards a later duplicate format within an existing key
group. Reversed-order and duplicate-key cases can test those predictions.

The same analysis finds artwork refresh bounds at UI-object `0x530`/`0x534`.
The decoded path requests a refresh when the playhead falls below the lower
bound, or reaches a nonzero upper bound. No chapter-metadata gate appears in that
examined path. These are static findings from the previously hashed firmware
dump, decoded with the emulator's own ARM decoder; they do not establish which
paths run in a new fixture or when pixels become visible.

## Method and evidence requirements

The new campaign is isolated from the completed `field-lab` runs. Every executed
case must preserve a hashed input, an independently checked ArtworkDB record map,
payload hashes, commands, executable/harness hashes, watch addresses, trace logs,
lossless captures, and post-run readback. Adding MHNI records necessarily changes
ancestor lengths/counts and image-file allocations; record those structural
changes rather than describing the fixture as a one-word patch.

Keep the same track, firmware, synthetic NOR, base image, iTunesDB version and
`0x148` MHIT header unless a case explicitly tests another input. Use distinct
small and large images and distinct earlier/later images so a scaled fallback
cannot imitate the expected result. Validate the indexed byte ranges against
independently decoded payloads before booting.

An emulator wait duration is not the audio playhead. Capture the actual firmware
position used by the selector alongside the image. Screenshots before/after a
boundary bracket a transition; they do not locate its exact onset. A single
forward switch does not establish reverse seeking, pause behavior, ordering
independence, or all sentinel semantics.

Instrumentation must not supply the requested key, selected image, or pixels.
Separate firmware comparisons from synthesized BCM display operations. Confirm
run-specific object addresses after allocation; changing record counts can move
objects. A read from a previously identified address alone is not field
provenance. Retain the read-log counts and caps, and repeat the unchanged control
after interventions.

## Prepared campaign

The lab is `C:\Users\JohnG\Coding\ipod-emulator-lab\timing-lab`. Its manifest
also resides at `.scratch/ithmb-emulator/timing-lab/manifest.json` in iOpenPod;
SHA-256 `2385431b24c21a9c02fdb112a44099e76a1ffa4ca2d30d4d78d8c8368412eb6b`.
All six prepared cases retain the same MHII and opaque MHOD type 6, cloning
complete MHOD type 2/MHNI representations and updating their enclosing lengths
and counts. The manifest records exact MHNI file offsets, keys, and payload ranges.

| Case | MHNI group order | Purpose |
| --- | --- | --- |
| `single-zero` | A at 0 | Single-pair display and telemetry control. |
| `both-zero-ab` | A at 0, B at 0 | Duplicate same-key/same-format behavior. |
| `both-zero-ba` | B at 0, A at 0 | Duplicate order reversal. |
| `timed-10000-ab` | A at 0, B at 10,000 | Ascending timed complete pairs. |
| `timed-10000-ba` | B at 10,000, A at 0 | Same times/pixels with reversed record order. |
| `timed-5000-ab` | A at 0, B at 5,000 | Shift the proposed boundary while retaining the same images. |

Each group contains 100×100 F1028 and 200×200 F1029 representations. A uses a
cyan small image and quadrant large image; B uses a magenta small image and blue
large image. Each includes distinctive markers. Both iTHMB files contain A then
B in **every** case, including the single-pair control. Thus payload contents,
iTunesDB and MP3 remain identical across all six filesets; ArtworkDB references,
keys and record order distinguish the cases. No chapter metadata is added.

The base is the earlier initialized image, SHA-256
`b15d7809e8a8292557d66d43c9336bbac76d477b160f9e9459fe82b33a74fe43`.
The shared iTunesDB retains SHA-256
`2ceaecf905f99a6a8598902df4297ed88ff353a48ca82af0c3b948de078164aa`.
F1028 contains 40,000 bytes with SHA-256
`88a8374ae4466ba1dd4201b87716dc3a97f317bc0062aa4f4c000e11c58d653b`;
F1029 contains 160,000 bytes with SHA-256
`1f7d8da2b831d75a67e25715b98dd56ef6ce3008ab4939fd105ce8240d6b2ab5`.

### Protocol and observation tool

The first protocol uses the established route into Now Playing, then waits
without button input. It captures `playing-plus-00`, `04`, `08`, `12`, `16`, and
`20`; these names mean added emulator wait time, not media position. After each
capture, it observes the firmware's position/end words through pointer chains:

```text
peek-chain 0x1081da18 0x1c 0xca0 0x4 0x2778
peek-chain 0x1081da18 0x1c 0xca0 0x4 0x2998
```

The new generic observer reads backing memory without CPU steps or dynamic MMIO
reads, reports every pointer hop and the current instruction/time counters, and
does not add firmware read-log events. Its paths derive from this specific
firmware's earlier analysis; it does not identify playback fields automatically.
The recorded eight trace tests pass, including two pointer-observation tests.
`instrumentation-provenance.json` has SHA-256
`737bdf27584eb569e9ff67cf85334919f5a3803661b572ca0d6f8c5597fedc9a`.

| Instrument | SHA-256 |
| --- | --- |
| Timing trace executable | `a94c19ee05cf6a200d76ae2108f8b954346a91daf08294ba0ee2c65f9bb7690c` |
| Cumulative patch against emulator commit `d39e850ac07baa28abbdd8b00b77b834a757b5e1` | `6c14753cec9e006209ead3ad0e1826dc4d88282d9db5f1405fbe3bf128968f4a` |

Later runs also observe UI interval words through `0x1081da18` plus `0x530` and
`0x534`. Two follow-ups reuse the unchanged `timed-10000-ab` fileset. The dense
run captures every 500 ms of emulator time after `playing-plus-08`. The probe
named `timed-10000-seek` continues after `playing-plus-20` with Select, rotation
−32, then Select, with waits and telemetry between inputs. Its filenames record
the intended steps; they do not prove a seek occurred. Each run retains its own
harness and exact command sequence.

## Results

All six core cases and two follow-ups completed with exit code 0, retaining
**98 captures**. `audit_timing.py` independently
checks raw records, input/output file hashes, telemetry, and exact RGB565 pixel
matches; results are in `timing-audit.json`. The runs retain the same iTunesDB,
whose track MHOD types are 1, 4, 3, 2 and 6: no type 17 chapter metadata exists.
All five tracked files match before and after each run, and recorded store logs
are not saturated. No further runs are queued.

| Run | Observed playback positions in ms | Exact 100×100 image at those checkpoints |
| --- | --- | --- |
| `single-zero` | 365, 365, 365, 6,768, 9,064, 10,997 | A throughout. |
| `timed-10000-ab` | 2,716, 3,712, 7,758, 9,691, 11,911, 14,001 | A at the first four; B at the final two. |
| `both-zero-ab` | 2,742, 5,146, 7,105, 9,067, 11,287, 13,583 | A throughout. |
| `both-zero-ba` | 2,716, 4,649, 7,418, 9,116, 11,049, 12,982 | B throughout. |
| `timed-10000-ba` | 2,716, 5,015, 7,105, 9,067, 11,313, 13,583 | A throughout, despite passing the 10,000 key. |
| `timed-5000-ab` | 2,716, 3,712, 8,019, 8,544, 12,643, 14,680 | A at the first two; B at the final four. |

Each match compares all 10,000 pixels at screen rectangle `[16,65,116,165)`
against the corresponding raw F1028 payload, with exclusive right/bottom edges.
The captures at 9,691 and 11,911 ms were also visually inspected: the ordinary
Now Playing layout stays visible while the cyan A image becomes magenta B.
There is no intervening button input.

This is direct evidence of an automatic timed image change for this firmware
configuration, with both representations supplied at each key and no chapter
metadata. The observations bracket the visible switch between 9,691 and 11,911
ms; they do not measure an exact 10,000-ms display-update instant. The unchanged
control stays A beyond 10,000 ms. The repeated early control position also
demonstrates why added emulator waits cannot stand in for measured playback time.

The timed run's execution evidence is more specific than the screenshots. Raw
records and constructed nodes retain the order F1028/0, F1029/0, F1028/10,000,
F1029/10,000; the cache holds two groups with both formats. Selector snapshots
at instruction counts 703,988,267 and 703,988,784 compare stored key 10,000
against requested position **10,057**, in non-exact mode. The UI interval changes
from `[0,10000]` to `[10000,10000]` at the subsequent logged stores. The repeated
last-group upper bound is an observed firmware value, not a claim that the image
has a zero-length display interval.

Thus firmware group selection after crossing the key is observed at 10,057 ms,
while the first retained screenshot of B is at 11,911 ms. Exact equality at
10,000 is still a decoded comparison rule rather than a sampled display event.

The duplicate controls distinguish record order from payload contents. At equal
key zero, AB displays A and BA displays B throughout the sampled positions.
Together with the inspected construction path, this supports **first encountered
representation wins for the tested same-key/same-format duplicates**. It is not a
claim about duplicates in every firmware or a recommendation to generate them.
Both runs build one zero-key cache group containing two format entries. Its
retained F1028/F1029 file offsets are 0/0 for AB and 20,000/80,000 for BA, matching
the first pair in each file order; the lower and upper interval values remain zero.

Reversing **different** time groups also changes behavior: `timed-10000-ba`
keeps A beyond 10,000 ms. Its actual cache vector is `[10000,0]`; the two recorded
floor-mode selections request position zero and choose the final zero-key group.
The lower/upper interval is then set to zero/zero, with no later interval stores.
No future boundary is armed, so the cached A image persists through 13,583 ms.
This is **not** an observed fresh selection of key zero at 13 seconds.

The same keys and pixels in ascending AB order switch to B. Thus record order
affects both cache selection and subsequent refresh behavior in this path. The
static reverse scan additionally predicts choosing key zero if called at a later
position; it must not be conflated with the original-node selector's
greatest-eligible-key algorithm.

Changing the ascending second key to 5,000 shifts the observed transition:
A is visible at 3,712 ms and B at 8,019 ms. A recorded cache selection requests
5,773 and chooses 5,000; interval stores change from `[0,5000]` to `[5000,5000]`.
This provides a second key-value intervention supporting
playback-time selection, with a coarse display-transition bracket rather than
an exact onset measurement.

| Report under `timing-lab/runs/` | SHA-256 |
| --- | --- |
| `single-zero/report.json` | `b89f999921b76f30845cce4e3583472c49ef1653b0b58ed5b1d2c536b62a6ddd` |
| `timed-10000-ab/report.json` | `7a8c88f54dbad7a33d0ca69a5a99b2bc25943d5364576423a2dc868a4351f5c2` |
| `timed-10000-ab/stores.tsv` | `20d5304ecd7663a2469aa771398a63a5ebcff4c4da5b576b0a5cf28298415b9d` |
| `timed-10000-ab/trace.log` | `bffe015c803b19d138cdb438a6ffbd6a62ecf6757ebf2b9e771df2c702945dee` |
| `both-zero-ab/report.json` | `b9d44ccc96d9f7f926a286d4bcda7c4a5623c429fa43569e5a05c769063628f7` |
| `both-zero-ba/report.json` | `ecd19ee00301a10a8cafb7958a9e53f97a5ac0f69ac360669db2deefef2478c4` |
| `timed-10000-ba/report.json` | `02aafa58cf130ecea0d8ded0409c4a6a80aa2afbec2da772f1d14d321ed27f42` |
| `timed-5000-ab/report.json` | `de47f05b05e7cbb2d3eb4336926053bd0a15994762f7673841f13edeb78e87fe` |

### Dense repeat: selection and the visible frame differ

The dense repeat reproduces the timed switch and separates internal selection
from display:

| Capture | Engine position, ms | Cached interval | Exact displayed small image |
| --- | --- | --- | --- |
| `playing-dense-08` | 9,691 | 0 / 10,000 | A |
| `playing-dense-09` | 10,057 | 10,000 / 10,000 | A |
| `playing-dense-11` | 10,736 | 10,000 / 10,000 | A |
| `playing-dense-12` | 11,102 | 10,000 / 10,000 | B |

The interval changes at instruction counts 703,989,433 / 703,989,692, before
`dense-09` at 704,163,280. `dense-11` and `dense-12` occur at 709,163,280 and
711,663,280. Their images were visually checked in addition to exact pixel
comparison. Later captures remain B through the final measured position 14,001.

Thus the first retained visible B frame follows selection of the new group.
The visible transition is bracketed between measured positions 10,736 and
11,102 ms in this repeat. **11,102 is not a newly discovered selection threshold**.
The captures do not isolate the cause of the delay or justify attributing it
specifically to BCM emulation, nor do they measure physical-device latency.

### Seek attempt and large-view result

The attempted backward-seek sequence did not demonstrate a backward seek.
After the initial forward switch, measured positions progress through 14,497,
16,431, 18,024, 20,506 and 25,495 ms. The observed playback-override indicators
remain zero. Therefore an unchanged later image is not evidence about whether
artwork restores correctly when seeking backward; that behavior remains untested.

The final `playing-seek-after-12.png` instead displays the large B representation.
All **40,000 pixels** in `[60,32,260,232)` match B's F1029 payload exactly, and the
screen was visually inspected. This is positive evidence that the later time
group's 200×200 representation renders in the large view at measured position
25,495 ms. It does not establish an automatic large-view boundary crossing.

| Follow-up artifact under `timing-lab/runs/` | SHA-256 |
| --- | --- |
| `timed-10000-dense/report.json` | `b4d8ed89f74965ca1b3b61fb2fa6694140342176172ff5bce7fcc429725da118` |
| `timed-10000-dense/playing-dense-11.png` | `d1d68797949a26d693dd831f5e75d21444c1d6b5a39ab6d56b1178476968d6f1` |
| `timed-10000-dense/playing-dense-12.png` | `710e4d94fdce4e4110898eff674ba4ef684f16fc78446a16caf9f0970043e2ea` |
| `timed-10000-seek/report.json` | `107b785badc87c0bdcefd570f8f4f032e12fd62fd95d0e6af45bbf221b8331e4` |
| `timed-10000-seek/playing-seek-after-12.png` | `85f041a538c164f1d35c1b62080c7ba6a1226cbc08176217e2e4c5c91c2b5977` |

### Final verification and limits

`campaign-status.json` records all eight completed reports, retained workers and
artifacts, and the unsuccessful seek interpretation. Its SHA-256 is
`64ebc63b1367cf0c86300d6ae89cd50b2b39c8e9bee8684f2a8ccb3040b37a9b`.
The independent `timing-audit.json` has SHA-256
`15b38bd919610c63df48887cdd3c490953790c0ebac334ce6c679bbcaabccb7b`;
its analyzer `audit_timing.py` has SHA-256
`afc52c859c732deb3005e4e70a5f3e1cc5d119b237aed5e1e57ebe113b53d637`.

This campaign supports timed, order-sensitive artwork selection on the tested
firmware path, without MHOD 17 chapter metadata. It does not settle successful
reverse seeking, pause behavior, exact equality at the boundary, automatic
large-view switching, arbitrary duplicate handling, sentinel values, PhotosDB,
or other device/firmware combinations. Those are future probes, not omitted
results from this eight-run campaign. The earlier 19 runs remain separate and
are not counted again. iOpenPod's format definitions and writing policy remain
unchanged.

[foo-artwork]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L746-L822
[foo-extraction]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/mp4.cpp#L972-L1006
[foo-mhod]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/writer_itunesdb.cpp#L536-L547
[foo-type]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/itunesdb.h#L241-L249
[foo-chapter]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/chapter.h#L127-L199
[gpod-chapter]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb.h#L824-L840
[foo-lookup]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.h#L80-L93
[foo-update]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L635-L655
[foo-import]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/file_adder.cpp#L558-L573
[foo-artwork-call]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/file_adder.cpp#L906-L918
