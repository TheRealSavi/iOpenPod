# Phase application contract audit

Research date: 2026-10-30. This note audits current iOpenPod and retained source
evidence. It does **not** establish the game's playlist-selection algorithm,
song-analysis format, or physical playback acceptance; the separate firmware and
game investigation must settle those contracts before implementation. The
[Classic contract](phase-playlist-contract.md) and independent
[nano 5 contract](phase-nano5-firmware-contract.md) now provide that game/SDK
evidence; this note remains the application-side audit.

## Existing meaning of MHYP +0x52

The current schema stores MHYP `+0x52` as the little-endian `u16`
`phase_game_flag`. This is a lossless binary field, not a proved Phase-specific
boolean. [Current definition](../../src/iPodDB/iTunesDB/shared/chunk_defs/mhyp.py#L40).

Original iOpenPod at commit
`a20242428b93b672d14b37230772dbad75139c69` documents an observed value **25
(`0x0019`)** on an iTunes-created Phase Music sample, explicitly qualifying its
meaning as unproved. Its writer accepts the exact value and its Sync adapter
passes it through. Its tests manufacture Phase Music rows carrying 25; they do
not launch Phase or prove that the field alone is sufficient.
[Original writer](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhyp_writer.py#L250),
[Original Sync adapter](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/_playlist_builder.py#L187),
[synthetic round-trip test](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/tests/test_itunesdb_forensics.py#L151).

The same halfword already participates in unrelated current behavior:

| Current path | Value written or checked |
| --- | --- |
| Generated special Podcasts Playlist | `11` (`0x000B`) |
| Podcast baseline normalization | Preserve bits outside `0x01FF`; set low nine bits to `0x010B` |
| Normalized Podcast verification | Require `field & 0x01FF == 0x010B` |

These are directly visible in
[reconciliation](../../src/iPodDB/library/_reconcile.py#L636),
[Podcast writing](../../src/iPodDB/library/_podcast_writing.py#L449),
[normalization](../../src/iPodDB/library/_podcast_normalization.py#L355), and
[verification](../../src/iPodDB/library/_podcast_verification.py#L132).
The historical field name must not be treated as a complete semantic definition.

Pinned libgpod `7982c5554f78dde47fd006afbeff659201d6db3d` is useful only as a
comparison. Its reader exposes `+0x50` as `mhsd5_type`, and its dataset-5 writer
duplicates that value at `+0x52` with a question in the comment. It neither
establishes Phase value 25 nor supplies a Phase playlist-creation contract.
[Reader](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L2266),
[writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L5524).

## What current iOpenPod preserves and cannot create

The public Playlist model has `PLAYLIST`, `SMART`, `GENIUS`, and `FOLDER` kinds,
and no Phase-specific source metadata or editable intent.
[Kinds](../../src/iPodDB/library/playlists.py#L17),
[Playlist model](../../src/iPodDB/library/playlists.py#L410).

Native projection classifies a Playlist using folder flags, Genius seed metadata,
and Smart metadata. It does not inspect `phase_game_flag`, so a retained Phase
Playlist currently projects as an ordinary Playlist unless some other classifier
applies. [Projection](../../src/iPodDB/library/_playlist_projection.py#L81).

Ordinary editing starts with the retained native header and selectively changes
parent, folder, and sort data. It leaves `+0x52` intact. New Playlist creation
constructs `MhypHeader` without an explicit `phase_game_flag`, yielding zero;
the name **Phase Music** has no special creation effect.
[Writer](../../src/iPodDB/library/_playlist_writing.py#L63).

A synthetic public-preparation probe on 2026-10-30 set `+0x52=25` in both dataset
2 and dataset 3 copies, renamed the semantic Playlist, prepared the database, and
parsed the result. Both native copies retained **25**. This establishes current
rename preservation only; the fixture contained no game-analysis files and did
not execute firmware.

SQLite projection also does not carry this halfword: its projected category comes
from `mhsd_5_type` only for dataset 5. The SQLite writer emits Podcasts kind 11,
categories 4/5, or zero, with separate Genius Mix handling. A Nano 5 implementation
therefore needs its own proved Phase lookup contract; binary MHYP preservation
alone is not evidence that an equivalent SQLite container is produced. The
subsequent nano 5 trace confirms that both ordinary kind 0 and distinguished
kind 25 pass its user Playlist classifier; 25 is recognized but is not required
by the game's PID/name selection.
[Container projection](../../src/iPodDB/library/_sqlite_projection.py#L98),
[container writing](../../src/iPodDB/SQLiteDB/database.py#L846).

## Captures and fixtures checked

The four databases under `C:/Users/JohnG/Coding/ipods/Classic6.5/` and the lab's
`captures/2026-10-26-itunesdb/iPod_Control__iTunes__iTunesDB` parsed successfully,
but none contained a Playlist title including Phase. This is a limited inventory,
not a claim that the repository has no other useful captures.

The lab capture SHA-256 is
`be6ad0b1b328676e973a908c204e3cbffe9a9ace8e0c779199567429c30158bf`.
The Original tests cited above remain useful controlled fixtures for preserving
25, not authenticated captures that prove its native consumer.

## Implementation boundary after the native contract is established

The likely required work is to expose a typed Phase Playlist intent or source
classification, preserve it on existing Playlists, and encode its verified native
marker during explicit creation in every required dataset. This is an
implementation direction, not an accepted enum or architectural decision.

Any required per-song analysis and companion artifacts need explicit preparation,
validation, identity dependencies, and publication through Storage together with
the Library. Merely changing a title or setting the historical halfword must not
be advertised as working custom-song support until the game-side requirements
are verified. This follows the existing retained-document and preparation
boundary. [ADR-0021](../adr/0021-prepare-library-drafts-over-retained-documents.md).

## Classic 2.0.1 main-library importer follow-up

The inspected initialized OSOS is exactly SHA-256
`220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`.
Its main DRAM mapping is runtime `0x08000000`, input offset `0xB65C`. The following
claims concern that firmware's ordinary main-library import path, not every
consumer of iTunesDB in the firmware.

`Research_ImportPlaylistDataset` at `0x08072F30` reads each MHYP header into a
stack buffer starting at `SP+0x104`. Instructions `0x0807306C..0x08073084` establish
the destination and read length `0x6C`. Consequently disk `+0x50` and `+0x52` are
stack locations `SP+0x154` and `SP+0x156`. Neither field is loaded or copied into
the native Playlist by this function. The complete header is passed only to its
byte-swap and absent-tail preparation helpers before individual understood fields
are consumed. The byte-swap helper `0x0806D408` also does not touch either
halfword. This is direct static evidence that changing 25 at disk `+0x52` cannot
change the ordinary imported Playlist through this path.
[Importer pseudocode](../../../ipod-firmware-lab/artifacts/phase-firmware-seeds/08072f30-Research_ImportPlaylistDataset.c),
[importer ARM instructions](../../../ipod-firmware-lab/artifacts/phase-firmware-seeds/08072f30-Research_ImportPlaylistDataset.asm.txt),
[byte swapping](../../../ipod-firmware-lab/artifacts/phase-firmware-seeds/0806d408-FUN_0806d408.c).

The construction path is also independent of disk 25:

- `0x0807310C..0x08073134` selects a context halfword according to the master and
  Podcast bytes and stores it into construction-parameter `+0x12`.
- Wrapper `0x08025E40` does **not consume that halfword**. It reads only parameter
  `+0x00` (Track Store), `+0x0C` (parent cursor), and `+0x10` (master boolean), and
  calls creator `0x0803CFAC` with a literal native kind.
- The literal at `0x08025E68` is **`0x66696C65`**, the four-character native kind
  `file`. It was read directly from the hash-matched initialized image.
- Creator `0x0803CFAC` stores its second argument at native Playlist `+0x13C`.
  Master status separately supplies creation flag 2 and native flags130 bit `0x40`.

`Research_CreateFilePlaylistFromImportParams` is therefore a supported proposed
name for `0x08025E40`; disk special-purpose value 25 must not be conflated with
native kind `file`.
[Wrapper ARM instructions](../../../ipod-firmware-lab/artifacts/phase-firmware-seeds/08025e40-FUN_08025e40.asm.txt),
[creator](../../../ipod-firmware-lab/artifacts/mhii-unknown-fields-20261028/0803cfac-FUN_0803cfac.c).

The root importer `0x080422E0` dispatches dataset 1 to Track import and imports
only the first dataset 2 or 3; other datasets, including 5, are skipped. Thus
dataset-5 processing cannot silently supply the missing field on this particular
path. A separate game-facing database reader remains a live investigation target;
these findings do **not** imply that the entire firmware ignores `+0x52`.
[Root importer](../../../ipod-firmware-lab/artifacts/phase-firmware-seeds/080422e0-Research_ITunesDB_ValidateAuthenticateAndImport.c).

## Phase 1.0 data assets and song preparation

The separate non-executable asset audit used the preserved `Games_RO/1D000`
installation and `ipg/Phase.ipg`. All **30 non-executable files** in the IPG were
byte-identical to the installed copies. No executable was decrypted or analyzed
in this subtask. Primary-file identities are recorded in the
[asset receipt](../../../ipod-firmware-lab/artifacts/phase-assets/index.json):

| File | SHA-256 |
| --- | --- |
| `main.hdr` | `15c365d262b8f173c31006c50ba4aef1343bef089fe5eff7b839f3521769ef5c` |
| `main_0.ark` | `f1f7e85156a4d0ea371637ea23c20139d698b149a32e3753970a60524a748a73` |
| English instruction image | `d4e86188aa4d6cdc77f6f1ec39ee3479f4c50b3aa76a2eedb7fbddddbca7059a` |

The English manual explicitly describes iTunes **7.5 or later**, automatic creation
of the Phase Music Playlist, and automatic generation of gameplay information
when songs are added to it. It then instructs the user to sync both the Playlist
and game. Thus the primary game documentation establishes that Playlist selection
and per-song gameplay preparation are separate requirements. The manual itself
does not specify numerical duration bounds.

### Bounded ARK and configuration extraction

`main.hdr` is 21,635 bytes. Its first four little-endian words are
`3, 1, 1, 27890840`; the last value matches `main_0.ark` exactly. A 8,935-byte
string area starts at `+0x14`, followed by 1,048 string offsets and **424 file
records**. Each file record contains five little-endian words: ARK offset,
filename-string index, directory-string index, byte count, and a final word
that is zero for every inspected record. All records are in bounds and the
table ends exactly at the HDR end. This is a successfully reconstructed layout
for this particular header, not a general implementation of every ARK version.
[Complete index](../../../ipod-firmware-lab/artifacts/phase-assets/ark-index.json).

The data-only extractor completely consumed `config/gen/phase.dtb` (216,765 bytes),
`config/gen/conv_phase.dtb` (32,595 bytes), and `ui/eng/gen/locale.dtb` (12,523
bytes). The main configuration's integer parameters explicitly contain:

| Configuration path | Value | Meaning supported by its authored name |
| --- | --- | --- |
| `conv/song_duration_min_sec` | `30` | Configured minimum song duration, seconds |
| `conv/song_duration_max_sec` | `1800` | Configured maximum song duration, seconds |
| `game/game_state/arcade_max_songs` | `5` | Configured Marathon/arcade song count |
| `song_provider/soundtrack/num_songs` | `7` | Bundled soundtrack count |

These bounds are directly present in configuration; whether the executable accepts
exactly 30 and 1,800 seconds still requires checking its comparisons. The English
locale independently instructs users to select at least five playable songs for
a Marathon. It also contains distinct UI states for songs requiring iTunes
encoding and songs rejected for being too short or too long. The exact runtime
gates should be traced before assigning meanings to every state value.
[Decoded main configuration](../../../ipod-firmware-lab/artifacts/phase-assets/config/gen/phase.json),
[decoded English locale](../../../ipod-firmware-lab/artifacts/phase-assets/ui/eng/gen/locale.json).

### Bundled analysis files are separate PHZ assets

The authored soundtrack configuration pairs each audio file with a `.phz` file
and a duration. The PHZ entries are stored inside the ARK's `midi/` directory:

| Audio | Analysis | Analysis bytes | Configured duration, ms |
| --- | --- | --- | --- |
| `a.m4a` | `midi/aaa.phz` | 4,234 | 240,117 |
| `b.m4a` | `midi/bbb.phz` | 3,786 | 217,962 |
| `c.m4a` | `midi/ccc.phz` | 4,874 | 232,533 |
| `d.m4a` | `midi/ddd.phz` | 5,370 | 252,029 |
| `e.m4a` | `midi/eee.phz` | 5,754 | 247,060 |
| `f.m4a` | `midi/fff.phz` | 2,170 | 138,176 |
| `g.m4a` | `midi/ggg.phz` | 3,146 | 272,266 |

All seven PHZs begin with the same ten bytes:
`70 68 61 02 01 00 00 00 40 00`. Interpreted structurally, the observed prefix is
`pha\x02`, little-endian word 1, and halfword 64; the semantics of the latter
fields remain unproved by this asset-only audit. After those ten bytes, all
seven remaining lengths are multiples of **16**, and their contents do not show
plain MIDI headers. This identifies useful bounded inputs for the executable
reader investigation; it does not yet establish a cipher or writable PHZ format.
[Extracted PHZs and hashes](../../../ipod-firmware-lab/artifacts/phase-assets/index.json).

The seven bundled audio files are stereo 44.1 kHz AAC-LC (`mp4a.40.2`) at a stated
256 kbps; the additional `m.m4a` is 128 kbps. Those are positive examples, not
evidence that Phase rejects other audio formats. In particular, observed bundled
analysis names do not establish the destination path or naming scheme for user
song analysis. That still belongs to the executable and firmware investigation.

## Classic game-facing Metadata API follow-up

The Phase executable's Metadata import table was matched to the hash-bound Classic
2.0.1 firmware descriptor. The firmware API is a handle-based facade over the
ordinary Library Browser, Playlist models, and Track models. These concrete
bindings resolve the relationship between game identifiers and serialized IDs:

| Metadata slot | Firmware wrapper | Proposed semantic name |
| --- | --- | --- |
| 45 | `082A0204` | `GameMetadata_OpenMainLibrary` |
| 46 | `082A01EC` | `GameMetadata_CloseLibrary` |
| 47 | `0829F6C0` | `GameMetadata_ResetToMasterPlaylist` |
| 48 | `082A0A40` | `GameMetadata_SelectPlaylist` |
| 57 | `082A0A10` | `GameMetadata_SetMediaKindFilters` |
| 61 | `082A06EC` | `GameMetadata_GetUserPlaylistCount` |
| 63 | `082A0DFC` | `GameMetadata_GetSelectedPlaylistSongCount` |
| 78 | `0829FACC` | `GameMetadata_AcquireTrackByIndex` |
| 89 | `0829FA1C` | `GameMetadata_AcquireUserPlaylistByIndex` |
| 95 | `0829F824` | `GameMetadata_ReleaseTrack` |
| 97 | `082A1148` | `GameMetadata_GetTrackPersistentId` |
| 100 | `082A15AC` | `GameMetadata_CopyTrackLocation` |
| 101 | `082A14E0` | `GameMetadata_CopyTrackTitle` |
| 102 | `082A0C24` | `GameMetadata_CopyTrackAlbum` |
| 103 | `082A0C74` | `GameMetadata_CopyTrackArtist` |
| 107 | `082A1360` | Other text token; exact meaning unresolved |
| 119 | `082A0EEC` | `GameMetadata_GetTrackDurationSeconds` |
| 120 | `082A0F10` | `GameMetadata_GetTrackDurationMilliseconds` |
| 162 | `082A0790` | `GameMetadata_GetPlaylistPersistentId` |
| 164 | `082A07DC` | `GameMetadata_CopyPlaylistTitle` |

These are proposed names, not recovered original symbols. Wrapper exports and
their direct dependencies are preserved under
[used Metadata calls](../../../ipod-firmware-lab/artifacts/phase-metadata-used/requests.tsv),
[additional Playlist calls](../../../ipod-firmware-lab/artifacts/phase-metadata-playlists/requests.tsv),
[Track acquisition](../../../ipod-firmware-lab/artifacts/phase-metadata-track-factory/requests.tsv), and
[tail-called methods](../../../ipod-firmware-lab/artifacts/phase-metadata-tail/requests.tsv).

Correction, 2026-10-30: this table previously mislabeled slots 100, 101 and 107
as Title, Artist and Album. The [four-game investigation](unique-game-library-contracts.md#correction-to-earlier-sdk-semantic-names)
followed the concrete Classic Track vtable and native string readers: 100 is
media location, 101 is title, 102 is album and 103 is artist. The prior Album
label for 107 is withdrawn; its native Track `+0x44` text token remains unnamed.
These research-name corrections do not change the persistent-ID or Playlist
selection findings.

### Playlist enumeration and identifiers

Slot 45 constructs the 0x48-byte model using `LibraryBrowser_Init` (`0811BFD4`),
whose concrete vtable is `0895B978`. Slot 47 reaches `08119C70`, selecting the
main native list. Slot 61 reaches `0811A398`, which returns the owner list count
minus one. Slot 89's member-function descriptor resolves to `0811A6FC`, which
adds one to the requested index before `0811AF40` obtains the native list. Thus
the user-facing enumeration omits the main list by index; it is not a scan for
MHYP `+0x52 == 25`.

Slot 162 reaches concrete Playlist getter `0827E5EC`. Its ARM instructions at
`0827E610` perform **`LDRD R0,R1,[native_playlist,#0x30]`**, returning the complete
64-bit persistent ID imported from MHYP `+0x1C`. Slot 48 reaches `0811A8F4`,
which finds the corresponding browser list by that persistent ID. Playlist
handle numbers and enumeration indices are separate from this persistent ID.
[Enumeration and selection](../../../ipod-firmware-lab/artifacts/phase-metadata-native/requests.tsv),
[Playlist persistent-ID instructions](../../../ipod-firmware-lab/artifacts/phase-metadata-native/0827e5ec-FUN_0827e5ec.asm.txt).

### Track identity, duration, and media filters

Slot 78 constructs a 24-byte `MediaItem_InitFromRecord` (`08248A78`) object and
registers a Track handle. Its concrete vtable is `0897BBC0`. Slot 97 resolves
through vtable `+0x0C` to `0827B7F4`, which reads native Track `+0x110/+0x114`
into **R0/R1**. Those are the full MHIT `+0x70` persistent-ID bytes, represented
by current iOpenPod's `db_track_id`; this is not MHIT `+0x10` numeric Track ID.
The decompiler's provisional 32-bit return type must not override these
instructions.
[Track identity instructions](../../../ipod-firmware-lab/artifacts/phase-metadata-track-values/0827b7f4-FUN_0827b7f4.asm.txt).

Slot 119 reaches `0827C3F4`, which divides the unsigned native duration at `+0x5C`
by **1,000**, returning whole seconds. Slot 120 reaches `0827ADF8`, returning the
same source value as exact milliseconds. A synthetic native probe executed the
unchanged getters and integer-division instructions for **26 cases**, including
nonzero high PID words, invalid models, 29,999/30,000/30,999 ms, and
1,800,000/1,800,999 ms. The only adaptation replaced model validity with explicit
return-0/return-1 callbacks; it did not substitute the getters or division.
[Native probe receipt](../../../ipod-firmware-lab/artifacts/phase-metadata-native-getter-probe.json),
[probe source](../../../ipod-firmware-lab/scripts/phase_metadata_getter_probe.py).

Phase's requested SDK media masks `1` and `0x7E` reach `0811AD88`. Converter
`0809EA88` maps them to native include mask **1** and exclude mask **`0x016E`**,
stored at browser `+0xC2C/+0xC30`. Existing consumer `080C0D78` requires a
nonzero Track media kind to overlap the include mask and not overlap the exclude
mask. This is music filtering, not a distinguished-Playlist-25 predicate; other
independent browser filters remain active.
[Filter setter](../../../ipod-firmware-lab/artifacts/phase-metadata-track-values/0811ad88-FUN_0811ad88.asm.txt),
[mask conversion](../../../ipod-firmware-lab/artifacts/phase-metadata-track-values/0809ea88-FUN_0809ea88.asm.txt),
[filter consumer](../../../ipod-firmware-lab/artifacts/itunesdb201-pass1/080c0d78-MediaBrowser_EvaluateEntryFilters.c).

### Async file roots for game data

The AsyncFileIO slot-0 wrapper `0829E98C` reaches `081C93D8`, which calls
`GameFiles_BuildPath` (`080804BC`). For root mode **1**, the latter formats
`iPod_Control/gamedata_RW/<game-identifier>/<relative-path>` using the identifier
held at the game file context's `+4`. Consequently a supplied relative
`Phase Data/...` path belongs under the game's writable data subtree; it does
not belong under the installed `Games_RO` assets. The exact game identifier is
supplied by the current game context, rather than invented from a title.

`GameFiles_GetStorageDirectoryName` (`0807667C`) maps modes 0/4 to `games_RO`,
1 to `gamedata_RW`, 2 to `gamestats_WO`, and 3 to `gamedata_ShareRW`. Mode 3
uses a separate shared-path formatting branch without the per-game identifier.
Spellings above follow the firmware literals; the familiar on-device directory
names commonly use `Games_RO` and `GameData_RW` capitalization.
[Path builder ARM instructions](../../../ipod-firmware-lab/artifacts/phase-async/080804bc-GameFiles_BuildPath.asm.txt),
[mode mapping](../../../ipod-firmware-lab/artifacts/phase-files-track/0807667c-GameFiles_GetStorageDirectoryName.c).
