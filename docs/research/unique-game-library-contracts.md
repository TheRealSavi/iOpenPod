# Music-library integration in four click-wheel games

Research date: 2026-10-30. This investigation inspected the supplied game files,
decrypted executables, followed ARM code and firmware API dispatch, and executed
selected original routines offline. It made no physical iPod changes and added
no product behavior. The support work below is proposed, not an accepted ADR.

## Findings that change the support plan

| Game | Mechanism established by this investigation | iOpenPod consequence |
| --- | --- | --- |
| Song Summoner | Fighters retain full 64-bit Track persistent IDs and cumulative play-count baselines. Normal positive count deltas earn ten points per play, once per distinct song. | Preserve identity, real cumulative counts, and opaque game saves. No separate listening-event exporter is needed for this inspected path. |
| iQuiz | Custom content is a directory of text and optional artwork. `.quizPack` is a separate compressed installer container. Later iQuiz is bundled in firmware resources as `11004`. | Add a bounded pack importer and a dedicated custom-content workflow, including built-in iQuiz detection. Do not gate it solely on an installed Games_RO manifest. |
| musika | The game reads song metadata and maintains per-song score records keyed by full persistent IDs. | Preserve accurate titles, playable media, IDs and existing score files; no Phase-style chart generation was found in the traced integration. |
| The Sims DJ | Purchased songs retain persistent IDs; players assign their in-game genres. Missing songs are removed and refunded by the game. | Preserve IDs and saves. A Host genre-conversion system or automatic save repair is not justified. |

These conclusions are build-specific. In particular, the later iQuiz executable
was located but not successfully decrypted, and the old and new Metadata SDK
UUIDs must not be treated as interchangeable.

## Inputs and evidence discipline

The supplied collection root is
`C:/Users/JohnG/Downloads/iPodGames/ipodclickwheelgamespreservationproject-main`.
Game installations are below
`iPod.Games.Files/iPod Games Files/{compatibility}/iPod_Control/Games_RO`.
The firmware lab is `C:/Users/JohnG/Coding/ipod-firmware-lab`.

| Manifest title | GUID | Version | Executable builds in supplied manifest |
| --- | --- | --- | --- |
| SONG SUMMONER | `24000` | `1.0` | `hd_4614181.bin` platform 1; `hd_4614323.bin` platforms 2/3 |
| iQuiz, Video installation | `11002` | `1.0` | `TWA_1_1_2902110.bin` platform 1 |
| musika | `1C300` | `1.0` | `molly_1_1_3028618.bin` platform 1 only |
| The Sims DJ | `15036` | `1.0` | `SimsDj_2002782.bin` platform 1; `SimsDj_2002889.bin` platforms 2/3 |

These are direct manifest observations, not inferred compatibility expansions.
The principal firmware bridge is Classic 120GB RetailOS 2.0.1, prepared OSOS
SHA-256 `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`.
The native verifier/decryption experiments use the original SINF and manifest
digest. Their explicit software AES, allocation, and thread-state adapters do not
constitute a complete firmware boot. Original inputs remain separate from outputs.

All game addresses below use the decrypted `eapp` logical base `0x18000000`.
Firmware addresses refer to the hash-bound Classic build above. Function names
are analyst descriptions, not recovered source symbols. Static code, limited
native execution, bundled help, and external reports are identified separately.

## Song Summoner

### Identity and fighter generation

The detailed analysis is of build **4614323**. Both supplied builds were decrypted,
but platform 1 imports an older Metadata UUID with 152 entries. Build 4614323's
169-entry Metadata UUID, `1eeeb60309134d1b77a8c3ca3298fa7b`, matches the mapped
Classic SDK. Its encrypted SHA-256 is
`7c51de506f6d798127aa23d4c678028510a86aac1e8b5f48eaa6aa1582e437f6`;
plaintext SHA-256 is
`6ccc7821d71874a5022c86d8c59561ad0c652e361b8a3004a0e348ec8f554484`.
See the [decryption receipt][ss-decrypt] and [import map][ss-imports].

