# Legacy Clock Alarms: Mini, Video and Nano 1/2

Research date: 2026-11-13. This report examines every available latest firmware
input for Mini 1/2, Video 5/5.5 and Nano 1/2 in the local firmware lab. It does not
claim coverage of every historical release. Clock Alarms are separate from
Calendar Reminders, the hardware wake scheduler and the Sleep Timer.

The [same-day sound follow-up](alarm-sounds-legacy-2026-11-13.md) supersedes this
report's initial sound and nonzero-Playlist enable restrictions. It qualifies
Mini sound IDs, native Playlist arrays, per-city sound modes and Radio observations.
The later [scheduling and city investigation](alarm-legacy-scheduling-cities-2026-11-13.md)
independently executes Mini 1/Nano 1 scheduling, maps the 204 native city entries,
and resolves Nano 1 creation defaults and the runtime Radio availability source.
Those findings supersede the corresponding open questions below.

The later [Nano 2 policy decision](../adr/0261-use-nano-1-alarm-compatibility-for-nano-2.md)
enables Nano 1-compatible editing on Nano 2 by explicit user direction. It
supersedes this report's product restriction for Nano 2, while leaving the
encrypted-code evidence gap unchanged.

The newly qualified operations are existing Mini 1 alarm-minute edits,
Mini 1/2 enable changes when no Playlist identity is saved, and existing
Nano 1/Video per-city time and canonical enabled-state edits. Video's Preferences word remains
a Clock Alarm Projection, not the persistent entry. Nano 2's encrypted OSOS does
not qualify a mounted-file writer. Sound, city changes, alarm creation/deletion,
physical wake and live firmware adoption remain outside these proofs.

## Input coverage and exact identity

