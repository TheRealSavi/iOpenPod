# Native Genius Mixes on Classic RetailOS 2.0.4 and 2.0.5

Classic Genius Mixes use distinguished MHYP records in the binary iTunesDB.
They do not require a new SQLite Library.itdb or a newly invented sidecar. The
Mix contains candidate Tracks from which the existing native Genius engine
generates playback. It is not an ordinary fixed Playlist, even though its disk
container and membership use MHYP and MHIP. The native engine still needs the
corresponding Track Genius IDs and the Classic Genius relationship database.

This report separates static firmware findings, offline execution, and Host
authoring policy. No physical iPod was read, changed, or used to validate playback
during this investigation.

## Exact sources and qualification

| Firmware | Logical OSOS SHA-256 | Playlist importer |
| --- | --- | --- |
| Classic family 38, RetailOS 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | `0x0808979c` |
| Classic family 35, RetailOS 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | `0x08089700` |

The images and their independent startup mappings are retained in
[Classic38FW][image38] and [Classic35FW][image35]. Addresses below are runtime
addresses in 2.0.5 unless a second version is explicitly named. An offset such as
MHYP `+0x52` starts at the chunk marker; a native object offset is a RAM field.

The 2.0.4 importer and the Mix controller, member-ID getter, generator constructor,
and artwork lookup were independently located by normalized ARM instruction
matching. The same authored fixtures then executed through both original
importers. This establishes the imported Mix representation on these two images,
not every historical release or all physical-device behavior. A local firmware
inventory did not contain a decrypted/mapped 2.0.3 image. Its public support
capability and the writer's format qualification remain separate decisions.
[Native probe][probe], [execution receipt][receipt]

## Disk representation

The file is the ordinary `iPod_Control/iTunes/iTunesDB`. The loader at
`0x08058afc` reads MHSD datasets sequentially. Type 1 imports Tracks. The first
type 2 **or** type 3 dataset imports Playlists through `0x0808979c`; a local flag
then skips subsequent type-2/type-3 datasets. Other dataset types, including 5,
take the skip path in this loader. Therefore an author should retain the
application's existing type-2/type-3 mirroring policy. A Mix only in dataset 5
does not reach this native consumer. [Database load wrapper][wrapper]

| Disk field | Native observation |
| --- | --- |
| MHYP `+0x52`, low byte | `0x20` sets native Playlist `+0x1ac` bit `0x40`, the Mix discriminator. `0x22` sets bit `0x20`, a different distinguished collection. |
| MHYP `+0x53` | Not consulted by this classification. Preserve it when changing the low-byte kind. |
| MHYP `+0x50` | Does not determine Mix classification in this importer. The probe tests both zero and 32 independently of `+0x52`. |
| MHYP `+0x1c`, u64 | Copied to native Playlist `+0x30/+0x34`; this is the Mix persistent identity used by the UI and artwork lookup. |
| Playlist MHOD type 1 | Title, imported through the ordinary Playlist name cache. |
| Playlist MHOD type 2 | Secondary text, imported into a separate cache/token; the Mix controller requests this text for its descriptive display. |
| MHIP `+0x18`, u32 | Ordinary short Track ID. Resolved against the imported Track table, then added to the Mix's candidate membership. |
| MHYP `+0x0c/+0x10` | Metadata-child and member counts control the native loops. |

The current shared schema calls the u16 at `+0x52` `phase_game_flag`. This is a
broader distinguished-kind field on these Classic targets: the exact byte value
32 is directly consumed as the Mix discriminator. The field's old name must not
be treated as evidence against that observed use. The separate u16 at `+0x2a`
has a different flag consumer. [MHYP schema][mhyp], [native importer][importer]

The importer reads a `0x6c`-byte MHYP prefix and skips any declared remaining
header. Both a `0x6c` header and the application's ordinary `0xb8` header passed
offline execution. It reads ordinary `0x4c` MHIP prefixes, resolving members in
stream order. Missing short Track IDs are skipped; duplicate members are retained.
That firmware tolerance is not a reason to author unresolved members.
[Execution receipt][receipt]

MHOD 54 has a separate, existing single-seed Genius Playlist path. The importer
resolves those persistent Track identities and stores a matched seed at native
Playlist `+0x218/+0x21c`. Mix startup does not use those fields. Authoring a Mix
does not require MHOD 54. [Native importer][importer], [Mix startup][providers]

## Native enumeration and display

After importing the database, `0x0805d6c8` walks native Playlists and separates
records with `+0x1ac` bit `0x40` into a Mix pointer array at context `+0xf74`, with
count at `+0xf78`. The ordinary Playlist array lives at different fields. The
provider implements its Mix-count virtual method at `0x08133544` and indexed
Mix lookup at `0x08133638`. The controller therefore uses the real imported
Playlists, rather than reconstructing Mixes from title strings or from a separate
file. [Collection construction][arrays], [provider methods][list]