Constructor `0x18014274` stores the full supplied persistent ID in the first
eight bytes of a `0x68`-byte fighter record. A baseline cumulative play count is
stored at record `+0x5c`. The relevant state has 75 records at `+0`, and another
20 at `+0x1e78`; the listening routine selects records with `+8 != 0` and
`+0xc == 0`. The wider meanings of those flags remain unresolved.
[Constructor][ss-constructor], [listening routine][ss-listening].

Fighter generation is not established as audio-signal analysis. The inspected
constructor ORs a local copy of the persistent ID with the Track's 64-bit sample
count, sums the eight resulting bytes, and uses modulo 46, game tables and
additional random selections. The saved ID itself is unchanged. Metadata slot
158 reaches firmware `0x082a0f34`, vtable `+0x150`, then `0x0827b284`, which
reads native Track `+0x100/+0x104`. The importer maps those words from MHIT
sample count `+0xbc`. This is a traced input to the constructor, not a complete
reconstruction of every fighter attribute. [Constructor][ss-constructor],
[firmware bridge receipt][counter-probe], [Track importer][track-importer].

### Listening outside the game

Routine `0x18022428..0x180226fc` collects distinct persistent IDs across the two
fighter arrays, keeping the first baseline encountered for a repeated ID. It
resolves each Track, checks validity, reads its current cumulative count, awards
points, then updates every eligible resolving fighter's baseline. Missing Tracks
receive no points and keep their old baselines. It does not consult a per-play
timestamp or external listening log in this path. [Game instructions and
pseudocode][ss-listening].

The bridge is explicit:

```text
fighter persistent ID
  -> game 0x18006f38 / Metadata 79: resolve Track
  -> game 0x180071a0 / Metadata 127: current count
  -> firmware 0x082a15fc / MediaItem vtable +0xc4
  -> 0x0827c708 / native Track +0x90
  -> cumulative play_count_1, serialized MHIT +0x50
```

The independent [firmware probe][counter-probe] executes that unchanged count
getter with a synthetic MediaItem and explicit validity callback. Six cases
confirm that it reads the cumulative total and ignores the secondary counter.

For ordinary ranges, the reward is `10 * (current_count - saved_baseline)` when
the signed 32-bit difference is positive. The pool normally caps at 500. Its
addition is stored to signed 16 bits before the cap check, however, so large
artificial count jumps can overflow into negative values. Baselines update even
after a count decrease. This is a reason to preserve real counts, not a reason
to introduce Host-authored rewards or rewrite game saves. [Native probe][ss-probe].

The original game routine passed 13 synthetic-state probes, including duplicate
fighters across both arrays, unequal duplicate baselines, missing Tracks,
unchanged/decreased counts, normal cap boundaries, counter wrap and overflow.
For example, `4 -> 5` earns ten points, `40 -> 2` earns none and saves baseline
two, and `0xffffffff -> 0` earns ten through native subtraction wrap.
Allocation/free and SDK lookup/count calls are modeled; the reward instructions
execute unchanged. [Probe source][ss-probe-source], [receipt][ss-probe].

### Saves and remaining uncertainty

Virtual names include `/userdata`, `/ugd00.bin`, `/ugd01.bin`, and a per-user
filename format `S%02d%08x.bin`. Save/load helpers copy `0x4e08` bytes of state
containing the fighter arrays and point pool. These observations do not establish
the complete disk envelope or the final mapping of every virtual name into the
firmware sandbox. No initialized physical save was supplied. Preserve runtime
files opaquely; the memory offsets above are not a save-editor specification.
[Save helper][ss-save], [load helper][ss-load], [user slot names][ss-slots].

## iQuiz

### Installed Video game versus bundled later game

