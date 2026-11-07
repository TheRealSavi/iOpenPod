# Phase playlists and per-song gameplay data

Research date: 2026-10-30. This report follows the actual Phase game and Classic
firmware, rather than treating the historical `phase_game_flag` field name as a
format specification. No connected iPod was changed.

The independent [nano 5 investigation](phase-nano5-firmware-contract.md) now
verifies the SQLite SDK bridge and the same persistent-ID/name selection. It
also establishes a native nano consumer accepting distinguished kind 25 among
several user Playlist kinds; the Classic-only importer result below must not be
generalized to that SQLite path.

## Main finding

Phase build **3168002** does not select its main music playlist by testing MHYP
`+0x52 == 25`. Its selection routine first uses a **playlist persistent ID stored
in a separate Phase Library index**. If that fails, it looks for an exact,
case-sensitive playlist title **`Phase`**. `Phase Music` does not satisfy that
fallback. The ordinary Classic playlist importer also does not consume `+0x52`.

The historical value 25 may still matter to iTunes' producer workflow. This work
does not establish how iTunes decides to generate analysis, and does not claim
that every game or firmware globally ignores that field. See the separate
[application audit](phase-application-contract.md) for its history and preservation.

A playable setup has three connected parts:

```text
iTunesDB playlist persistent ID
             |
             v
Phase Data/Phase Library: selected playlist ID + per-track index
             |
             v
MHIT track persistent ID -> shard + uppercase hexadecimal analysis filename
             |
             v
Per-song gameplay data, separate from the song's audio
```

The index format is reproducible: an authored 384-byte, one-track index is accepted
by the game's real ARM parser, preserves both persistent IDs, and supports native
track lookup. Bad magic and incorrect total file size are rejected. This is an
offline parser result, not a physical gameplay test.

## Exact inspected inputs

| Input | SHA-256 |
| --- | --- |
| Classic 120GB RetailOS 2.0.1, prepared OSOS | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| Encrypted `Executables/Phase_3168002.bin` | `36ca824604bcb63dac194dcac267916f3196cedcf26aa95790d9b96f3c857caa` |
| Decrypted Phase executable, 947,252 bytes | `35834fede51f170a0b0bda8e380e1c12af0f86ca1a7952e5abfbb24ab4082258` |

The unmodified manifest maps platform IDs 2 and 3 to this executable. Its separate
platform-1 build 3167997 has not been traced here. The decrypted executable is an
`eapp` image with a logical base of `0x18000000`. Its new Ghidra project is
`ipod-firmware-lab/projects/phase-game/phase3168002.gpr`. Twenty-five proposed
semantic function names are saved in that project, with analyst comments and
a byte-unchanged receipt in `artifacts/phase-game/applied-research-names.tsv`.
They are visible when opening the program in Ghidra, not only in this report.

The stock firmware's actual SIDB parser and game verifier authenticated the
executable using its original SINF and manifest digest. Stock routine `0x0804d008`
then decrypted it. The decryption experiment replaces the locked physical AES
peripheral with software AES-CBC and supplies a constant kernel thread ID for
heap accounting. These are explicit environment adapters; they are not evidence
of a fully booted iPod. The receipt records source hashes and adapter scope.

## Playlist selection

Game routine `0x180416c4`, proposed name **Phase_SelectMusicPlaylist**, performs:

1. Open/reset the SDK music-library browser.
2. Apply include mask `1` and exclude mask `0x7e` through Metadata API slot 57.
3. Enumerate user playlists through SDK Metadata slots 61 and 89.
4. If a Phase Library object exists and its stored playlist ID is nonzero, compare
   that full 64-bit ID against each playlist's persistent ID.
5. If no ID matched, compare each playlist title with literal `Phase`.
6. Select the matching playlist and query its filtered song count. No match
   leaves selected handle `-1` and count zero.

The native probes cover ID precedence over names, the exact-name fallback,
missing-ID fallback, and failure of a playlist named only `Phase Music` when no
matching index ID is supplied. The title comparison at `0x18002548` also rejects
`phase`, `PhaseX`, and `Phase `.

The SDK Metadata module UUID in the game matches the firmware module descriptor
at `0x089fb750`. Its 169 function pointers start at `0x089fb4ac`. This provides an
independent bridge from the game's imported functions to firmware consumers.

| Value | Game wrapper / SDK slot | Classic firmware consumer |
| --- | --- | --- |
| Playlist persistent ID | `0x18006b38`, Metadata 162 | `0x082a0790` -> `0x0827e5ec`: native playlist `+0x30/+0x34`, imported from MHYP `+0x1c` |
| Track persistent ID | `0x18006b98`, Metadata 97 | `0x082a1148` -> `0x0827b7f4`: native Track `+0x110/+0x114`, from MHIT `+0x70` |
| Whole duration seconds | `0x18006b80`, Metadata 119 | `0x082a0eec` -> `0x0827c3f4`: unsigned duration milliseconds divided by 1,000 |
| Exact duration milliseconds | Metadata 120 | `0x082a0f10` -> `0x0827adf8` |