| Target | RetailOS; updater families | Main image SHA-256 | Alarm result |
| --- | --- | --- | --- |
| Mini 1 | 1.4.1; 3 and 6 | `2f844307acf62702fc247b19a148f35d497ce59d6ef7790b242200b5d64b09df` | Each package replayed independently: Preferences minute and zero-Playlist enable edits through native UI and whole-file save |
| Mini 2 | 1.4.1; 7 | `346504450c5201a632cafa38312093fc04b402b4ca37c79d7ca4a4167bb8f34d` | New zero-Playlist enable proof; existing native minute and next-occurrence proof retained |
| Video 5 | 1.3; 13 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` | Native per-city record serializer/parser replayed |
| Video 5 | 1.3; 20 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` | Independently loaded and replayed identical complete image |
| Video 5.5 | 1.3; 25 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` | Independently replayed distinct complete image; common code prefix |
| Nano 1 | 1.3.1; 14 and 17 | `2d34721c1d36f592b076ca111822cea6afcf718331dcf4117618f0eb338bf4cb` | Each package replayed independently: same tagged record framing as Video, different resource bases |
| Nano 2 | 1.1.3; 19 and 29 | No qualified plaintext OSOS | Encrypted inputs inventoried; no executable alarm contract inferred |

Mini 1 and Nano 1 use their independently verified initialized runtime maps,
logical ARM little-endian base zero and retained source aliases. Video's helper
executes its original startup relocation. These are bounded execution models,
not complete boots. Nano 2's identical complete firmware members have SHA-256
`1432ac66f164eed331e74f68e80bf69cc2de888884cfadb0d06f638296a94000`;
this is a container identity, not a plaintext code hash.
[Mini 1 provenance][mini1-input], [Mini 2 provenance][mini2],
[Nano 1 provenance][nano1-input], [Nano 2 status][nano2-input],
[Video provenance and prior record proof][video-existing].

The [new reproducible probe][probe] executes **52 cases**: six on each Mini 1
input, three on Mini 2, seven on each Video input and eight on each Nano 1 input. Its
[receipt][receipt] records the complete image hash and every executed original
four-byte instruction with source-byte equality checks. The Mini 1 cases compare
the entire Preferences file. The Nano/Video cases execute original record logic
and byte-framing helpers, adapting stream I/O and city resource lookup. They
retain Preferences unchanged. No physical iPod was accessed or changed.

Run in the sibling firmware lab with a fresh output directory:

```powershell
uv run scripts/check_legacy_clock_alarms.py artifacts/alarm-legacy-NEW
```

## Mini 1 and Mini 2: one saved Alarm Clock setting

Both qualified Mini releases use `iPod_Control/Device/Preferences`, exactly
2,876 bytes (`0xB3C`), LE u32 version `0x16` at file offset zero. Owner offsets
are eight bytes greater than file offsets. The alarm minute word is LE u16
at file `0xB22`, owner `0xB2A`. Its low 12 bits are minutes after local midnight;
its high four bits must survive an edit.

Mini 1's own getter `0x667A0`, setter `0xC226C`, and UI callback `0xC5098`
confirm this independently of Mini 2. Property `0x282B` applies
`old & 0xF000 | minutes & 0xFFF`; a changed setter marks owner `0xB44` dirty.
The new probe starts at `D05A`, `F000` and `A59F`, sets 495, 1439 and 0 minutes,
then executes native whole-file save `0xDD840`. Only the two-byte minute field
may differ. Each of updater 3 and 6 passes all three cases.
[Mini 1 getter][mini1-getter], [setter][mini1-setter], [UI][mini1-ui], [receipt][receipt].

The mode is a separate masked field in LE u16 file `0xB18`, owner `0xB20`.
Mini 1's property `0x282C` toggle uses mask `0x0C`: it changes an enabled setting
to 8, and changes 8 to 0 or 4 depending on a Playlist-selection lookup. Property
`0x2822` also modifies those bits after selecting a Playlist. Thus a generic
boolean writer must not overwrite the entire word or invent how to restore the
sound selection. File `0xB24/0xB28` retains the Playlist persistent ID words.
The live getters `0x666F8` on Mini 1 and `0x66A44` on Mini 2 search the loaded
Playlist array for that persistent ID and return a signed index. They explicitly
return `FFFFFFFF` without searching when both saved ID words are zero. The
enable callback chooses 4 only for an index greater than zero, otherwise 0.
The new native probes execute this zero-ID getter, the menu callback and the
entire save on Mini 1 updaters 3/6 and Mini 2 updater 7. Initial words `A5A0` and
`A5A4` become `A5A8`; `A5A8` becomes `A5A0`. All other file bytes survive.

Consequently the host permits enable edits for canonical modes 0/4/8 only when
the saved Playlist ID is zero, preserving every bit outside `0x0C`. A nonzero
saved ID needs the current native Playlist lookup and ordering; its checkbox
remains unavailable while minute editing stays independent. Unknown mode 12 is
retained, not normalized.
[Mini 1 UI][mini1-ui], [Mini 1 Playlist getter][mini1-playlist],
[Mini 2 Playlist getter][mini2-playlist], [receipt][receipt].

Mini 2's previously executed scheduler `0xD88BC` obtains the alarm minute and
mode through properties `0x282B/0x282C`, then tests
`alarm_minutes * 60 - 5 - current_seconds`. A strictly positive result selects
today; zero or negative selects tomorrow. The disabled route cancels slot 3.
The existing 54-case investigation covers five boundary vectors, slot selection
and actual original BCD encoding with captured bus calls. It establishes civil
component scheduling, not a guaranteed physical wake or a particular UTC choice
for a repeated DST hour. Mini 1's persistence replay does not independently prove
every Mini 2 scheduling branch on Mini 1. [Mini 2 native evidence][mini2].

## Video and Nano 1: a persistent alarm per city clock

The persistent artifact is **`iPod_Control/Device/clock`**. The whole collection
uses root container 0 and city containers 1. Video loader/saver `0x238F2C` and
Nano 1 loader/saver `0x191BE4` iterate those records, clear/rebuild their own
collections during load, and write each city between the root opening/closing
words. Nano 1's path literal is `clock` at ROM `0x1ED6F1`; Video's established
path literals are ROM `0x2AA84A/0x2AA844`.
[Video collection][video-collection], [Nano 1 collection][nano1-collection].

All token words are little-endian. A container is `0x40000000 | tag`, nested
tokens, then `0xC0000000 | tag`. A scalar is tag, u32 byte length, payload, then
`0x80000000 | tag`. **There is no alignment padding**, including after the
one-byte DST value. These are variable-position fields, not whole-file offsets.

| Owner | Tag | Payload | Verified meaning |
| --- | ---: | --- | --- |
| City 1 | 2 | LE u32 | Region resource ID minus its family-specific base |
| City 1 | 3 | LE u32 | City resource ID minus its family-specific base, interpreted within that region |
| City 1 | `0x14` | One byte | Saved manual DST flag for this city |
| City 1 | 5 | Nested container | This city's Clock Alarm |
| Alarm 5 | 6 | LE u32 | Minute-of-day in this city's clock basis |
| Alarm 5 | 7 | LE u32 | Alarm kind; canonical 8 disabled, 4 Playlist |
| Alarm 5 | `0x1F` | LE u32 | Separate retained word; full meaning unresolved |
| Alarm 5 | 8 | LE u32 | Selection word consumed by Playlist routes; full identity/lifecycle unresolved |

Video city serializer `0x142068` calls alarm serializer `0x21E5A4`; its resource
bases are region `0x62C8`, city `0x61FB`. Nano 1 independently uses city serializer
`0xA6C44` and alarm serializer `0x173950`, with bases region `0x62C4`, city
`0x61F7`. Identical saved ordinals must not be presented as established identical
city names across firmware families. Time edits preserve both ordinals and the
DST byte. [Video prior proof][video-existing], [Nano 1 city][nano1-city],
[Nano 1 alarm][nano1-alarm].

The new Nano 1 probe constructs the alarm through original `0x173AB4`, confirming
default minute 0, kind 8 and zero remaining words. It then independently emits
and reads 125-byte city records for `(minute, kind)` pairs `(0,8)`, `(495,4)` and
`(1439,0)` on both updater inputs, with nonzero unknown words and DST byte 1.
Native parsing reproduces each value and leaves the entire Preferences payload
unchanged. The Video replay repeats its previously established native 125-byte
record vectors at minutes 480 and 1439 on all three images. Standalone application
tests embed the native wire bytes; no runtime dependency on the lab is added.
[Nano constructor][nano1-constructor], [receipt][receipt].

The probe's complete fixture files add the root-0 pair according to the inspected
collection writers. The entire collection filesystem parser was **not** emulated;
record serialization/parsing and its unaligned byte framing were. The host codec
therefore requires complete matched framing, bounded nesting, one alarm container
and unique correctly sized known fields per city. Malformed sources stay opaque;
ambiguous cities remain read-only. Unknown scalar values, containers and field
order survive unchanged. This is a stricter edit qualification than the firmware
parser's tolerant skip behavior, not a claim that firmware rejects every source
the host declines to edit.

### Projection, enabled state and date interpretation

Video collection recomputation chooses the earliest enabled city's alarm and
copies it into Preferences. File `0xB22` is the minute projection in the current
device clock basis, with kind bits in `0xB18` and a Playlist ID in `0xB24` when
appropriate. Changing that projected minute does not update the selected saved
city record, and later recomputation can overwrite it.
[Video ownership and callbacks][video-existing].

The Video earliest-alarm selector excludes a **full u32 kind equal to 8**. A
different Settings getter masks `0x0C` and derives its On/Off display from the
currently selected city; its empty-collection fallback even displays On. These
are not equivalent observations. The codec reports canonical kind 8 as disabled,
0/4 as enabled, and unfamiliar kinds as unknown. It does not turn arbitrary
`0xFFF8` into canonical disabled 8 or promise that the displayed city is the next
alarm. [Native selected-city review][video-existing].

The independently inspected native enable callbacks are Video `0x238A20` and
Nano 1 `0x191714`. Both set an enabled kind to 8. From 8 they read the retained
tag-8 selection as **signed i32**: greater than zero chooses kind 4, otherwise
kind 0. Both call collection recomputation after the change. Unlike Mini's
lookup, this transition reads the saved selection directly and needs no current
Playlist ID-to-index resolution. [Video toggle][video-toggle],
[Nano 1 toggle][nano1-toggle].

Five new native vectors run on each Video and Nano 1 input: `0→8`, `4→8`,
`8→4` with selection 17, `8→0` with selection 0, and `8→0` with selection
`FFFFFFFF` (signed −1). Every other city-record byte survives. Collection element
lookup, subsequent recomputation and UI notification are adapted for this bounded
test; the original condition, signed comparison and kind store execute. The
application therefore offers canonical 0/4/8 enable transitions while preserving
the selection. Arbitrary sound selection and normalization of unfamiliar kinds
remain unavailable. Application tests also cover both signed-i32 boundaries.
[Receipt][receipt].

Video next-occurrence routine `0x21E4C8` uses civil minute precision, rolls an
equal/past minute to tomorrow, and converts between the selected city and current
device clock using their base offsets and manual DST values. Existing native
vectors preserve a gap-shaped 02:30 and exercise half/quarter-hour arithmetic;
this is not an IANA historical transition resolver. Nano 1's record replay proves
minute storage, not every scheduling behavior of Video. No Host timezone is
applied to these saved minute-of-day values. [Video scheduling][video-scheduling].

Saving a file is distinct from live firmware adoption. Collection dirty saves can
replace Host changes, and the full USB/eject reload sequence remains unverified.
Application publication must retain Storage source preconditions and keep any
success message about file publication, not immediate arming or audible output.

## Nano 2 and Original iOpenPod baseline

Both Nano 2 latest packages are inventoried, but no accepted plaintext OSOS or
Ghidra corpus exists. Resources and shared family resemblance do not prove a
writer. The earlier acquisition remains paused pending repair of the selected
device's center button; this task did not stage a loader or resume device work.
The supported behavior can be described separately from a qualified file codec.
[Nano 2 acquisition status][nano2-input].

The retained Original iOpenPod v1.68.1 source at
`.scratch/issue-234/v1.68.1-source/src/iopenpod` was searched for alarm and
sleep-timer implementation. No matching Python feature was found. Accordingly,
the behavioral baseline supplies no competing alarm writer to port; the native
firmware artifacts above are the source for this implementation. The ignored
source tree is research evidence, never an application dependency.

## Remaining questions and supported edit boundary

- Mini 1/2: edit the existing qualified minute word and, with a zero saved
  Playlist ID, apply the canonical enable transition. Preserve all unrelated
  flag bits and the ID. Minute precision discards explicitly edited seconds.
- Nano 1/Video: edit an existing city's minute field or canonical enabled state;
  retain selection words, city, DST and all unrecognized bytes. Do not author the
  Preferences projection as if it were the saved entry.
- Nano 2: no mounted-file edits while OSOS remains unavailable. Known user-facing
  support is not permission to infer Nano 1's binary format.
- New/deleted clocks, Mini enable changes with a saved Playlist, sound choices, Playlist identity,
  full malformed-stream firmware behavior, missed alarms, audible delivery,
  power-state wake and USB adoption require further primary evidence.
- Sleep Timer remains an on-device workflow. None of these record proofs
  establishes a mounted-file command that starts or stops a countdown.

[mini1-input]: ../../../ipod-firmware-lab/notes/mini1-firmware-workspace.md
[mini2]: ../../../ipod-firmware-lab/notes/mini2-calendar-alarm-2026-11-06.md
[nano1-input]: ../../../ipod-firmware-lab/notes/nano1-firmware-workspace.md
[nano2-input]: ../../../ipod-firmware-lab/notes/nano2-firmware-workspace.md
[video-existing]: preferences-video-complete-2026-11-07.md
[probe]: ../../../ipod-firmware-lab/scripts/check_legacy_clock_alarms.py
[receipt]: ../../../ipod-firmware-lab/artifacts/alarm-legacy-20261113-v5/receipt.json
[mini1-getter]: ../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000667a0.c
[mini1-setter]: ../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000c226c.c
[mini1-ui]: ../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000c5098.c
[mini1-playlist]: ../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000666f8.c
[mini2-playlist]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00066a44.c
[video-collection]: ../../../ipod-firmware-lab/artifacts/preferences-video-clock-record-export-20261107-v1/00238f2c.c
[nano1-collection]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00191be4.c
[nano1-city]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000a6c44.c
[nano1-alarm]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00173950.c
[nano1-constructor]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00173ab4.c
[video-toggle]: ../../../ipod-firmware-lab/artifacts/preferences-video-clock-export-20261107-v1/00238a20.c
[nano1-toggle]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00191714.c
[video-scheduling]: ../../../ipod-firmware-lab/notes/video-calendar-alarm-2026-11-06.md