Video build **2902110** was decrypted and analyzed. Its encrypted SHA-256 is
`07c2538469945ce509452d8237c35ca96144dcb740c62013b7929903d6300a1f`;
plaintext SHA-256 is
`e8d8f83e307a2124b2b6aa58458590b255beef831da02c3fb9d89fa63edafe9f`.
[Decryption receipt][iquiz-decrypt].

The Classic firmware resource package `Firmware-33.9.0.1`, SHA-256
`42d6a0c18e7e3fc7cc181a15973ee12757769e25354d3320f0bff5c5d8ae17eb`,
contains a FAT16 filesystem at file offset `0x7e00`. Its
`/Resources/Games/games_RO/11004` directory contains 320 files, including an iQuiz
manifest for platforms 2/3 and encrypted **TWA_n25_3178308.bin**. That executable's
SHA-256 is
`52cb046243c8f609cdcb8a7ecb9acf01463fc2df19f1525f0329410180efb9f3`.
The external-game authorization harness rejected the bundled authorization context,
so its parser was not analyzed. Finding its GUID in firmware does not prove every
later model uses an identical overlay lookup. [Extraction receipt][iquiz-extract].

The directly traced Video custom path is:

```text
iPod_Control/Games_RO/11002/UserTrivia/Packs/<pack-folder>/trivia.txt
```