Decompiler signatures that show these ID getters returning one word are wrong:
the ARM instructions return both halves through R0/R1. Numeric iTunesDB Track IDs
and a device GUID are not substitutes for these persistent IDs.

The media filter maps the SDK exclude mask to native mask `0x16e`. The browser
requires the music bit and rejects the other mapped kinds. This is a media-kind
filter, not a distinguished-playlist-kind-25 check.

## Song eligibility

The primary game configuration sets `song_duration_min_sec = 30` and
`song_duration_max_sec = 1800`. Routine `0x18076a74`, proposed name
**Phase_ClassifySongAvailability**, uses inclusive comparisons against the SDK's
integer whole seconds and then looks up the track persistent ID in the Phase
Library index.

| Observation in this path | Returned value |
| --- | --- |
| Duration outside the configured whole-second interval | `2` |
| Duration eligible, no matching analysis-index record | `1` |
| Duration eligible, matching analysis-index record | `0` |

Native probes verify 29,999 ms fails, 30,000 ms passes the duration test,
1,800,999 ms still passes, and 1,801,000 ms fails. These are the observed eligibility
boundaries; other decoding or data-validation failures can still prevent play.
The primary assets also require five playable songs for Marathon mode.

## Storage and identity

The index opens as `Phase Data/Phase Library`. An analysis record supplies a
shard number and track persistent ID, from which game routine `0x18010f6c` builds:

```text
Phase Data/F{shard as decimal, at least three digits}/{track PID as 16 uppercase hex digits}
```

Example for shard 7 and track PID `8877665544332211`:

```text
Phase Data/F007/8877665544332211
```

There is no `.phz` extension in this user-analysis pathname. The separately
bundled soundtrack uses `midi/aaa.phz` through `midi/ggg.phz` inside `main_0.ark`.
These paths should not be conflated.

The game uses SDK AsyncFileIO with directory kind 1. Classic
`GameFiles_BuildPath` (`0x080804bc`) maps that kind to the game's per-installation
`iPod_Control/gamedata_RW/<game-id>/` directory. For Phase the identifier is
`1D000`. Existing directories may be presented with `GameData_RW` capitalization
on the device; FAT name matching is case-insensitive. These files belong beside
the game's writable data, not inside the read-only game executable archive.

## Minimal Phase Library index

The following is the **native-accepted minimal subset**, not a complete catalog
of every field iTunes may populate. Integers are little-endian. Optional MHOD
children are omitted in the generated fixture.

| Record | Serialized header bytes | Header-width value used by the reader |
| --- | --- | --- |
| `mhfd` | `0x74` | `0x78` |
| `mhsd` | `0x64` | `0x68` |
| `mhlr` | `0x5c` | `0x5c` |
| `mhrd` | `0x4c` | `0x50` |

The four-byte differences are important. Decoder `0x18013d5c` and record decoder
`0x18010d48` copy serialized 64-bit fields into aligned native structures, leaving
a four-byte padding gap. The generated fixture uses the exact serialized read
sizes and skip arithmetic executed by the reader.

| Record + offset | Width | Confirmed role / generated value |
| --- | --- | --- |
| `mhfd +0x00` | 4 bytes | Literal `mhfd` |
| `mhfd +0x04` | u32 | Header-width value `0x78` |
| `mhfd +0x08` | u32 | Reader accepts values at most 1; fixture uses 1 |
| `mhfd +0x10` | u32 | Dataset count; fixture uses 1 |
| `mhfd +0x14` | u64 | Actual serialized file size; mismatch returns `-4` |
| `mhfd +0x1c` | u32 | Next record-ID state copied to native object `+0x14` |
| `mhfd +0x24` | u64 | Playlist persistent ID, copied to native object `+0x18` |
| `mhsd +0x00` | 4 bytes | Literal `mhsd` |
| `mhsd +0x04` | u32 | Header-width value `0x68` |
| `mhsd +0x10` | u16 | Dataset kind 1 selects the record-list reader |
| `mhlr +0x00` | 4 bytes | Literal `mhlr` |
| `mhlr +0x04` | u32 | Header-width value `0x5c` |
| `mhlr +0x08` | u32 | Number of `mhrd` records |
| `mhrd +0x00` | 4 bytes | Literal `mhrd` |
| `mhrd +0x04` | u32 | Header-width value `0x50` |
| `mhrd +0x0c` | u32 | Child MHOD count; fixture uses zero |
| `mhrd +0x10` | u32 | Index-record ID, separate from track persistent ID |
| `mhrd +0x14` | u64 | Track persistent ID |
| `mhrd +0x1c` | u32 | Analysis-file shard number |
| `mhrd +0x20` | u32 | Analysis-byte count returned by the metadata-only path |

