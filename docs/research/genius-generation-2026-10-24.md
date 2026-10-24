# Native Genius generation investigation

Date: 2026-10-24. Investigation and authorized physical experiment; no application
Genius workflow or architectural decision added. Local source baseline:
`16fee285049ba66da067dc9ebf04eb146a1ba537`.

## Assessment

iOpenPod's private experiment generated data that a 120 GB Classic 6.5G accepted
for native Genius Playlist creation and playback. The user confirmed the result
after selecting Start Genius on the device. After Save and reconnect, readback
confirmed a firmware-created file containing 25 distinct music Tracks. This
establishes one working Track-seeded case, not a complete application workflow or
compatibility with every iPod. Independently, the upstream author reports native
Genius Mix playback on nano 5G and 6G.

A second local experiment produced a native Genius Mix on a 16 GB nano 7G running
RetailOS 1.0.4. After verified publication and safe eject, the user confirmed that
the Mix appears and plays. Its synthetic IDs, metadata, candidate graph, and compact
configuration were generated locally without calling Apple's Genius service.
This establishes initial native Mix playback, not continuous queue replenishment,
reboot persistence, subsequent Sync preservation, or musical recommendation quality.

A later read-only hardware probe established that this Classic runs RetailOS
2.0.1. Apple's 2.0.3 release notes introduce Genius Mixes for the Fall 2009 160 GB
Classic. The connected 120 GB model's existing firmware is therefore unsuitable
for a native Mix experiment; successful Track-seeded Playlists do not establish
Mix capability. No Mix database or firmware changes were made to that Classic.

The work separates into two problems: deciding which Tracks belong together, and
encoding those relationships for the firmware. The research substantially advances
the second problem. A local recommendation engine could replace the Apple service's
role, with different musical results. It would not reproduce Apple's private
recommendation dataset merely by writing the same file format.

