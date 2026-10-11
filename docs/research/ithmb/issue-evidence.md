# iTHMB evidence from iOpenPod issues

Research date: 2026-10-11. Scope: public reports in
[TheRealSavi/iOpenPod](https://github.com/TheRealSavi/iOpenPod), including the full
discussion of issue 178 and relevant closed issues. This is an evidence ledger,
not an Apple specification or an authorization to change format definitions.

## How to read this evidence

**Reported** means a participant describes a measurement or device result.
**Inspected** means this investigation read the issue, comment, log text, or
repository document. No physical iPod test was performed for this document.
No issue-linked binary ArtworkDB/iTHMB sample was independently parsed here.
Issue closure and a maintainer's diagnosis do not independently validate a
binary-format rule.

Keep a report attached to its physical unit, firmware, producing application,
application version, and library state. A model name and a numeric format ID
alone cannot establish compatibility with another unit. In particular, do not
turn the latest 1061 measurements into an unconditional global definition or
infer that a model's other firmware versions must use the same layout.

This caution is also historical project guidance: in
[issue 140](https://github.com/TheRealSavi/iOpenPod/issues/140#issuecomment-4807145402),
the maintainer described the table as incomplete knowledge refined through local
device tests and user reports, explicitly allowing unknown firmware/iTunes
combinations. The linked Ithmb-Codec project states that it used iOpenPod as a
reference; its agreement with an iOpenPod table is therefore not automatically
independent corroboration.

## Starting point: issue 178

The issue remained **open** when read. Its opening report and subsequent comments
describe several devices and multiple failure histories. They must not be merged
into one test unit or one proved root cause.

### Latest report: 2026-10-11

Source: [najchris11's requested comment](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-6106769456).
The author reports a synthetic 10,000-Track library with distinct 300-by-300
covers, comparing a Classic 7th-generation unit written by Windows iTunes
12.11.x and iOpenPod 2.0.4. Five additional devices were inspected read-only:
Classic 6.5, Video 5, and nano 3, 4, and 5. Exact firmware versions, hashes,
parser source, and raw captures are not attached to this comment; files and the
parser are offered for later sharing. The author's earlier comment identifies
their MC293, but the latest test does not explicitly bind its dedicated unit to
that earlier unit or supply its firmware.

The report is valuable evidence for three format questions:

| Observation reported | Bounded inference | What it does not establish |
| --- | --- | --- |
| iTunes used 1055, 1060, and 1061 for the large Classic test; no 1068 file. iOpenPod generated 10,000 1068 frames. | Routine per-Track generation of 1068 deserves investigation on that unit and writer version. | That 1068 is invalid, unnecessary on every device, or safe to delete from retained libraries. |
| Complete 1060 shards were 524,288,000 bytes; the final shard was partial. | This particular iTunes run demonstrates multiple numbered shards and a 500 MiB complete-shard size. | A universal firmware limit, a mandatory minimum shard size, or proof that smaller correctly indexed shards fail. |
| 1061 slots measured 6,160 bytes on Classic 7, Classic 6.5, and nano 3; usual visible content was 55-by-55 with 112-byte rows. | Distinguish visible pixels, row stride, raster length, and allocation length. | That all 1061 rasters must have 55 rows, or that a retained 6,272-byte allocation is corrupt. |
| Some 1061 images had smaller non-square visible dimensions while retaining the same slot size. | A file's frame allocation need not equal tightly packed visible pixels. | The meaning of every MHNI size/padding field without the actual records. |

Reported 1068 counts in the read-only inventory:

| Reported device | Tracks with artwork | Reported 1068 images | Qualification |
| --- | ---: | ---: | --- |
| Classic 7, synthetic library | 9,601 | 0 | 10,000 Tracks were transferred, but only 9,601 artwork-bearing Tracks are listed. |
| Classic 6.5 | 1,937 | 1 | Existing library; precise writer history and firmware absent. |
| nano 3 | 15 | 0 | Small existing sample. |
| nano 4 | 140 | 1 | Presence alone does not identify purpose. |
| nano 5 | 6 | 0 | Format reportedly declared, with no corresponding file. |

The Video 5 is named in the methodology but no corresponding 1068 or 1061
measurement row is provided. Two Classics of different generations disagreeing
on 1068 count does **not** isolate content as the trigger: firmware, writer,
library history, and generation also vary. A count of one also does not prove
that the image belongs to a special firmware-owned role; follow its database
references first.

Arithmetic helps formulate tests but does not verify the source measurements:
55 × 110 = 6,050, 55 × 112 = 6,160, and 56 × 112 = 6,272 bytes.
These are three plausible geometry/stride combinations, not three interchangeable
descriptions of one frame. Likewise, the reported 500 MiB size is exactly 2,560
frames if the relevant 1060 frame is 204,800 bytes. That single aligned format
cannot distinguish a generic byte threshold from the last complete frame below
some threshold for other formats.

The report also describes missing-iTunesDB error handling. That is a Filesystem
Session/application diagnostic question, not evidence of an iTHMB encoding.
Its proposed code changes are proposals, not results of this research. The
comment's broad closing claim about reproducing all four findings must be read
alongside its narrower methodology: read-only inspection of five devices cannot
by itself establish their behavior under the proposed writer changes.

### Earlier evidence and changing hypotheses

Dates below are source timestamps in UTC, retained for citation accuracy.

| Date | Source and unit | Reported result | Evidentiary limit |
| --- | --- | --- | --- |
| 2026-08-19 | [Opening report](https://github.com/TheRealSavi/iOpenPod/issues/178), jkblank, Classic MC293 160 GB, firmware reported as 1.62, iOpenPod 1.68.1/1.67.0 | Artwork absent on all tested screens, although the reporter decoded pixels and checked database links. Their same-unit iTunes reference reportedly displayed art. Mixed 1061 sizes of 6,050/6,160/6,272 were logged. | Full reference artifacts and scripts were offered, not attached. Firmware is a reported identifier, not independently normalized here. |
| 2026-08-26 | [jkblank's follow-up](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-5421140361), separate Classic 6, 80 GB | Failure after growth beyond roughly 1,800 Tracks with 32,000,000-byte shards; success after raising the cap and rebuilding, 1,984 Tracks/1,983 artwork entries. iTunes reportedly displayed a live 335 MB 1060 file. | The earlier duplicate comment is the same experiment, not a second unit. Rebuild changes more than a size constant; no uploaded before/after binary bundle establishes causality. Firmware unspecified. |
| 2026-08-27 | [kailan's initial report](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-5438634148), Classic 7 | Existing art disappeared after adding roughly 250 Tracks to about 2,000. | Symptom/scale report, without field-level measurements. |
| 2026-09-02 | [Maintainer response](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-5512926436) | Questions rollover as the root cause; notes 2 and 6 both worked as MHFD root values on personal devices, and format IDs can have model-specific details, citing nano 7. | Model-specific observation and hypothesis, not proof that either root value works on every unit. |
| 2026-09-03 | [jkblank clarification](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-5521897595) | Their deletion workaround removed the whole Artwork directory, including iTHMB files. | Rules out interpreting the workaround as a controlled ArtworkDB-only change. |
| 2026-09-10 | [najchris11's earlier report](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-5613051455), MC293 160 GB | Art was broken before iOpenPod; a fresh rebuild still failed with 20,284 Tracks. Old/new MHFD opaque fields differed. | Both states were broken; their difference cannot identify a necessary rendering field. Firmware unspecified. |
| 2026-09-18 | [kailan's follow-up](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-5735083086), MC297 160 GB | Twelve roughly 30 MB 1060 shards became one per format after changing the cap and regenerating art for about 2,979 Tracks. Reporter confirms Now Playing, Cover Flow, and list artwork. | Explicitly AI-generated write-up with human confirmation. Cap, allocation, fresh extraction, and rebuild changed together. Raw dumps offered, not attached. Firmware unspecified. |
| 2026-09-19 | [Maintainer test request](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-5737984374) | Requests enough unique artwork to force genuine iTunes rollover and compare its output. | Distinguishes unsupported sharding from incorrectly authored sharding; request itself is not a test result. |
| 2026-10-11 | [Latest measurement report](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-6106769456) | iTunes reportedly produced 1060 files numbered 1 through 4. | Evidence against a blanket claim that the tested Classic cannot use numbered shards. It does not identify which iOpenPod field caused the earlier failures. |

The original report additionally associates ordinary Track representations with
`AssociatedFormat=0`, and reports 1068/1069 with other association values. The
values are metadata observations for that capture, not a fully decoded definition
of `AssociatedFormat`. Matching the visible pixels and primary Track links is
insufficient to prove the whole ArtworkDB equivalent to iTunes: ancillary
records, allocation, counts, and filenames can still differ.

### PR 186 and rollover units

[PR 186](https://github.com/TheRealSavi/iOpenPod/pull/186) was closed without merge
on 2026-08-26. It proposed deriving the artwork cap from the filesystem maximum,
with FAT32's 4 GiB minus one fallback. The
[maintainer's closing comment](https://github.com/TheRealSavi/iOpenPod/pull/186#issuecomment-5431246730)
reports problems above approximately 500 MB on some hardware, without identifying
that hardware or supplying a capture. This is useful historical warning evidence,
not an exact measured ceiling for all devices.

Keep the quantities distinct: the old writer's 32,000,000-byte budget, the later
writer's 268,435,456-byte budget, the reported iTunes boundary of 524,288,000 bytes,
and the filesystem maximum of 4,294,967,295 bytes answer different questions.
The filesystem's ability to store a file does not establish firmware acceptance.

## Closed issues with direct artwork evidence

### 1061 mixed sizes can coexist with a report of working art

[Issue 111](https://github.com/TheRealSavi/iOpenPod/issues/111), filed 2026-06-05,
contains iOpenPod 1.0.55 logs for a Classic 6, 80 GB, on Fedora. The writer reports
1,251 existing entries and mixed 1061 lengths of 6,160 and 6,272, choosing 6,160
for MHIF. The reporter
[explicitly says artwork works on the iPod](https://github.com/TheRealSavi/iOpenPod/issues/111#issuecomment-4634808159).

This is counterevidence to treating *any* mixture as sufficient cause of complete
artwork failure. It does not prove that each layout was exercised on every screen,
that the two lengths occurred within the same shard, or that another firmware
accepts the mixture. No firmware or raw file capture is supplied.

### nano 7: separate rendering and preservation failures

[Issue 10's nano report](https://github.com/TheRealSavi/iOpenPod/issues/10#issuecomment-4201634938)
describes correct artwork from CopyTrans but missing iOpenPod artwork, plus a
reported discrepancy between displayed firmware 1.70 and 1.04. This illustrates
why firmware strings need provenance; it does not prove two firmware revisions
were actually compared.

[Issue 69](https://github.com/TheRealSavi/iOpenPod/issues/69) then records several
different stages:

- A claimed fix was followed by user failure. The maintainer clarified that their
  own nano 7 could only enter disk mode and could not confirm firmware rendering
  ([testing limit](https://github.com/TheRealSavi/iOpenPod/issues/69#issuecomment-4274308206)).
- Later, Now Playing worked while list covers were tiled/shifted; two users
  described that split
  ([screenshots and report](https://github.com/TheRealSavi/iOpenPod/issues/69#issuecomment-4345119876)).
- Once small covers reportedly rendered correctly, successive Syncs removed
  older art
  ([repeat-Sync report](https://github.com/TheRealSavi/iOpenPod/issues/69#issuecomment-4406260370)).
- The maintainer diagnosed overbroad pruning, and a user eventually confirmed
  success
  ([diagnosis](https://github.com/TheRealSavi/iOpenPod/issues/69#issuecomment-4429794798),
  [final confirmation](https://github.com/TheRealSavi/iOpenPod/issues/69#issuecomment-4449748493)).

[Issue 89](https://github.com/TheRealSavi/iOpenPod/issues/89) separately reports
existing nano 7 art disappearing after adding a song with 1.0.51. Its
[maintainer diagnosis](https://github.com/TheRealSavi/iOpenPod/issues/89#issuecomment-4429801252)
again identifies pruning of still-needed artwork. A second report calls its
device a Classic 3rd Gen, an ambiguous generation label that should not be
silently mapped to a Device Profile. Neither issue supplies a controlled binary
layout comparison. These reports support testing all display roles and repeated
Sync preservation, not deriving pixel geometry from symptom descriptions.

### Classic and Video: format selection versus identification

[Issue 81](https://github.com/TheRealSavi/iOpenPod/issues/81) concerns an 80 GB
Classic whose list cover appeared but Now Playing did not. The log identifies
MB029, reports firmware 1.62, and shows format IDs 1044/1060/1061/1068. The
maintainer later
[removed 1044 as a hypothesis](https://github.com/TheRealSavi/iOpenPod/issues/81#issuecomment-4502969346),
after asking for model, firmware, iTunes version, and reference filenames.
The original reporter
[eventually confirmed success](https://github.com/TheRealSavi/iOpenPod/issues/81#issuecomment-4566974293),
without an isolated 1044 comparison. The thread does not prove that 1044 universally
inhibits 1061 or that its presence alone caused the failure.

A Video 5 participant in the same thread had a separate raw-device access and
identification problem, and
[reported success after rerunning with sufficient permissions](https://github.com/TheRealSavi/iOpenPod/issues/81#issuecomment-4520316902).
Treat this as historical evidence about incomplete Device Evidence, not a
recommendation to run the application as root.

[Issue 10](https://github.com/TheRealSavi/iOpenPod/issues/10) similarly ends its
original modded Video 5 report with
[user confirmation after an identification-related fix](https://github.com/TheRealSavi/iOpenPod/issues/10#issuecomment-4031324838).
[Issue 72](https://github.com/TheRealSavi/iOpenPod/issues/72#issuecomment-4263418539)
reports artwork returning after restoring a U2 30 GB Video with conflicting
identifiers. These reports make incorrect format selection or incomplete Device
Evidence plausible alternatives to a pixel-decoder failure; they do not isolate
the exact erroneous representation in a controlled binary comparison.

### Other useful boundaries

| Issue | Finding worth retaining | Limit |
| --- | --- | --- |
| [9](https://github.com/TheRealSavi/iOpenPod/issues/9) | Video 5 reports combine wrong-image association in the application, missing device art, and source-metadata problems. One reporter eventually reports success; another questions the outcome. | Multiple failure modes, no exact layout measurement. |
| [19](https://github.com/TheRealSavi/iOpenPod/issues/19) | Host UI enlargement makes small device thumbnails visibly blurry. | Perceived quality is not proof of incorrect iTHMB encoding. |
| [94](https://github.com/TheRealSavi/iOpenPod/issues/94#issuecomment-4502292146) | Maintainer distinguishes artwork never extracted from media tags from artwork rejected by firmware. | Tagged-media sample/logs were linked; no iTHMB format measurement. |
| [100](https://github.com/TheRealSavi/iOpenPod/issues/100) | A modded Classic 7 reportedly mixes artists' covers after a second Sync. | Closed as possibly fixed without reporter confirmation or logs; does not isolate codec versus image identity/allocation. |
| [107](https://github.com/TheRealSavi/iOpenPod/issues/107) | Shuffle 3 Sync failed because the old code required an artwork format table. | Application policy error on a screenless device, not evidence of an undiscovered display codec. |
| [122](https://github.com/TheRealSavi/iOpenPod/issues/122#issuecomment-4705427091) | A participant recalls artwork-ID errors when initializing a blank library; prior iTunes initialization reportedly avoided the problem. | No captured database pair; broader database validity issue. |
| [140](https://github.com/TheRealSavi/iOpenPod/issues/140#issuecomment-4807145402) | Maintainer records incomplete format knowledge and possible firmware/iTunes variation. | Completeness cannot be inferred from profile count or an AI-produced cross-reference. |
| [152](https://github.com/TheRealSavi/iOpenPod/issues/152#issuecomment-5071073541) | A wrapper user reports a locally found artwork-entry change on an incompletely identified Video 5.5. | Actual change and physical validation matrix absent. |
| [238](https://github.com/TheRealSavi/iOpenPod/issues/238) | Host scan failure leaves Tracks without metadata/artwork before encoding begins. | Input acquisition, not an iTHMB layout failure. |

## Search coverage and attachment status

On 2026-10-11, GitHub issue searches used
`repo:TheRealSavi/iOpenPod is:issue is:closed` with each of `artwork`, `ithmb`,
`"album art"`, `cover`, `photos`, `photo`, `thumbnail`, `corruption`,
`"album artwork"`, and `"album-art"`. Each requested up to 100 results; each
returned fewer than that limit. The union contained 28 closed issues. All their
returned bodies and full comment lists were obtained for relevance screening;
large diagnostic logs were examined selectively. This is keyword coverage, not
proof that no other relevant issue exists. The supplied open issue 178 and its
linked PR 186 were read separately.

The closed-issue union was: 4, 8, 9, 10, 19, 21, 36, 47, 69, 72, 81, 89, 94,
100, 107, 111, 122, 126, 140, 144, 152, 157, 159, 175, 187, 214, 221, and 238.

The remaining screened results provide surrounding context rather than format
measurements:

- [4](https://github.com/TheRealSavi/iOpenPod/issues/4#issuecomment-3998463700),
  [8](https://github.com/TheRealSavi/iOpenPod/issues/8),
  [36](https://github.com/TheRealSavi/iOpenPod/issues/36), and
  [175](https://github.com/TheRealSavi/iOpenPod/issues/175): general library
  acceptance, naming, or Apple-software interoperability; issue 4 also reports an
  artwork improvement after a master-Playlist flag fix.
- [21](https://github.com/TheRealSavi/iOpenPod/issues/21),
  [126](https://github.com/TheRealSavi/iOpenPod/issues/126),
  [144](https://github.com/TheRealSavi/iOpenPod/issues/144),
  [187](https://github.com/TheRealSavi/iOpenPod/issues/187), and
  [214](https://github.com/TheRealSavi/iOpenPod/issues/214): Host UI, workflow,
  podcast, or scan-cache discussion.
- [47](https://github.com/TheRealSavi/iOpenPod/issues/47),
  [157](https://github.com/TheRealSavi/iOpenPod/issues/157),
  [159](https://github.com/TheRealSavi/iOpenPod/issues/159), and
  [221](https://github.com/TheRealSavi/iOpenPod/issues/221): transcode, identity,
  database-size, or Sync failures without a new iTHMB layout measurement.
  Issue 159 includes the reporter retracting their original model-detection
  theory, another reason to read follow-ups rather than only titles.

Issues 9, 10, 69, 81, and 100 include screenshot links. Issue 10 includes a log
link; 81 and 111 include relevant inline logs. Issue 94 links old/new logs and
an external tagged-media sample. These links were observed but their external
attachment bytes and continued download availability were not verified here.
In issue 178, the crucial raw ArtworkDB/iTHMB captures, parser, and before/after
listings are **offered rather than linked** in the retrieved discussion. This
investigation therefore cannot publish hashes, independently recomputed frame
counts, or a reproducible binary fixture manifest from that thread.

## Questions the issue history leaves open

1. For the latest three 1061 samples, are 6,160-byte raster size, allocation size,
   MHIF declaration, and distance to the next frame identical? What are both MHNI
   size fields, padding fields, offsets, and remaining shard bytes?
2. Which references lead to the isolated 1068 images? Are they ordinary Track
   covers, shared references, associated images, historical leftovers, or another
   role? Compare both live database references and raw files.
3. Why are 9,601 iTunes artwork-bearing Tracks listed for a 10,000-Track synthetic
   library while iOpenPod produces 10,000 1068 frames? Identical Track-string
   counts alone do not establish identical artwork population or deduplication.
4. Can the same unit render an otherwise identical, correctly indexed library
   split below the observed iTunes threshold? Compare boundary-adjacent Tracks,
   filenames, offsets, MHIF records, auxiliary data, and allocation overlaps.
5. Does the result repeat on another unit with the same model and firmware, and
   on another firmware for that model? Keep iTunes version and device filesystem
   provenance constant while testing one variable.
6. Is a blank-library rebuild necessary for the workaround, or would a controlled
   relocation preserving all image records suffice? Existing reports change
   multiple variables and cannot decide this.

Current accepted project policies explicitly distinguish synthetic validation
from physical compatibility: [ADR-0124](../../adr/0124-accept-validated-mixed-f1061-layouts.md)
retains validated 55/56-row variants, and
[ADR-0131](../../adr/0131-accept-bounded-visible-dimensions-in-packed-artwork.md)
separates bounded visible dimensions from stored raster geometry. The latest
issue report is a reason to obtain stronger evidence and review those policies;
it does not silently supersede them.
