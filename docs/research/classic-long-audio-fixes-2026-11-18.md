# Classic 2.0.5 long-audio repairs

Date: 2026-11-18. Implemented and bundled as Mod Platform Version **0.7.0-dev**.
Initial qualification used offline native execution. Subsequent physical testing
on the user's Classic 120GB is recorded below; separate the native comparisons
from user-reported playback results.

## Inputs and provenance

Unmodified Classic 38 / Apple 2.0.5 OS SHA-256:
`d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224`.
Raw DRAM file offset `0xaf98` maps to `0x08000000`; the prepared input adds
the 0x800-byte header, making that offset `0xb798`. Its SHA-256 is
`660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e`.

The overflow diagnosis/instruction replacements originate in kayboll's
[osos-lab PR 62](https://github.com/lgreitis/osos-lab/pull/62), commit
`5f3744d4b752dd36460d2c840edf251a6363c099`.
The audio cursor offsets and chunk-jump approach originate in
[PR 63](https://github.com/lgreitis/osos-lab/pull/63), commit
`bd573eb656c5af62572bfa7e5e8e8bf84a36bb6f`, GPL-3.0-only.
The implementation here is independently qualified and differs substantially
from that proposed seek wrapper. Their reported hardware timing is not our test.

## Reproduction before changing the firmware

The executable probe is
`../ipod-firmware-lab/scripts/probe_classic_long_audio.py`. It executes the
actual ARM seek, unsigned 64-bit divider, edit setter, cursor walker, table
window loaders, byte-order conversion and packet getter. The file object's
seek/read methods supply synthetic, deterministic MP4 table/media bytes.
There is no emulated codec, audio engine, HDD timing or complete MP4-open parser.

```powershell
uv run ../ipod-firmware-lab/scripts/probe_classic_long_audio.py `
  --baseline --out PATH/TO/baseline.json
```

A 2.5-million-sample fixture with 1024-unit durations, timescale 44100 and one
edit reproduces the bug: seeking to 14 hours returns success, but the next
native read emits **zero packets**. The assertion fails on the original image.
With only the three timestamp repairs (`--overflow-only`), packets return, but
the performance assertion still fails: the seek walks **2,170,547 samples**.
Both failures were observed before qualification of the final bundle.

## Setters, getters and the chosen hook

| Address | Contract checked |
| --- | --- |
| `0x081bd1cc` | Public seek: signed millisecond duration validation, video/chapter alignment, audio call, result mapping |
| `0x081bb678` | Surrounding native video/chapter seek and potential target adjustment; not replaced |
| `0x081bb188` | Audio cursor reset/advance, rounding, edit changes and error-state publication |
| `0x081ba664` | Edit setter: 64-bit start, duration scaled from movie to audio timescale, end, terminal sentinel |
| `0x081bbed0` | Audio packet getter: sample sizes/offsets, edit inclusion, timestamp output and cursor advancement |
| `0x081bac44`, `0x081bab1c`, `0x081baaa0` | Sample-size, sample-to-chunk and chunk-offset window setters |
| `0x081b940c` | Native integer-table reader and its partial-read acceptance problem |
| `0x08024024` | Native unsigned 64-bit division used by old and new paths |

The three instruction replacements load the actual high word of media time,
instead of sign-extending its low word. Native accumulation already writes both
words with carry; packet timestamps and seek conversion already read both words.
At `0x081bb5e8` the load is `[r2 - 0x1c]`; at `0x081bc0f4` it is
`[r2 - 0x14]`; at `0x081bc114` it is `[r2 - 0x1c]`. All three preimages are
`0xe1a01fc0`. The patch recipe validates the exact preimages and whole plan.

The seek patch replaces only the audio call at **`0x081bd204`**. The public
vtable remains `0x08994a68 → 0x081bd1cc`. Thus duration rejection, video/chapter
alignment and native error mapping remain before/around the optimization.
The proposed upstream replacement called the whole public seek with zero first,
even for requests that would later be rejected or take its fallback. We avoid
that extra reset, repeated video/chapter work and additional I/O.

## Planning and committing the audio cursor

The new code computes a plan without writes or file reads. It validates resident
table counts, monotonic chunk runs, positive durations, sample totals, timescale,
media length and arithmetic bounds. It walks duration and chunk-run tables
linearly, avoiding the proposed nested chunk-by-duration-table search. Work is
capped at 32,768 duration entries and fewer than 32,768 chunk-run entries.

For no edit or one nonempty, bounded edit, it finds a chunk whose first sample
ends **strictly before** the target and edit end. It accounts for trimmed priming
samples by finding the first sample whose start lies inside the edit. Native
code finishes the remainder, retaining its rounding and terminal transition.
Cheap forward/repeated seeks retain their current-state native path.

The commit reproduces the native state after consuming that chunk's first sample:

| Track offsets | Values |
| --- | --- |
| `+0x68`, `+0x6c`, `+0x70` | Next sample, chunk-run index, chunk number |
| `+0x74`, `+0x78` | One sample consumed in this chunk, its byte size |
| `+0x84`, `+0xa0` | Position inside the duration entry, duration-entry index |
| `+0x88/+0x8c`, `+0x90/+0x94` | Complete presented time and media time |
| `+0xa4` | Initial edit index |
| `+0xa8` through `+0xbc` | Start/end/duration of the single supported edit, when present |

Two edge cases emerged from independent tests and required additional handling:

- Apple keeps the next-sample cursor in a register and publishes it only on
  success. An initial implementation changed its value on edit-end failure.
  The final code restores the value the native reset/forward path would retain.
- A repeated forward request after a terminal/error state can return differently
  if the edit is restarted. Such continuation now stays in the original path.

Unsupported cases fall through **once, without a reset or partial cursor update**:
multiple/empty edits, nonresident or excessive run tables, oversized duration
tables, inconsistent sample/chunk counts and unsupported numeric bounds. This
preserves native behavior; it does not make malformed files safe or promise
fast seeking for every MP4 arrangement.

## File-window failure handling

The native sample-size loader's shared table reader treats any nonzero read
count as success. A direct jump must not publish a cursor based on stale bytes
from a truncated table. Its new window read requires the complete requested
byte count, converts entries using Apple's original endian reader, then
publishes the window base. Failed/short reads return the native error without
retrying through another seek; an overwritten cache is invalidated so a retry
reloads it. A seek failure does not invalidate an untouched cache.

This protection applies to the new jump's reads. We did **not** alter the shared
native table reader used by other audio/video paths, or claim to repair all of
its existing short-read behavior.

## Final qualification

```powershell
uv run ../ipod-firmware-lab/scripts/probe_classic_long_audio.py `
  --build PATH/TO/build --suite --out PATH/TO/qualification.json
```

The final build passes:

- **390** differential seeks and conditional subsequent packet reads across 26
  fixtures: rates 32000/44100/48000/96000, fixed/variable sample sizes, multiple
  duration/chunk runs, description changes, trims, multiple/empty edits, random
  forward/backward targets, repeats, start, end and rejected past-end requests.
  Complete fixture reader/audio-track state, packet bytes, per-packet timestamps
  and statuses match the native linear implementation with only overflow fixed.
- **16** packet-getter cases at the `2^31` and `2^32` time boundaries, including
  nonzero edit starts beyond those boundaries. Original code emits no packets
  in 12 of these; the candidate emits packets in all 16.
- **8** edit-end transitions across those boundaries. The original fails to
  terminate; the candidate advances the edit and returns the native terminal
  error as expected.
- **17** malformed/unsupported plan inputs reach the original walker once with
  unchanged cursor state and no speculative reads. That test intercepts the
  native entry; it does not claim Apple safely processes those malformed inputs.
- Failed read, positive short read and failed file seek all return an error
  without committing a jump; clearing the injected error permits a successful
  seek and packet read equal to the native reference.
- **3** native wrapper boundary cases: rejected past-end request, video helper
  failure, and a helper-adjusted timestamp. The helper is a fixture here;
  full video/chapter playback was not emulated.

The original 14-hour reproduction now returns 53 packets and requires only
**50 native sample steps**, versus 2,170,547 for linear seeking. The emulator
measurement was about 0.0015 seconds versus 5.6 seconds on this Host, including
observation overhead. These are **not** iPod HDD/flash performance measurements.

The bundled app passes 227 focused firmware/installation/UI tests; Mypy and
changed-file Ruff checks pass. Native boot reporting and startup relocation/BSS
pass for all four supported hardware profiles. The retained-artwork failure
replay and manual/Auto appearance refresh tests pass on this same build.

## Bundle and remaining limits

The native Mods list adds **Long Audio Playback** and **Fast Audio Seeking**,
both 0.1.0-dev, for ten included mods. Builder flag: `--long-audio`.
No new preference or desktop install action is introduced. Temporary artwork
diagnostics stay disabled and Bootloader Report stays enabled.

- Complete firmware: 101,871,616 bytes, SHA-256
  `fe1cdca1d2242b379d084c13cd92f7ef0399ff0c5c84fe3ed02f8f8f20cc37cc`.
- Prepared OS SHA-256:
  `05d2bbc76078b44866798e30e4842755da7f1c67d910b5f5d2bb2e7eb7dd2964`.
- Common IM3 SHA-256:
  `747ecfb29de381b9e91f2b003d3ce072f9b9c1f822ad7c9c23085cf4be8099aa`.
- Initialized payload: 113,656 bytes; payload SHA-256
  `ed50df8dda00f01be3255dd51fe4f85147c659f8a6f9d0991a6e76290db7b079`.
- Page-rounded Mod Memory Region: 118,784 bytes (29 pages), **one 4 KiB page more**
  than 0.6.8-dev. The new seek hook owns no heap allocation, BSS cache or timer;
  its compiled function frame is 144 bytes before callees.
- Compressed asset: 56,754,238 bytes. Bootloader 2.1.0 is unchanged; normal USB
  firmware installation remains available.

Protected-media behavior, measured HDD/flash timing, arbitrary MP4 layouts and
other Classic models remain unqualified for this release. The changes affect the native MP4 audio reader
(including M4A/M4B), not every codec/container. Huge single chunks or unsupported
edit/table layouts can still take the slower native route. This is not a general
file-size-limit or all-audiobook-bugs repair.

Local evidence is retained in `.scratch/classic-long-audio-20261118/`, including
`baseline.json`, `linear-seek-baseline.json`, `qualification.json`, native
decompilation/disassembly, the independently reproduced intermediate failures,
and the final `candidate-4` build. Only the final build is bundled.

## Physical test feedback

The user's Classic 120GB (MB565) reports **0.7.0-dev** over current USB.
The `Firmware 0.7.0 Tests` Playlist contains 16-hour AAC books at 44.1 and
48 kHz, a 28-hour AAC book, short AAC/16-bit ALAC/MP3 controls, a chaptered
AAC Podcast, and an H.264/AAC video. Long books have chapters and initial
bookmarks near the signed and unsigned 32-bit media-time boundaries.

After receiving the boundary-playback, bidirectional-seek, bookmark, chapter,
end-of-file and short-control checklist, the user reported that everything
worked except test 08 opening as audio. This is an aggregate user report, not
instrumented per-case timing or proof of every optional test. The user also
confirmed that their existing videos play and seek with synchronized sound.

Test 08's problem was the one-off fixture installer: it chose `AUDIO_VIDEO`,
which encodes native `media_type=0` and projects as Music, rather than the
Movie classification `VIDEO` (`media_type=2`). Both native video flags were
already one, and the device file hash matched the generated H.264/AAC file.
Three existing Movie records used type 2 with the same playback flags.

The fixture script now requires Movie classification. A database-only correction
sets test 08 to type 2; readback verifies publication, unchanged media bytes,
unchanged other Track chunks and unchanged Playlist membership. This does not
change firmware or the production importer. Physical video playback of the
corrected test 08 still awaits confirmation. Open it through **Videos → Movies**;
the Music Playlist is not the video-mode playback test.

Local fixture, check and correction evidence is retained under
`.scratch/long-audio-test-media-20261118/`.