Apple describes its Genius service as using information from the user's Library
and other customers' Libraries, with an Apple account and Internet connection.
That describes Apple's service workflow; it does not establish a network requirement
for firmware consuming locally authored data. See
[Apple's iTunes Genius documentation](https://help.apple.com/itunes/mac/12.7/en.lproj/itns22073.html).

## Evidence and provenance

- [Issue 261](https://github.com/TheRealSavi/iOpenPod/issues/261) reports native
  offline Mix playback on nano 6G RetailOS 1.2 and links the research.
- The research was inspected at
  [commit 57b7ae8](https://github.com/dotm5/Genius-Mix-Research/tree/57b7ae865a10177f725c90e946e1199c00411e53).
  Its later [cross-generation measurements][crossgen] include a nano 5G with 298
  Tracks and a nano 6G with 189 Tracks. Exact 5G firmware provenance still needs
  capture alongside any imported fixture.
- The [format description][format], [alignment discussion][align], and
  [hardware rounds][rounds] distinguish byte interpretation, simulation, and
  reported device observations. The Chinese reference documents contain later
  corrections that are essential when reading the issue and code comments.
- Original iOpenPod `v1.68.1`, commit
  `de300074a25f6f327b54a7141720e5fbff9d5c5b`, explicitly writes empty Genius tables
  in `src/iopenpod/sqlitedb_writer/genius_writer.py`. It supplies a schema baseline,
  not a recommendation engine.
- Current iOpenPod behavior was checked against ADR-0141, ADR-0150, the SQLite
  generator, retention, and validation code, plus a synthetic in-memory replay.
  That initial investigation did not access or change device files. The subsequent
  user-authorized Classic experiment captured and modified two device databases;
  its physical result and limits are recorded below.

## What the iPod needs

The upstream nano Mix path has four distinct inputs. A Mix container's members are
potential starting Tracks; they are not necessarily the complete set of Tracks
that can play. The Classic experiment instead joins MHIT Genius IDs to tables in
`Extras.itdb` and does not create a Mix container.

| Input | Representation | Responsibility |
| --- | --- | --- |
| Mix seeds | `Library.itdb.container` with `distinguished_kind=32`, ordered `item_to_container`, and `Dynamic.itdb.container_ui` | Expose a Mix and its possible starting Tracks |
| Track identity | `Library.itdb.item.genius_id`; related Dynamic field on schemas that have it | Connect a Library Track to Genius records |
| Candidate relationships | `Genius.itdb.genius_similarities` | Supply ordered candidate Genius IDs for graph traversal |
| Constraint keys and rules | `genius_metadata` and `genius_config` | Filter candidates and space Tracks sharing selected keys |

The firmware starts from either a user-selected Track or a sampled Mix seed,
traverses candidate relationships, applies constraints, and builds its playback
queue. The research describes these paths as sharing an evaluation core. This
supports a native on-device experience after Sync, including generating a Playlist
from a Track, rather than only transferring a precomputed ordinary Playlist.

Reported hardware ablations found that a Mix can work without `smart_criteria`
and with `smart_is_genius=0`; setting that flag alone is not an implementation.
`container_seed` is not part of the reported minimum Mix representation. Ordinary
Playlist persistence, saved Genius Playlists, and kind-32 Mixes need separate tests.
See [format relationships][format] and [round 8][rounds].

### Binary representations

- `item.pid` and `item.genius_id` are separate identity namespaces. Upstream's
  [custom generator][custom] assigns synthetic Genius IDs; Apple catalog matching
  is not inherently required for a local graph. iOpenPod would need stable,
  collision-checked allocation that coexists with retained IDs.
- Uncompressed similarities are little-endian `u32 flag=0`, `u32 payload_size`,
  `u32 count`, followed by `count` unsigned 64-bit Genius IDs. Payload size is
  `4 + 8*count`; total size is `12 + 8*count`. Compressed variants require separate
  evidence and preservation rather than treating every record as this layout.
- Metadata is an array of little-endian unsigned 64-bit constraint keys. These
  keys are not candidate edges or audio embeddings. Slot 0 supplies the cluster
  label in the captured factory configuration; other indexed slots supply spacing
  keys. The 21-slot representation is 168 bytes and supplies slot 20.
- Configuration entries describe cluster compatibility (`op=2`), same-key spacing
  (`op=1/3`), skip-history filtering (`op=4`), and randomized deferral (`op=5`).
  Playlist result thresholds occupy separate configuration columns.

These layouts come from the [upstream format description][format]. They require
bounded readers, explicit supported variants, and lossless Unknown Data handling
before becoming an iPodDB authoring contract.

### Two evidenced configuration approaches

| Approach | Evidence | Remaining consideration |
| --- | --- | --- |
| Captured factory configuration | The measured 5G and 6G configurations are byte-identical, 151,212 bytes, with seven entries and a 591-node cluster graph | Obtain and record the configuration's provenance; map local labels into compatible clusters |
| Constructed compact configuration | The 108-byte `cfg_limits` variant retains two spacing rules and skip filtering; the 48-byte variant has no constraint entries | Without the cluster rule, candidate graph construction must supply the desired musical separation |

The compact byte layouts are described in [format section 3.2][format]. Their
44-byte compatibility suffix is a retained historical construction, not a fully
explained set of canonical defaults. The original configuration blob is not shipped
as an asset in the inspected research tree. A self-contained compact writer is a
possible route without requiring that blob. The Classic experiment below provides
one successful test starting from empty Genius tables; other models and fuller
behavior still need independent tests.

The updated [controlled hardware comparison][crossgen] reports that both 32-byte
and 168-byte metadata work with the full configuration when cluster labels are
appropriate. Thus 168 bytes is useful for representing every referenced key, but
is not a universal activation requirement. Early simulator results and a stale
comment in `cluster_align.py` incorrectly suggest otherwise.

Mix initialization reportedly targets 10 Tracks with a usability floor of 2;
one continuous-play test observed a 50-Track queue. Track-seeded Playlists use
`default_num_results` and `min_num_results`, observed initially as 25 and 10.
These describe different paths, not a universal 25- or 50-Track Mix length.
The author also observed an unusable two-member Mix with a container-only candidate
pool, so minimum cardinality alone cannot establish playability. See [rounds 4–8][rounds].

## How iOpenPod could produce useful recommendations

The following is a design direction for evaluation, not an accepted architecture.

1. Select the eligible music Tracks that will actually exist in the resulting
   iPod Library. Host-only Tracks must not become unresolvable device candidates.
2. Produce deterministic candidate rankings using available metadata: genre,
   artist relationships, era, and BPM where populated. Choose diversity rules for
   repeated artists and albums. This offers an inspectable first baseline without
   a new dependency or service.
3. Group compatible Tracks into Mixes and assign stable Genius IDs. Encode candidate
   relationships separately from the labels used by the firmware constraints.
4. Optionally investigate richer audio features or an external similarity provider
   after the format works. Existing Acoustic Fingerprints establish recording
   similarity for Sync; they are not established musical-recommendation vectors.
   Synesthesia Track Analysis is currently ephemeral, so durable reuse would need
   its own decision rather than silently turning it into a recommendation cache.
5. Validate every seed's reachable candidates, usable output size, missing IDs,
   exclusions, and diversity before preparing the complete artifact generation.

This would give iOpenPod control over the recommendation policy while the native
firmware keeps control over selection and playback. Musical quality must be judged
separately from whether a Mix appears and plays.

The upstream [alignment implementation][cluster] writes nearly the entire Library
as candidates for every Track. That is reasonable for its small experiments but
quadratic in storage. At 10,000 Tracks, `N * (12 + 8*(N-1))` is 800,040,000 bytes
of raw similarity payloads, before SQLite overhead. A bounded candidate graph
should be investigated; no particular candidate cap is yet established as sufficient
for firmware traversal and constraints. Library-wide eligibility does not require
an all-to-all graph.

## Current iOpenPod integration gaps

ADR-0141 intentionally generates empty Genius tables. ADR-0150 later retains
existing unrepresented Genius metadata, while keeping CDB-derived Track and
container membership authoritative. The current implementation follows those
mechanisms, but retaining Genius records does not guarantee preserving a working
SQLite-only Mix. The broad preservation wording must not be read as that guarantee.

Relevant implementation:

- [Schemas](../../src/iPodDB/SQLiteDB/schema.py) already describe the three tables.
- [Retention](../../src/iPodDB/SQLiteDB/retention.py) leaves existing Genius tables
  intact and retains Genius ID columns for surviving Tracks.
- [Generation](../../src/iPodDB/SQLiteDB/database.py) reconstructs the known
  container and membership tables from checked Library inputs.
- [Validation](../../src/iPodDB/SQLiteDB/validation.py) checks SQLite integrity and
  CDB-derived relationships, but does not decode the Genius graph or verify its
  references. Additional SQLite-only containers are not part of its expected set.

A synthetic replay used two Tracks, Genius IDs 1001 and 1002, one configuration,
two metadata rows, two similarity rows, and an additional kind-32 container with
membership, UI, and seed rows. All five retained databases were supplied to
`build_sqlite_databases` without a corresponding CDB container.

| Observation | SQLite refresh | Refresh after removing the second Track |
| --- | --- | --- |
| Additional kind-32 container | Removed | Removed |
| Its membership, UI, and seed rows | Removed | Removed |
| Library/Dynamic Genius IDs | Both retained | Surviving Track's ID retained |
| Genius config / metadata / similarities row counts | 1 / 2 / 2 | 1 / 2 / 2 |
| Current generation validation | Passed | Passed |

This proves a host-side retention gap for independently authored SQLite containers
and shows that stale Genius records can remain after Track removal. It does not
prove hardware failure for all retained Apple-authored Genius data. The experiment
forced SQLite generation; ordinary no-op preservation is a separate path.

The private reproduction is `.scratch/genius-investigation-2026-10-24/inspect_retention.py`.
Run it from the repository with:

```shell
PYTHONPATH=.:src uv run python .scratch/genius-investigation-2026-10-24/inspect_retention.py
```

Existing SQLite retention and database tests also passed: **41 tests**, using:

```shell
uv run pytest tests/iPodDB/SQLiteDB/test_retention.py tests/iPodDB/SQLiteDB/test_database.py -q
```

## Classic 6.5G physical experiment, 2026-10-24

The user subsequently authorized a minimal native Genius experiment on a connected
120 GB Classic 6.5G. Its captured iTunesDB version is 117, with 624-byte MHIT
headers. It contains 162 Tracks: 112 music, 29 video, and 21 podcast. All MHIT
Genius IDs were initially zero and dataset 9 was absent. Its existing `Extras.itdb`
has the three Genius tables, all empty; there is no separate `Genius.itdb` or
`Library.itdb`. The later hardware probe below established firmware 2.0.1 directly
from the device. Generated SysInfo is not firmware-version evidence.

[OpenGenius's Classic investigation][classic-sync] independently observed the
Genius ID at MHIT +0x1E4 in iTunesDB 117 and Genius rows in `Extras.itdb`.
Its observed +0x1F0 update value triggers Apple's Host synchronization; this is
not evidence that direct device generation needs that value. The shared MHIT
definition now names the eight-byte Genius ID. Synthetic tests cover decoding,
editing only those eight bytes, preserving adjacent data, and short older headers.

Experiment 1 writes only the two database files through Storage:

- Give each music Track a distinct nonzero Genius ID; preserve other Track IDs.
- Add a type-9 dataset with a synthetic 32-byte ASCII CUID. Its necessity is
  unproven; the opaque dataset shape follows existing libgpod support.
- Insert one version-2 config: 25 desired results, 10 minimum, 48-byte no-rule
  config. Insert 112 metadata records, each 32 bytes, and 112 similarity records.
  Every music Track lists the other 111 music Tracks as candidates.
- Preserve the existing SQLite schema, user version, and unrelated table rows;
  recalculate both retained HASH72 and HASH58 signatures.

Host checks verified exact no-op parsing, unchanged semantic Library projection,
the allowed binary edits, both signatures, SQLite integrity, and all candidate
references. A virtual Storage Transaction published and restored the files.
The first physical transaction stopped after publication because macOS changed
the dependent AppleDouble `._iTunesDB` file. All captured contents were restored,
and both recovery journals were cleaned. The retry omitted AppleDouble metadata
from independent input dependencies, verified the two files by readback, completed
its durability barrier and cleanup, and safely ejected the device.

The user reported **"A Genius playlist appears and plays"** in response to the
requested test: highlight the suggested music Track, hold Center, and choose
Start Genius, following the [120 GB Classic user guide][classic-manual]. This is
user-observed firmware acceptance of the generated data for one Track-seeded
Playlist. No prebuilt Playlist was added. Save and reconnect were subsequently
checked below. Other seeds, Refresh, explicit restart, subsequent Sync, and Genius
Mixes have not been verified. The graph deliberately has no musical similarity
policy.

### Saved Playlist readback

The user saved the generated Playlist and reconnected the same Volume. A fresh
read-only Filesystem Session captured the small iTunes and Device files and
rechecked their fingerprints. `iTunesDB` and `Extras.itdb` are byte-for-byte equal
to the deployed experiment. The firmware instead created
`iPod_Control/iTunes/GeniusPlaylist_1.plist`, a 1,620-byte plist with these fields:

| Field | Observed representation |
| --- | --- |
| `version` | Integer 0 |
| `savedIndex` | Integer 1 |
| `name` | Seed Track title |
| `seedTrackPersistentID` | Seed's MHIT `db_track_id`, not its synthetic Genius ID |
| `trackMasterIndexes` | 25 zero-based positions in the original MHIT Track order |
| `trackPersistentIDs` | 25 corresponding MHIT `db_track_id` values |
| `DBTimestampMacOSDate` | Retained integer; epoch and invalidation semantics not established |

Every positional reference agrees with its paired persistent ID. There are 25
distinct music Tracks, the seed is first, and the remaining 24 Genius IDs exactly
match the first 24 entries in that seed's authored candidate list. This confirms
the configured 25-result count for this case and directly connects the saved
native result to the experiment's graph. It does not establish the firmware's
general traversal behavior for other graphs or configurations.

The saved file survived reconnect and is retained in the private `readback-001`
capture with `analysis.json`. An explicit reboot and playback of the saved
Playlist after a later eject have not been observed. A separate one-Track
`OTGPlaylistInfo` also appeared; its relationship to the user's button actions
has not been established and is not treated as the saved Genius Playlist.

There is an integration gap: `is_playback_sidecar()` does not recognize
`GeniusPlaylist_1.plist`, and the current Library projection does not import it.
The saved Playlist is absent from the unchanged iTunesDB Playlist list. Future
product support must investigate capture, import, preservation, and positional
reference handling for these files; this readback adds no such behavior and made
no device writes.

Private captures, prepared files, manifests, scripts, and rollback material are
under `.scratch/genius-classic-2026-10-24/`. The rollback script checks that both
database files still match the deployed experiment before restoring; later device
edits require inspection. No personal database, device identifier, or signing
material is included in this document or committed fixtures.

Validation: 142 iTunesDB tests passed; 9 private nano-capture tests were skipped.
Mypy and the changed Python files' Ruff checks passed.

### Native Mix capability investigation

The user next requested a native Genius Mix on the same Classic. A fresh Storage
hardware probe captured the device's SCSI VPD vendor payload without modifying
device files. Its 12,464-byte XML contains these direct top-level values:

| Hardware field | Observed value |
| --- | --- |
| `VisibleBuildID` | `2.0.1` |
| `BuildID` | `9.0.1` |
| `FireWireVersion` | `1.62` |
| `SupportsGenius` | `true` |
| Config, metadata, and similarities minimum versions | `1` |
| Config, metadata, and similarities maximum versions | `20` |
| `SupportsGeniusMixes` | Key absent |

The original firmware XML has key elements inside arrays, which `plistlib`
rejects. Direct top-level XML pairs were inspected without rewriting the payload.
The generated SysInfo value `1.62` corresponds to the hardware's FireWire revision,
not its user-visible RetailOS version. Capability provenance must preserve this
distinction. An absent Mix key alone is not proof of unsupported playback.

Independent evidence establishes the firmware boundary:

- Apple's [2.0.3 release-notes archive][classic-203-notes], specifically
  `en/Readme.rtf`, labels the release for the Fall 2009 160 GB Classic and lists
  "Support for Genius Mixes".
- The [120 GB guide][classic-manual] describes Track-seeded Genius Playlists;
  the later [160 GB guide][classic-160-manual] explicitly describes the Music >
  Genius Mixes interface.
- The published [2.0.1 firmware string analysis][classic-201-strings] contains
  Genius Playlist handlers but no `GeniusMix` occurrences. The
  [2.0.4 analysis][classic-204-strings] contains `SupportsGeniusMixes`,
  `GeniusMixesTask`, and `TSilverMediaListCntlr_GeniusMixes`. This corroborates the
  version boundary; string absence is not treated as a complete code audit.

Together these findings rule out enabling native Mixes on the connected stock
2.0.1 firmware merely by authoring database rows. A Mix playback experiment needs
compatible firmware on a supported device. Cross-flashing firmware is a separate
device modification, outside this database experiment. No Mix rows were published
and no firmware was changed.

The current files also differ from the earlier saved-Playlist capture, indicating
intervening changes outside this read-only investigation. All 112 nonzero music
Genius IDs remain, and `Extras.itdb` retains one configuration, 112 metadata rows,
and 112 similarity rows. The saved Genius plist is now absent; the iTunesDB
instead contains an Airbag Playlist with the same 25 persistent Track IDs in the
same order in both dataset-2 and dataset-3 representations. This observation does
not identify which software consumed the plist. Its earlier private capture remains
available. Fresh hardware evidence, file captures, comparison results, and the
downloaded Apple release notes are retained under the private `mix-probe/` folder.

## Nano 7G native Mix experiment, 2026-10-24

The user connected a 16 GB nano 7G for the next experiment. A new identity-bound
Storage capture established that it is a different Volume from the Classic. Its
hardware response reports `VisibleBuildID=1.0.4`, `BuildVersion=37A40005`, and
`SQLiteDB=true`. The payload does not advertise Genius capability keys; absence
is not a negative capability declaration. Apple's [nano 7G guide][nano7-manual]
documents native Genius Mix playback.

The captured Library has 20 Tracks: 19 music and one video. All Library and Dynamic
Genius IDs are initially zero, and no kind-32 Mix exists. `Genius.itdb` already
contains one version-2 configuration with a 151,212-byte payload and result
thresholds 25/10, but no metadata or similarity rows. The original configuration
is retained in the private capture; its prior origin has not been established.

Experiment 1 prepares one **iOpenPod Test Mix** on Host copies:

- Give the 19 music Tracks distinct synthetic Genius IDs in `Library.item` and
  `Dynamic.item_stats`; retain the video and all other Track fields.
- Add a kind-32 container with all 19 music Tracks in ordered membership, one
  compatibility seed row, and a corresponding Dynamic UI row. Existing containers
  and their membership remain unchanged. No smart-criteria blob is added.
- Replace the configuration payload with the evidenced 48-byte no-rule variant,
  retaining version 2 and thresholds 25/10. Each music Track gets 32-byte metadata
  and a rotating candidate list containing the other 18 music Tracks.

Checks verified SQLite integrity, schemas and user versions, foreign keys,
unchanged unrelated rows, persistent Track identity against the captured CDB, and
every seed's candidate references. A virtual Storage Transaction published the
prepared files and restored the exact original bytes. This tests structural
consistency and recovery, not firmware playback or recommendation quality.

The physical Storage Transaction replaced only `Genius.itdb`, `Dynamic.itdb`, and
`Library.itdb` inside `iPod_Control/iTunes/iTunes Library.itlp/`. Fresh fingerprints
bound the original files and unchanged dependencies; active SQLite journals were
absent and all referenced media paths existed. Readback matched all three prepared
files, durability and recovery cleanup completed, and macOS confirmed safe eject.
The user answered **"The Mix appears and plays"** when asked to disconnect, open
Music > Genius Mixes, and play **iOpenPod Test Mix**. This confirms user-observed
native Mix visibility and initial playback on this nano 7G with the prepared
data. It does not establish which seed was selected, the resulting queue length,
playback of every candidate, continuous queue replenishment, restart persistence,
or behavior after reconnect and Sync. No post-playback readback has yet occurred.
The observation is retained in `experiment-1/hardware-observation.json` alongside
the exact prepared artifact hashes and deployment record.

This is deliberately a SQLite-only firmware experiment. The existing iTunesCDB,
Locations database and its Checksum Book, Extras database, artwork, and media were
not rewritten. It is not an implementation of the application Sync contract;
the additional Mix is absent from CDB and can be removed by a later Sync. Host
originals, hardware evidence, preparation checks, and the deployment record are
retained under `.scratch/genius-nano7-2026-10-24/`. No personal capture is committed.

## Decisions and experiments needed before product support

The investigations above establish format inspection, preservation gaps, and a
first offline generator over captured Host copies, with successful physical
Classic Track-seeded Playlist and nano 7G Mix cases. The private experiments are
not a product generation workflow.

An ADR would need to extend ADR-0141/0150 to define ownership of authored Genius
state and its relationship to iTunesCDB. Candidates include a typed native Library
extension or a separate typed, application-owned generation input. Neither is
selected here. Ad hoc SQLite edits would be erased by the present projection rules.

Boundary responsibilities remain:

- **Application Layer:** recommendation policy, eligibility, generation intent,
  review, and invalidation after additions, removals, or media replacement.
- **iPodDB:** typed config/metadata/similarity representations, identity mapping,
  variant-aware encoding, structural validation, and cross-artifact relationships.
- **Device Registry:** evidence-backed Genius capabilities by model and firmware;
  [ADR-0175](../adr/0175-model-native-genius-capabilities-by-firmware.md) now defines
  the [native feature matrix](../genius-capabilities.md). Existing SQLite support
  alone must not imply tested Genius support or application workflow readiness.
- **Storage:** publication through the bound Filesystem Session and existing staged,
  verified, recoverable Storage Transaction. Publish the coherent Library artifact
  generation and required signatures. Safety cannot depend on optional Backup Snapshots.

Before enabling generation, experiments should establish:

- A complete initially empty Genius database can be authored without relying on
  previous iTunes-generated IDs, containers, smart criteria, or factory assets.
- Every offered Mix seed works; the reported sampler does not always recover from
  an invalid first seed. Test sparse graphs, overlapping seeds, short Libraries,
  malformed records, and impossible result thresholds.
- Generated and retained Mixes survive metadata edits and subsequent Sync; deleting
  or replacing Tracks updates the graph and preserves unrelated Unknown Data.
- The nano 5G schema without `item_stats.genius_id` remains intact. Where the column
  exists, establish its exact role and keep related IDs coherent. Upstream lists
  this role as an open measurement, and `custom_graph.py` does not update the column.
- Configured spacing and recent-skip rules behave as intended. Use iOpenPod's
  established time conversion contract: the referenced SQLite epoch is Core Data
  2001, distinct from the 1904 Mac epoch used elsewhere.
- Native Mix playback, Track-seeded Playlist creation, reboot/reconnect, repeated
  Sync, and musical quality are tested independently on each targeted firmware.

The simulator is useful for diagnostics but uses Python randomness and explicitly
disagrees with hardware on some metadata/config combinations. It is not an oracle.
Observed success with 17 containers and up to 189 members does not prove unlimited
capacity. The upstream evidence covers nano 5G/6G; the local Classic 6.5G result
covers one Track-seeded Playlist and the nano 7G result covers one Mix's initial
playback. Nano 4G, other Classics, and Classic Mix support require separate
investigation. An ordinary generated Playlist remains a separate potential fallback
on other models, without claiming native Genius activation.

Upstream code and documentation carry an [MIT license][license]. Any reused code
must retain its attribution. This investigation adds no dependency, vendors no
upstream code or firmware blob, and does not accept an implementation design.

[format]: https://github.com/dotm5/Genius-Mix-Research/blob/57b7ae865a10177f725c90e946e1199c00411e53/docs/FORMAT.md
[crossgen]: https://github.com/dotm5/Genius-Mix-Research/blob/57b7ae865a10177f725c90e946e1199c00411e53/docs/CROSSGEN.md
[align]: https://github.com/dotm5/Genius-Mix-Research/blob/57b7ae865a10177f725c90e946e1199c00411e53/docs/ALIGN.md
[rounds]: https://github.com/dotm5/Genius-Mix-Research/blob/57b7ae865a10177f725c90e946e1199c00411e53/docs/ROUNDS.md
[cluster]: https://github.com/dotm5/Genius-Mix-Research/blob/57b7ae865a10177f725c90e946e1199c00411e53/tools/cluster_align.py
[custom]: https://github.com/dotm5/Genius-Mix-Research/blob/57b7ae865a10177f725c90e946e1199c00411e53/tools/custom_graph.py
[license]: https://github.com/dotm5/Genius-Mix-Research/blob/57b7ae865a10177f725c90e946e1199c00411e53/LICENSE
[classic-sync]: https://github.com/mizoyuzu/opengenius/blob/2f28520e7f8f769030709563420c8b961a9b35a2/docs/research/2026-10-06-ipod-genius-sync.md
[classic-manual]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma630_ipod_classic_120gb_en.pdf
[classic-160-manual]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma1195_ipod_classic_160gb_user_guide.pdf
[classic-203-notes]: https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-7155.20090925.Ju879/iPodDocumentation_35.2.0.3.ipd
[classic-201-strings]: https://github.com/giek2000/ipod-classic-firmware-research/blob/2b916dc452f869d59b1819e5c2b0b06a172eddb2/specs/iPod_Classic_6_5G_Rev_A_33_2_0_1.md
[classic-204-strings]: https://github.com/giek2000/ipod-classic-firmware-research/blob/2b916dc452f869d59b1819e5c2b0b06a172eddb2/specs/iPod_Classic_7G_35_2_0_4.md
[nano7-manual]: https://cdsassets.apple.com/live/6GJYWVAV/user/locale/en-gb/ma1624_ipod_nano_2015_user_guide.pdf