The root parser at `0x1800cd38`, proposed name **PhaseLibrary_ParseIndex**, accepts
the generated index. Lookup routine `0x18017bd8`, proposed name
**PhaseLibrary_FindTrackByPersistentId**, returns its record for the correct
64-bit PID and null for a missing PID. The parser does not require a SIDB, device
GUID, or signature in this minimal format.

## Per-song PHZ gameplay-analysis format

The per-song bytes are also reproducible. Routine `0x18009dc4`, proposed name
**PhaseAnalysis_DecryptAndParse**, accepts all seven bundled `.phz` files and a
freshly authored synthetic file. Despite the asset directory being named `midi`,
the decrypted payload is a compact chunked event format, not a standard MIDI
file. This result establishes container-writing feasibility; it does not recreate
iTunes' audio-to-chart analysis or establish physical playability of a synthetic
chart.

### Envelope and integrity check

| Offset | Width | Observed value and reader behavior |
| --- | --- | --- |
| `+0x00` | 3 bytes | Bundled files use ASCII `pha`; the parser consumes these bytes without comparing them |
| `+0x03` | u8 | Bundled value 2, retained as the parsed analysis object's format byte |
| `+0x04` | LE u32 | Bundled value 1; parser requires a positive signed value |
| `+0x08` | LE u16 | Wrapped-key byte count; bundled value 64, parser permits at most `0x400` |
| `+0x0a` | preceding count | RSA-OAEP/SHA-1 ciphertext wrapping a 16-byte AES key |
| following ciphertext | remaining bytes | AES-128 ECB encrypted chunk stream; observed files have a multiple-of-16 body |

The game embeds a fixed 512-bit RSA private key in a 318-byte DER object at
`0x180aea8c`; key initializer `0x18019c70` imports it. The corresponding public
key's DER SHA-256 is
`5a92d8bdbe0662a327ec6509544f09d3194d21194d81aa7a304b1ebcc9e9e97e`.
This is a game-asset key, separate from the account and device keys used to launch
the game. A new envelope needs only the public key. No device GUID or SIDB input
appears in this analysis parser.

RSA wrapper `0x18009374` invokes `rsa_decrypt_key` at `0x18083720` with OAEP and
SHA-1, requiring a 16-byte result. AES loop `0x1800dd70` decrypts successive
16-byte blocks independently: there is no IV or CBC chaining. Routine
`0x1800b4e8` hashes the entire decrypted body with MD5. Its 16-byte digest must
equal the unwrapped AES key. All seven bundled files satisfy this relationship.

A producer can therefore build the chunk stream, pad it to a 16-byte multiple,
set the AES key to MD5 of those padded bytes, RSA-OAEP/SHA-1 wrap that key with the
public key, and encrypt the padded bytes using AES-128 ECB. A newly generated
envelope following this procedure passed the real game parser with the adapters
described below.

### Plaintext chunks and events

Each chunk begins with a four-byte tag and a little-endian u32 payload length;
the length excludes the eight-byte chunk header. The first chunk in bundled
files is `head`. The parser consumes its first u16 and skips the rest of that
chunk; this routine does not check its tag or that u16 value. The synthetic
fixture uses a 16-byte `head` payload beginning with u16 value 1.

Subsequent `tran` and `beat` chunks each begin with a little-endian u32 event
count. Both chunk kinds must be encountered for this parser to return an object.
Unknown chunk kinds are skipped using their declared length. A transient event
contains a timestamp and a u16 packing three five-bit magnitudes; a beat event
contains a timestamp and a u8 packing two four-bit magnitudes. Exact musical
meanings of these magnitudes require their gameplay consumers and should not be
inferred solely from the names `tran` and `beat`.

Timestamp decoder `0x1800e3b4`, proposed name **PhaseAnalysis_ReadEventTimeQ16**,
maintains an independent timestamp accumulator for each chunk:

- A byte from 0 through 254 advances the previous Q16.16 seconds value by
  `byte * 0x200`, equivalent to `byte / 128` seconds.
- Byte `0xff` instead introduces an absolute little-endian u32 Q16.16 timestamp.
- Helper `0x1800a1a8` multiplies by 1,000 and shifts right 16 to obtain integer
  milliseconds in the decoded event array.