The [preservation project's guide][iquiz-guide] supplies the later `11004`
destination with the same suffix. The matching built-in GUID is independently
verified above; later device overlay behavior still needs acceptance. Since the
supplied Games_RO tree has no physical `11004` installation, iOpenPod's existing
manifest-only game catalog cannot be the sole qualification for this workflow.
[Video metadata reader][iquiz-metadata].

### Pack directories and `.quizPack` containers

The game loads directories containing line-oriented `trivia.txt`, optional
localized trivia files and skin assets. Apple's supplied
`11002/UserTrivia/Samples/sample1/trivia.txt` documents examples; its `HIDDEN YES`
and `GROUP Examples` affect visibility/grouping. Samples include TGA images;
author-made archives also include IPD images. Save/result code refers to pack paths
and `Results/%s.txt`, so renaming a pack is not established as identity-neutral.
[Metadata reader][iquiz-metadata], [saved-pack comparison][iquiz-saved],
[results code][iquiz-results].

All eight supplied `iQuiz/Maker/*.quizPack` files use this format:

| Element | Observed representation |
| --- | --- |
| Magic | Four bytes `JWWq` |
| Enter directory | `bdir`, little-endian u16 name byte length, name bytes |
| File | `file`, u16 name length/name, u32 uncompressed size, u32 compressed size, zlib payload |
| Leave directory | `edir` |
| Trailer | Little-endian CRC32 of every preceding byte, including magic and final `edir` |

All eight CRCs validate; 32 file payloads decompress to declared sizes. Thirty-one
are byte-identical to existing `iQuiz/QuizFiles` exports; the extra file is
`.DS_Store`, absent from the exported content. This establishes a practical
importer without running the archived Mac applications. Copying an intact
`.quizPack` into Packs does not match the traced native loader. Entry names in
these eight containers decode as UTF-8; that does not establish all historical
name encodings. [Package inspection and corpus receipt][iquiz-packages].

Of 466 exported community `trivia.txt` files, 363 decode as UTF-8 and 103 do not.
All use LF and none has an observed UTF-8/UTF-16LE BOM. Preserve existing bytes
and diagnose encodings rather than silently converting all files. Native header
parsing retained an UTF-8 `é`; the traced character decoder handles one-, two-
and three-byte forms, not four-byte Unicode. This is a decoder finding, not
proof that every community pack is valid. [Corpus receipt][iquiz-packages],
[decoder][iquiz-decoder], [header probe][iquiz-header].

### Parser constraints and the reported pack limit

Native probes execute original Video-game routines, not a new implementation of
the parser. The header probe adapts only allocation/free and ASCII whitespace
classification; keyword/count probes use no instruction substitutions.
[Header probe][iquiz-header], [keyword/count probe][iquiz-parser].

- Header defaults are ASK 10 and LOSE 3. CRLF, blank lines and `//` comments were
  exercised. Outer normalization limits ASK to question count, defaults nonpositive
  ASK to 10, defaults negative LOSE to 3, and limits LOSE to seven and then ASK.
  For 12 questions, ASK 1001 / LOSE 99 becomes 12 / 7.
- Keyword matching is case-insensitive ASCII prefix matching: even `titlefoo`
  matches TITLE. An authoring/import validator should emit canonical directives
  and report ambiguity rather than rely on that permissiveness.
- Static routine `0x1801ceb4` retains at most 1,000 questions. The MC parser uses
  a `0x300`-byte question buffer and up to four `0xc0`-byte answer buffers; TF has
  its own explanation area. These are byte-buffer extents, not established
  Unicode-character limits. [Question dispatcher][iquiz-questions],
  [MC parser][iquiz-mc], [TF parser][iquiz-tf].
- Original name collector `0x18006000` retains 64 names after 70 synthetic calls.
  It also has a `0x3f00` preappend buffer threshold. Menu constructor
  `0x18027f40` clamps custom count to 61; native inputs 58, 60 and 61 survive,
  while 62, 64 and 100 become 61. Built-in entries, hidden/malformed packs and
  enumeration ordering affect the actual menu. [Native results][iquiz-parser].

The guide's **58-additional-pack observation remains an upstream report**, not
a universal firmware limit. Conversely, a constructor accepting 61 does not prove
61 working visible custom packs. A future importer needs qualified capacity
diagnostics and physical boundary testing; neither number should become a
universal hardcoded promise.

Custom editorial trivia needs no iTunesDB or Game Authorization Store changes.
This investigation has not mapped the dynamic music-trivia game's exact metadata
predicates/getters. That remains separate work rather than an inferred requirement
to manufacture genre, year or album data.

## musika

The analyzed build is **3028618**, supplied only for platform 1. Its encrypted
SHA-256 is `7f2bf22e34bdc3cd101d487a5425313feb4b30029deb765501cd1427037aadc8`;
plaintext SHA-256 is
`c61f89386dd1f839739273151b81b2c133c81798cb8f3521198d1c5d3da1df00`.
Successful offline decryption using Classic routines does not establish Classic
launch compatibility. [Decryption receipt][musika-decrypt].

This game's older 152-entry Metadata UUID was matched independently to Video
family 25 OSOS, SHA-256
`784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251`.
Its slot numbers differ from the newer Classic/Sims SDK. Old slot 66, reached
through game `0x18006ba0`, supplies the title; projection `0x1802d538` requests
at most `0x100` SDK bytes, converts to the game's UTF-16 buffer and filters it.
Gameplay setup `0x18023e5c` consumes the resulting title string. The traced
integration requires accurate Library metadata, not Host-generated letter charts.
[Old SDK map][musika-imports], [Video bridge][musika-video],
[projection][musika-title], [gameplay setup][musika-gameplay].

Native filter `0x18008650` retains nonzero UTF-16 code units through `U+00ff`
and `U+3040..U+30ff`; others become `?`. It preserves ASCII case. An unchanged
routine probe maps `AaéЖ漢あア😀` to `Aaé??あア??`, including one replacement
for each surrogate of the supplementary character. Keep the actual Library title
unchanged: this is a game-local limitation. SDK encoding/truncation and every
downstream glyph path were not exhaustively tested. [Native receipt][musika-probe].

The score database is also identity-sensitive. Insertion `0x18016268` gets a
64-bit key through old Metadata slot 64, stores both words in a 24-byte record,
and has capacity 1,000. Lookup `0x18016458` compares both words. Six native
synthetic-RAM cases distinguish IDs with identical low words and different high
words. The lookup can match an unused zeroed slot when asked for zero, so zero
is not a safe fabricated identity. [Insertion][musika-insert],
[lookup][musika-lookup], [native probes][musika-probe].

`ScoreDatabase.dat` reader `0x1801667c` and writer `0x1801676c` use version
`0x11`, a 12-byte header, `N * 24` record bytes and trailer `0xdeadbeaf`.
`molly_settings.dat` is separate. The writer selects writable root mode 1;
preserve the game's runtime files rather than regenerating scores during Sync.
No initialized physical save was supplied, and a full save-editing contract is
outside this result. [Reader][musika-reader], [writer][musika-writer],
[settings][musika-settings].

## The Sims DJ

The analyzed build is **2002889**, platforms 2/3. Its encrypted SHA-256 is
`ee7c856805b202fb6a064c03ea9e53594b0fb50e4d4e295e168cc3fc4e0ba740`;
plaintext SHA-256 is
`e2a837515a12048b9a6ff701f82a88e9ca05bc5d5a17322bfe0960a23d21f350`.
Platform-1 build 2002782 was inventoried, not traced. [Decryption receipt][sims-decrypt].

Career purchases use 24-byte in-memory entries at career `+0x5b0 + N*0x18`.
For external Library songs, the low/high key words at entry `+8/+12` are the full
persistent ID. Browse code obtains it through Metadata 97; replay code passes
both words to Metadata 79 to reacquire the Track. A source marker distinguishes
Library songs from bundled numbered MP3 assets, whose keys must not be treated
as iTunesDB identities. [Purchase enumeration][sims-purchases],
[replay branches][sims-replay], [browse population][sims-browse].

Missing-song routine `0x18027d6c` checks Track validity and, in its modifying
branch, adds ten to career currency at `+0x57c`, then removes the purchase.
The bundled `15036/text_eng.txt` help also describes refunding deleted songs.
Thus regenerating persistent IDs during an ordinary rewrite can make surviving
songs appear deleted to the game. This refund path is statically traced, not a
physical-game observation. [Missing-song code][sims-refund].

The same bundled help says the player assigns each purchased song one of seven
game types: Pop, Rap, RnB, Rock, Dance, World or Country. The game constructs this
menu locally. This does not justify converting iTunesDB genres into seven labels
or rewriting saved categories. [Genre menu][sims-genres].

Playback `0x18006234` queues ordinary native audio: Metadata 100 supplies media
location, Metadata 120 exact milliseconds, and Audio 14 queues playback. Keep
paths, database references and duration coherent; this traced path has no required
Host-authored analysis sidecar. [Playback instructions][sims-playback].

Saves include `SaveState.sav` and `Profiles.dat`. Profile writer `0x18028780`
copies three `0xbe0` career blocks, including purchases, into its payload and
writes through root mode 1. The verified Classic root resolver maps that mode
to `iPod_Control/gamedata_RW/<game-id>/<relative-path>`. Preserve the `15036`
runtime subtree opaquely; the complete envelope/checksum variants were not
decoded. [Profile writer][sims-profile], [file writer][sims-file],
[existing root contract](phase-application-contract.md#async-file-roots-for-game-data).

## Correction to earlier SDK semantic names

The earlier [Phase application note](phase-application-contract.md#classic-game-facing-metadata-api-follow-up)
assigned guessed Title/Artist/Album labels to slots 100/101/107. Following the
concrete Classic Track vtable at `0x0897bbc0` establishes this correction:

| Newer SDK slot | Wrapper | Traced value |
| --- | --- | --- |
| 100 | `0x082a15ac` | Media location, through vtable `+0x10`, `0x0827b930` and the location resolver |
| 101 | `0x082a14e0` | Title, ultimately `0x0827b8ac` / `SongRecord_ReadTitle` |
| 102 | `0x082a0c24` | Album, ultimately `0x0827ba2c` / `SongRecord_ReadAlbum` |
| 103 | `0x082a0c74` | Artist, ultimately `0x0827bf7c` / `SongRecord_ReadArtist` |
| 107 | `0x082a1360` | Other text token at native Track `+0x44`; precise meaning unresolved |

The old labels are explicitly withdrawn in that note. This corrects research
annotations; it does not change current application behavior. The values must not
be transferred to musika's different old SDK by slot number alone.
[Concrete getter chains][sims-fields], [slot 107 chain][sims-107],
[slot 107 token][sims-107-token].

## Current iOpenPod coverage

The inspected checkout was HEAD
`328022b04c92f75e35d999c59a243557e70efbab` plus substantial user-owned Games and
Phase changes already present before this research. The following are current
source observations, not claims of physical game acceptance:

- [Identity resolution](../../src/iPodDB/library/_resolve_write.py#L394) retains
  existing primary persistent IDs and allocates IDs only for new Tracks, reserving
  both source identity fields. [Track verification](../../src/iPodDB/library/_track_verification.py#L203)
  checks that retained primary and secondary IDs survive. A differing retained
  secondary ID is not normalized.
- [Selective Track writing](../../src/iPodDB/library/_track_writing.py#L341)
  starts from retained records; new Tracks receive IDs explicitly. The
  [SQLite projection](../../src/iPodDB/SQLiteDB/database.py#L142) uses the Track's
  persistent ID for its item PID and projects cumulative play counts.
- [Playback Sidecar projection](../../src/iPodDB/library/_sidecar_projection.py#L92)
  merges native deltas into cumulative totals. [ADR-0100](../adr/0100-reconcile-firmware-playback-sidecars-on-device-selection.md)
  publishes that reconciliation on device selection and retires active evidence
  transactionally. Game save baselines are separate from Playback Sidecars.
- [Installation](../../src/iOpenPod/app/services/game_installation.py#L72)
  preserves existing runtime data while ensuring shared GameData_RW and
  GameStats_WO directories. [Uninstallation](../../src/iOpenPod/app/services/game_uninstallation.py#L16)
  intentionally removes the chosen game's executable and GUID-owned runtime data
  after its existing warning. Custom-pack changes should not use uninstall/reinstall.

The Original iOpenPod baseline is local `origin/1.x`, commit
`a20242428b93b672d14b37230772dbad75139c69`. A source/test search for these games'
names, `quizPack`, `Games_RO`, `GameData_RW` and `GameStats_WO` found no dedicated
contract. Its broader game references concern the historical Phase flag and
generic iTunes preference counters. Existing historical code therefore supplies
no stronger support specification for these four integrations.

## Proposed support increments

1. **Verify preservation before adding game-specific transformations.** Add
   integration fixtures for retained full IDs, cumulative counts and opaque game
   files through metadata edits, Track reorder, Sync, accepted media replacement
   and selection-time Playback Sidecar reconciliation. Removing/re-adding a song
   with a fresh persistent ID must not silently claim to restore its old game
   association. Equal titles, audio bytes or low 32-bit IDs do not prove identity.
2. **Implement iQuiz custom-pack management as a separate content workflow.**
   A pure typed codec should inspect the Host container/directory and report its
   contents and compatibility. The Application Layer should select the qualified
   iQuiz target, review collisions, and prepare bounded validated relative paths.
   Storage should publish additions/replacements/removals recoverably, leaving
   executable assets, authorization files and unrelated packs alone.
3. **Keep game saves game-owned.** Song Summoner points/fighters, musika scores
   and Sims purchases/categories should remain opaque. Ordinary Library saves
   should neither regenerate them nor attempt title-based relinking. User-controlled
   Backup Snapshots can preserve saves, but transaction safety cannot depend on
   automatic backups.
4. **Qualify later models independently.** Trace the bundled later iQuiz parser
   and verify game-facing IDs/counts on the relevant Nano SQLite firmware before
   promoting Classic-only findings to a family-wide contract. Exercise physical
   gameplay after ordinary saves and actual playback; offline probes establish
   individual routines, not scheduling, decoder or complete-device acceptance.

These increments fit the existing boundaries: iPodDB owns byte formats and shared
field definitions, the Application Layer owns workflows, Device Registry owns
qualified capabilities, and Storage owns every device mutation. Firmware images,
Ghidra and emulators stay in the lab. No runtime dependency addition is justified
by this investigation. See [ADR-0208](../adr/0208-prepare-game-authorizations-with-a-standalone-codec.md).

## Validation and limits

Focused existing product tests covered Track preservation, Playback Sidecars,
game installation and game removal: **163 passed, one failed**. The failing
existing `test_coordinator_binds_installation_to_current_device_and_dependencies[]`
asserts `1D000/empty`, while its fixture creates `Executables/empty`. The correctly
nested destination exists; the lower-level installation test checks that path
and passes. No product source or test assertion was changed for this research.

```powershell
uv run pytest tests/iPodDB/library/test_track_native_verification.py tests/iPodDB/library/test_sidecar_projection.py tests/iOpenPod/app/services/test_game_installation.py tests/iOpenPod/app/services/test_game_uninstallation.py -q
```

The new counter probe is reproducible from the lab with:

```powershell
uv run --script scripts/probe_game_metadata_counters_research.py
uv run --script scripts/probe_song_summoner_listening.py
uv run --script scripts/inspect_iquiz_packages.py
uv run --script scripts/probe_iquiz_parser.py
uv run --script scripts/probe_iquiz_header.py
uv run --script scripts/probe_musika_identity.py
```

Input hashes and adapters are recorded in the linked receipts. No physical
gameplay, physical pack installation, complete game-save format, or universal
cross-firmware limit is claimed.

[ss-decrypt]: ../../../ipod-firmware-lab/artifacts/song-summoner-p2/native-decryption.json
[ss-imports]: ../../../ipod-firmware-lab/artifacts/song-summoner-p2/imports.json
[ss-constructor]: ../../../ipod-firmware-lab/artifacts/song-summoner-p2/sdk-deep/18014274.c
[ss-listening]: ../../../ipod-firmware-lab/artifacts/song-summoner-p2/sdk-deep/18022428.c
[ss-probe]: ../../../ipod-firmware-lab/artifacts/song-summoner-p2/native-listening-probes.json
[ss-probe-source]: ../../../ipod-firmware-lab/scripts/probe_song_summoner_listening.py
[ss-save]: ../../../ipod-firmware-lab/artifacts/song-summoner-p2/saves/1805e104.c
[ss-load]: ../../../ipod-firmware-lab/artifacts/song-summoner-p2/saves/1805ddf0.c
[ss-slots]: ../../../ipod-firmware-lab/artifacts/song-summoner-p2/saves/18017628.c
[counter-probe]: ../../../ipod-firmware-lab/artifacts/game-metadata-counters-research.json
[track-importer]: ../../../ipod-firmware-lab/artifacts/phase-metadata-objects/08073bb8-ITunesDB_ImportTrackDataset.c
[iquiz-decrypt]: ../../../ipod-firmware-lab/artifacts/iquiz-game/native-decryption.json
[iquiz-extract]: ../../../ipod-firmware-lab/artifacts/iquiz-game/firmware-11004/extraction.json
[iquiz-guide]: https://github.com/Olsro/ipodclickwheelgamespreservationproject/blob/main/iQuiz/README.md
[iquiz-metadata]: ../../../ipod-firmware-lab/artifacts/iquiz-game/survey/1801d1f8.c
[iquiz-saved]: ../../../ipod-firmware-lab/artifacts/iquiz-game/survey/1803c95c.c
[iquiz-results]: ../../../ipod-firmware-lab/artifacts/iquiz-game/survey/1804661c.c
[iquiz-packages]: ../../../ipod-firmware-lab/artifacts/iquiz-game/package-inspection.json
[iquiz-decoder]: ../../../ipod-firmware-lab/artifacts/iquiz-game/detail/1803b61c.c
[iquiz-header]: ../../../ipod-firmware-lab/artifacts/iquiz-game/native-header-probe.json
[iquiz-parser]: ../../../ipod-firmware-lab/artifacts/iquiz-game/native-parser-probe.json
[iquiz-questions]: ../../../ipod-firmware-lab/artifacts/iquiz-game/parser/1801ceb4.c
[iquiz-mc]: ../../../ipod-firmware-lab/artifacts/iquiz-game/detail/1801cba4.c
[iquiz-tf]: ../../../ipod-firmware-lab/artifacts/iquiz-game/detail/1801ccd0.c
[musika-decrypt]: ../../../ipod-firmware-lab/artifacts/unique-games/molly_1_1_3028618/native-decryption.json
[musika-imports]: ../../../ipod-firmware-lab/artifacts/unique-games/molly_1_1_3028618/imports.json
[musika-video]: ../../../ipod-firmware-lab/artifacts/unique-games/molly_1_1_3028618/video25-metadata-exact.c
[musika-title]: ../../../ipod-firmware-lab/artifacts/unique-games/molly_1_1_3028618/score-survey/1802d538.c
[musika-gameplay]: ../../../ipod-firmware-lab/artifacts/unique-games/molly_1_1_3028618/score-survey/18023e5c.c
[musika-probe]: ../../../ipod-firmware-lab/artifacts/unique-games/molly_1_1_3028618/native-identity-probes.json
[musika-insert]: ../../../ipod-firmware-lab/artifacts/unique-games/molly_1_1_3028618/save-survey/18016268.c
[musika-lookup]: ../../../ipod-firmware-lab/artifacts/unique-games/molly_1_1_3028618/score-survey/18016458.asm
[musika-reader]: ../../../ipod-firmware-lab/artifacts/unique-games/molly_1_1_3028618/save-survey/1801667c.c
[musika-writer]: ../../../ipod-firmware-lab/artifacts/unique-games/molly_1_1_3028618/save-survey/1801676c.c
[musika-settings]: ../../../ipod-firmware-lab/artifacts/unique-games/molly_1_1_3028618/save-survey/1802e688.c
[sims-decrypt]: ../../../ipod-firmware-lab/artifacts/unique-games/SimsDj_2002889/native-decryption.json
[sims-purchases]: ../../../ipod-firmware-lab/artifacts/unique-games/SimsDj_2002889/save-survey/18027894.c
[sims-replay]: ../../../ipod-firmware-lab/artifacts/unique-games/SimsDj_2002889/save-survey/1801a2c4.c
[sims-browse]: ../../../ipod-firmware-lab/artifacts/unique-games/SimsDj_2002889/save-survey/1802ebc8.c
[sims-refund]: ../../../ipod-firmware-lab/artifacts/unique-games/SimsDj_2002889/save-survey/18027d6c.c
[sims-genres]: ../../../ipod-firmware-lab/artifacts/unique-games/SimsDj_2002889/save-survey/180273ec.c
[sims-playback]: ../../../ipod-firmware-lab/artifacts/unique-games/SimsDj_2002889/survey/18006234.asm
[sims-profile]: ../../../ipod-firmware-lab/artifacts/unique-games/SimsDj_2002889/save-survey/18028780.c
[sims-file]: ../../../ipod-firmware-lab/artifacts/unique-games/SimsDj_2002889/save-survey/18040cbc.c
[sims-fields]: ../../../ipod-firmware-lab/artifacts/unique-games/SimsDj_2002889/classic-track-fields.c
[sims-107]: ../../../ipod-firmware-lab/artifacts/unique-games/SimsDj_2002889/classic-slot107.c
[sims-107-token]: ../../../ipod-firmware-lab/artifacts/unique-games/SimsDj_2002889/classic-slot107-native.c