The main menu's Mix action at `0x0822598c` chooses an introductory screen for
zero Mixes, a single-Mix screen for one, and the Mix browser for more. The browser
constructor/update at `0x081aaf1c` clamps its visible count to **12**. This is an
observed display limit, not a parser limit. A Host creation policy should avoid
making additional Mixes that this UI cannot reach. Existing extra records should
not be silently deleted. [Menu action][menu], [browser][browser]

Mix name getter `0x0829cf64` calls the ordinary name getter `0x08049624`. The
secondary display getter `0x0829c88c` calls `0x08049440`, matching the MHOD-2
cache populated by the importer. Controller `0x081ab3c0` requests both name and
secondary text. [Provider getters][list], [secondary display][track-artwork],
[controller][engine]

## Playback, candidates, and Genius identities

At `0x081abc00` the selected Mix must be valid and have nonzero member count.
The code allocates eight bytes per member, iterates the Playlist's members, and
calls `0x0829acd8` for each. That getter returns both words at native Track
`+0x118/+0x11c`; the ARM instructions explicitly set R0 and R1. The Track importer
at `0x0808a488` copies these from MHIT `+0x1e4/+0x1e8`, the **Genius ID**, not the
Track persistent ID at MHIT `+0x70` and not the short Track ID in MHIP.
[Startup][providers], [getter][importer], [Track import][track-artwork]

The three identity namespaces therefore remain separate:

1. MHIP short Track ID resolves a candidate Track in iTunesDB.
2. That Track's MHIT Genius ID selects metadata and relationships in the Genius
   graph.
3. MHYP persistent Playlist ID identifies the Mix and its optional artwork.

Constructor `0x08164868` stores the candidate array, count, title, Mix identity,
and generator settings. Startup `0x0816435c` builds the native Genius engine and
calls the multi-seed path at `0x082c13c0` when the Mix flag is set. A single
candidate delegates to the ordinary seed path. Multiple candidates are sampled
without replacement; the loop inspects at most **100** candidates and resolves
them using `0x0825ee10`. It then creates the generator using a resolved seed and
passes the remaining resolved seeds through `0x08260c24`.
[Generator initialization][generation], [multi-seed engine][engine]

The 100-candidate loop is a generation-time sampling limit, **not** a file member
limit. Do not truncate an existing or newly proposed membership to 100 based only
on this observation. The wrapper's count getter `0x0829c858` reads a native u16
member count; authoring should retain the existing database bounds and avoid
overflow rather than inferring an unlimited container.
[Member count][list], [multi-seed engine][engine]

The generator can fail before playback when no candidate yields valid Genius
metadata. A nonempty MHYP alone is insufficient. Mix authoring must coordinate
Track Genius-ID assignment and the existing Classic `Extras.itdb` graph update
as one Library preparation/publication. It must not substitute persistent Track
IDs for Genius IDs or emit an ordinary fixed Playlist and call it a native Mix.
[Native seed validation][engine], [existing graph contract][adr176]

Controller initialization at `0x08191d9c` reads the library's MHBD `+0xa4/+0xa6`
target/minimum counts through native root `+0x90c/+0x90e`. Mix startup supplies
the minimum as both initial target and minimum, while the completion predicates
at `0x081645c4` and `0x081647e8` compare the generated member count against those
stored thresholds. The existing graph authoring path was found to retain these
header fields unchanged, including their zero defaults. Explicit graph authoring
needs to initialize useful values; Mix records do not replace that setup.
[Controller and threshold consumers][controller-init], [startup][providers]

Zero is not an unlimited/default sentinel. Original collection loop `0x08164574`
tests target equality before calling the next-candidate routine. With readiness
true, target zero, minimum zero, and an empty result list, it immediately reports
completion and the minimum predicate accepts the empty result. Twelve offline
cases on 2.0.4/2.0.5 reproduced this: the zero-threshold case made **zero** candidate
requests; Mix target/minimum 10/10 collected ten and rejected a nine-track result;
25/25 rejected a 24-track result. [Threshold flow][threshold-flow],
[threshold probe][threshold-probe], [threshold receipt][threshold-receipt]

The local Classic captures below both contain MHBD target/minimum **25/10**:

- Laboratory capture `captures/2026-10-29-game-transfer-1515fb5d/iPod_Control__iTunes__iTunesDB`,
  SHA-256 `815f3c55f3abaa0cddc89b2ab841acbc6c0f3c3cc24f0a03da8763a31a6ac8c7`.
- iOpenPod private baseline `.scratch/baseline-classic-20261019/current-fresh-sync/devices-v2/Classic 6.5/iPod_Control/iTunes/iTunesDB`.

Using 25/10 for explicit new graph authoring is consistent with these captured
producer values and the application's existing Genius configuration. Native Mix
startup then collects its initial ten-track buffer. Raising the minimum to 25
would instead reject playable graphs that produce ten through 24 Tracks. This
does not authorize normal metadata saves to rewrite retained threshold values.