Transient decoder output is five u32 words: time in milliseconds, each of the
three five-bit magnitudes shifted left 11, and their sum. The top input bit is
unused. Beat decoder output is three u32 words: time in milliseconds, the high
nibble shifted left 12, and `((low_nibble << 11) * 19660) >> 15`. The constant
19660 is stored at `0x1800a1a4` (`0x4ccc`).

The returned 24-byte analysis object has transient count/pointer at `+0/+4`,
beat count/pointer at `+8/+0xc`, and the outer format byte as a word at `+0x14`.
Its remaining word is not assigned a semantic meaning here.

### Native verification scope

`scripts/probe_phase_phz.py` runs 13 cases against hash-checked game instructions:
the seven original songs, one generated file with one event of each kind, missing
`tran`, missing `beat`, altered ciphertext, zero container version, and altered
outer magic. The native parser rejects the two missing-chunk cases, the damaged
body, and version zero. It accepts the new valid file and the altered unchecked
three-byte magic. The generated events decode to exactly the predicted integer
times and magnitudes.

Native envelope control flow, MD5, integrity comparison, stream reading, chunk
dispatch, and event decoding execute unchanged. RSA-OAEP/SHA-1 and AES ECB use
explicit host adapters, independently checked by decrypting all seven original
files. Allocation and key initialization are modeled. The probe does not claim
that the native RSA/AES implementation itself was exercised or that a physical
iPod played the generated chart. See the [PHZ probe receipt][phz-probes] and
[parser exports][phz-export].

## Creation recipe and application work

1. Create an ordinary iTunesDB playlist and retain its nonzero persistent ID.
   With a matching Phase Library index, its visible title can be `Phase Music`
   or another name. Without an index-ID match, only the exact `Phase` fallback
   is established for this executable.
2. Include eligible music Tracks, retaining each MHIT persistent ID and duration.
3. Produce valid gameplay analysis for those exact audio files.
4. Write a Phase Library index containing the playlist ID and one record per
   analyzed track, with the track PID, shard, and analysis size.
5. Publish the index and analysis files through Storage with the library changes,
   preserving existing game saves and unrelated game files.

The research-only builder `ipod-firmware-lab/scripts/phase_library.py` generates
the minimal index without shipping firmware, an emulator, or game code. For
example, `build_phase_library(playlist_id, (PhaseTrack(track_pid, 7, size),))`
returns bytes; `analysis_relative_path(...)` returns the corresponding filename.
It does not generate analysis, write an iPod, or implement an iOpenPod feature.

Current iOpenPod preserves the historical raw marker during ordinary edits but
does not implement this Phase index/analysis workflow. Stable persistent IDs and
joint publication of the database and companions are the important application
requirements established here.

## Evidence and reproduction

Run from the firmware lab:

```powershell
uv run scripts/probe_phase_game_contract.py
uv run scripts/phase_metadata_getter_probe.py
uv run scripts/probe_phase_phz.py
```

The 19 native cases use the hash-checked game instructions for string comparison,
playlist selection, song eligibility, index parsing, and index lookup. SDK/config/
UI calls and allocation are explicit adapters. The separate firmware getter
probe checks the persistent-ID and duration semantics independently. Together
the three probes cover 58 cases: 19 game/index, 26 firmware getter, and 13 analysis
container cases. The separate executable-decryption reproduction is
`uv run scripts/decrypt_phase_for_research.py`; its cached authorization snapshot
is checked against the original encrypted executable before reuse.

- [Native game probe receipt][native-probes]
- [Game selector, disassembly and references][playlist-export]
- [Game analysis-index parser exports][format-export]
- [SDK module identity and slot mapping][imports]
- [Firmware track getters][firmware-getters]
- [Firmware file-root exports][file-roots]
- [Data-only soundtrack/configuration extraction][assets]
- [Executable authentication/decryption receipt][decryption]

[native-probes]: ../../../ipod-firmware-lab/artifacts/phase-game/native-contract-probes.json
[playlist-export]: ../../../ipod-firmware-lab/artifacts/phase-game/playlist/
[format-export]: ../../../ipod-firmware-lab/artifacts/phase-game/fileformat/
[imports]: ../../../ipod-firmware-lab/artifacts/phase-game/imports.json
[firmware-getters]: ../../../ipod-firmware-lab/artifacts/phase-metadata-track-values/
[file-roots]: ../../../ipod-firmware-lab/artifacts/phase-files-track/
[assets]: ../../../ipod-firmware-lab/artifacts/phase-assets/index.json
[decryption]: ../../../ipod-firmware-lab/artifacts/phase-game/native-decryption.json
[phz-probes]: ../../../ipod-firmware-lab/artifacts/phase-game/native-phz-probes.json
[phz-export]: ../../../ipod-firmware-lab/artifacts/phase-game/phz-envelope/