## Artwork and fallback

The Mix browser requests an image by the **Mix persistent Playlist ID** at
`0x081ab23c` and `0x081ab6cc`. `0x0815e298` passes that u64 to `0x08046474`, which
uses the native artwork store at device context `+0xf9c`. Lookup `0x08045668`
compares the requested ID with image-object `+0x10/+0x14`. This is not a lookup
of the first candidate Track's album artwork. [Artwork calls][providers],
[artwork lookup][generation], [image lookup][track-artwork]

If an image cannot be obtained, `0x081ab6cc` takes a built-in resource fallback
path and returns a drawable result. Dedicated Mix artwork is thus optional for
the initial data writer. This investigation has not yet qualified a new
ArtworkDB Mix-image producer; preserving existing artwork is the supported
conclusion. [Fallback branch][engine]

The subsequent [Mix artwork investigation](classic-genius-mix-artwork-2026-11-18.md)
qualifies the 2.0.5 browser's dedicated F1069 selection and proxy fallback through
native execution. It establishes 142 × 142 covers linked by Mix identity; the
complete Host producer and physical rendering remain implementation work.

## Offline execution

The [probe script][probe] executes the original importers, with synthetic file
read/skip/position, allocation, metadata-storage, Track lookup/insertion, and
notification services. These adapters isolate the format/control-flow question
without constructing the complete firmware OS or accessing a device. They do
not reimplement the Mix discriminator, header parsing, metadata dispatch, or
MHIP member dispatch being tested.

The [receipt][receipt] contains **40 passing cases** across both exact images:

- MHYP header sizes `0x6c` and `0xb8`.
- Distinguished kinds 0, 32, 34, `0x120`, and 33.
- Independent `+0x50` values 0 and 32.
- Native Mix and alternate-kind flag checks.
- Full 64-bit Mix persistent identity preservation.
- MHOD-1 title and MHOD-2 secondary-text dispatch.
- Ordered repeated members and a missing Track-ID control.

The application writer's actual fixture was then tested separately. Its
`.scratch/classic-genius-mix-qualification/iTunesDB` contains Track short IDs
1/2, persistent IDs 101/102, Genius IDs 1001/1002, and Mix persistent ID 900
(`Test Mix`) with candidates 2 then 1, mirrored into datasets 2 and 3. Both
datasets executed through both stock importers: **four further native cases**.
All consumed the complete MHLP, classified one Mix, preserved its identity and
title, and imported candidate order correctly. The real Genius-ID getter then
returned 1002 followed by 1001 from the resulting member Track objects. The
fixture's MHBD thresholds were 25/10. The final fixture was regenerated after
the writer began assigning MHIP occurrence persistent IDs through the ordinary
Playlist allocator, then passed all four cases again. Its occurrence IDs are
303/304 in dataset 3 and 305/306 in dataset 2; its complete iTunesDB SHA-256 is
`85955f207a148d733ba7fce6993cdcaca0cd43fafd97d3991d39279207324774`.
[Authored-fixture probe][authored-probe],
[authored-fixture receipt][authored-receipt]

The static exports and execution receipt live in the ignored sibling laboratory
artifact directory, so this report retains exact function addresses and firmware
hashes even when the private evidence files are absent from a public checkout.
No claim here establishes successful physical Mix browsing/playback, complete
Genius recommendation quality, 2.0.3 writer compatibility, or newly authored Mix
artwork. Those are distinct from the demonstrated native record import.

[image38]: ../../../ipod-firmware-lab/Classic38FW/README.md
[image35]: ../../../ipod-firmware-lab/Classic35FW/README.md
[probe]: ../../../ipod-firmware-lab/scripts/probe_classic_genius_mix_import_20261118.py
[receipt]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/native-import-probe-formatted.json
[wrapper]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-import-classic38-20261113/08058afc.c
[importer]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/importers.c
[providers]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/providers.c
[arrays]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/offset_access.c
[list]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/native_list.c
[menu]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/seed/0822598c.c
[browser]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/seed/081aaf1c.c
[generation]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/generation.c
[engine]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/mix-engine.c
[track-artwork]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/track-artwork.c
[controller-init]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/mix-controller-init.c
[threshold-flow]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/generation-thresholds.c
[threshold-probe]: ../../../ipod-firmware-lab/scripts/probe_classic_mix_thresholds_20261118.py
[threshold-receipt]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/native-threshold-probe-final.json
[authored-probe]: ../../../ipod-firmware-lab/scripts/qualify_authored_classic_genius_mix_20261118.py
[authored-receipt]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/app-authored-occurrence-import-probe.json
[mhyp]: ../../src/iPodDB/iTunesDB/shared/chunk_defs/mhyp.py
[adr176]: ../adr/0176-preserve-and-author-native-genius-data.md
