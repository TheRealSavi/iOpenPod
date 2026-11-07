# iPod mini 2: Finder and iOpenPod capture comparison

Date: 2026-10-22. Investigation only; no application behavior, supplied capture,
or connected iPod was changed.

## Finding

**The supplied captures do not reproduce the reported failure. Both the Apple
and v2 two-album Syncs show and play their songs on the owner's mini 2**, as the
owner confirmed during this investigation.

Apple itself writes Track MHOD types **22, 23, 29, and 30** in this working
capture. These are Album Artist, Sort Artist, Sort Album Artist, and Sort Composer.
Consequently, the claim that Apple restricts this model to Track MHODs 1–6 and 12
is contradicted by the supplied evidence. The working v2 capture additionally
contains empty Track MHODs 19/20, nonempty Track MHOD 37, and Playlist MHOD 53.
Their presence alone is also insufficient to cause the failure on this iPod.

No failing MHOD type has been isolated. The reporter's trimming result remains
useful evidence, but deleting many types simultaneously does not distinguish
type support, a particular malformed or oversized payload, aggregate memory
pressure, repaired counts/lengths, or a different successful write/read cycle.
It does not justify broad MHOD deletion. Nor do these Host copies establish
that the reporter's CompactFlash storage is failing.

## Evidence and method

Inputs are the three directories under
`C:\Users\JohnG\Desktop\mini 2 tests`:

- `fresh apple`: empty, newly recovered baseline.
- `apple`: Apple/Finder two-album Sync, confirmed working.
- `v2`: iOpenPod two-album Sync, confirmed working and retained as the baseline
  for any subsequent experiments.

Source inspection used commit
`dc6d6c4b28ddfb9f4b90413f0f18d7e4b5aaa707`, local branch `main`, project version
2.0.14. The directory label `v2` does not independently prove which exact build
produced its bytes. The reporter's `v2.0.13` source was separately checked at
`c7d62659409bb152c20e1755325704cfcfc68def`. Original iOpenPod was inspected at
`origin/1.x`, commit `a20242428b93b672d14b37230772dbad75139c69`.

The comparison used the production, definition-driven iTunesDB parser and writer;
matched Tracks by album, title, disc number and Track number; compared MHODs by
parent context and type; and matched Playlist entries by their resolved Tracks.
Numeric IDs, physical record positions, and shifted file offsets were not used
as cross-capture Track identity. An independent check verified string framing,
Playlist references, and browse-index permutations. The companion audit hashed
every captured regular file and inspected MP4 atoms and encoded audio payloads.

All three iTunesDB files parse and serialize unchanged to **exactly their original
bytes**. This tests parser/writer fidelity and structure, not firmware acceptance.
The firmware evidence is the owner's separate playback confirmation. No failing
firmware loop or original/repaired 1,452-Track pair was available; this report
therefore completes the requested differential investigation without claiming a
root-cause diagnosis or implementing a speculative fix.

### Capture fingerprints

| Capture | iTunesDB bytes | SHA-256 |
| --- | ---: | --- |
| Fresh Apple | 8,190 | `3f8a721ccae881d25f95f4f37799b96dafc062a076df4bd8a9afc3bc5f916c5e` |
| Apple | 38,960 | `4b2040b66d4eadcc16bc78844175d3d9ae1343ca66a2dff8b458d6e514455f25` |
| v2 | 36,296 | `94b6f6d95cb6f971ef0994d66da5cf84447225ac47d68a4d16f757d561b3396f` |

| Measure | Fresh Apple | Apple | v2 |
| --- | ---: | ---: | ---: |
| Captured regular files | 9 | 28 | 41 |
| Captured bytes, all files | 20,987,394 | 552,634,101 | 552,159,216 |
| Tracks / Music files | 0 | 19 | 19 |
| Albums | 0 | 2 | 2 |
| MHSD datasets | 5 | 5 | 5 |
| MHYP Playlist records | 4 | 4 | 4 |
| MHIP Playlist entries | 0 | 38 | 38 |
| All MHOD records | 30 | 265 | 323 |
| Track MHOD records | 0 | 191 | 239 |

## Track MHOD compatibility

Counts below are restricted to MHODs whose parent is MHIT. They must not be
confused with Playlist index or album-name MHODs.

| Type | Meaning | Apple count | v2 count | Comparison |
| ---: | --- | ---: | ---: | --- |
| 1 | Title | 19 | 19 | Byte-identical for each matched Track |
| 2 | Location | 19 | 19 | Different valid file paths; same string framing |
| 3 | Album | 19 | 19 | Byte-identical |
| 4 | Artist | 19 | 19 | Byte-identical |
| 5 | Genre | 19 | 19 | Byte-identical |
| 6 | Filetype | 19 | 19 | Byte-identical |
| 12 | Composer | 10 | 10 | Byte-identical |
| 19 | Show | 0 | 19 | Empty in every v2 Track; 40 bytes each |
| 20 | Episode | 0 | 19 | Empty in every v2 Track; 40 bytes each |
| 22 | Album Artist | 19 | 19 | Byte-identical, nonempty |
| 23 | Sort Artist | 19 | 19 | Byte-identical, nonempty |
| 29 | Sort Album Artist | 19 | 19 | Byte-identical, nonempty |
| 30 | Sort Composer | 10 | 10 | Byte-identical, nonempty |
| 37 | Content Provider | 0 | 10 | `Maverick`; 56 bytes each |

All captured Track MHODs use a 24-byte common header. Its unknown words at
`+0x10/+0x14` are zero in both writers. Every string uses the same 16-byte prefix:
encoding indicator 1, exact UTF-16LE byte length, word `+0x20 = 1`, and
word `+0x24 = 0`. Declared string and Chunk lengths match the actual bytes.
There is no observed common-string encoding defect.

Order differs. Apple's ten Tracks with composers use
`1,4,22,12,3,5,6,2,23,29,30`; its other nine use
`1,4,22,3,5,6,2,23,29`. v2 starts with
`1,4,3,5,19,20,22,2`, adds the applicable composer/sort/provider records, and
puts type 6 last. The successful v2 control demonstrates that this concrete
ordering is accepted here.

These captures do **not** test Track MHODs 7–11, 13–18, 21, 24–28, 31–36,
or other unlisted types. In particular, they contain neither lyrics MHOD 10
nor chapter-data MHOD 17. They do not establish acceptance of nonempty Show or
Episode strings, arbitrary Unicode, very long text, large chapter structures,
or other values absent from this sample. An observed MHOD may also be ignored
by firmware: successful library loading is not proof that every associated
feature is rendered or used.

### Exact size accounting

v2 adds 48 Track MHODs: 38 empty Show/Episode records and ten provider records.
They occupy **2,080 additional bytes**. Its shorter Track headers save
**5,624 bytes**: 19 × (624 − 328). It adds **880 bytes** of Playlist MHOD 53.
Other dataset lengths cancel, giving:

```text
38,960 − 5,624 + 2,080 + 880 = 36,296 bytes
```

Thus v2 has more MHOD records but a database **2,664 bytes smaller** than Apple.
This refutes an assumption that these extra records necessarily make this
particular database larger. It does not measure firmware memory use or exclude
a content/size limit in the reporter's approximately 4.2 MB database.

## Database headers and datasets

All three files have a 244-byte MHBD, root version **117 (`0x75`)**, platform 2,
five datasets, timezone offset −14,400, and hashing scheme 0. All are ordinary
logical iTunesDB files. The Mini Device Profile's `0x13` value is an authoring
baseline, **not the observed root version in these captures**.

Apple changes MHBD words `+0x50/+0x54` to **1/31**; fresh Apple and v2 contain
**0/0**. The reporter quoted 1/5 from another database. These words therefore
must not be replaced with assumed universal Finder constants. Database IDs at
`+0x18/+0x48` also differ between the synced captures. Apart from total length,
these are the parsed root-header differences between Apple and v2.

All captures retain dataset order `4,1,3,2,5`:

| Dataset | Purpose in this capture | Fresh bytes | Apple bytes | v2 bytes |
| ---: | --- | ---: | ---: | ---: |
| 4 | Album list | 188 | 710 | 710 |
| 1 | Track list | 188 | 24,812 | 21,268 |
| 3 | Master Playlist representation | 1,944 | 4,756 | 5,196 |
| 2 | Master Playlist representation | 1,944 | 4,756 | 5,196 |
| 5 | Two retained Playlist records | 3,682 | 3,682 | 3,682 |

Both synced album lists contain two MHIA records and two each of MHOD
200/201/202. Album text matches; album IDs and SQL IDs differ, and
`album_track_db_id` is zero in Apple versus the allocated album value in v2.
Track album references resolve inside their respective captures.

## Track headers beyond MHODs

Every Apple MHIT is **624 bytes** and every v2 MHIT is **328 bytes**. Both load
and play in these controls. The current authoring choice follows
[ADR-0144](../adr/0144-expand-track-headers-with-device-capabilities.md) and
[ADR-0145](../adr/0145-select-track-layouts-for-all-library-writes.md), which
explicitly distinguish authoring layouts from proven firmware maximums.

The following groups account for the observed defined-field differences within
the shared header extent. Offsets are relative to MHIT; exact per-Track values
are retained in the local CSV evidence.

| Fields / offsets | Apple versus v2 | Interpretation and limit |
| --- | --- | --- |
| Child count `0x0C` | 9/11 versus 12/13/14 | Correct counts for each Track's MHODs |
| Track ID `0x10`; persistent IDs `0x70,0xA8`; album ID `0x120` | Different allocations | References must be compared semantically |
| Modified/added dates `0x20,0x68` | Different dates | Different preparation histories |
| File sizes `0x24,0x12C` | Different for all 19 | Media containers differ; encoded audio matches |
| Duration `0x28` | Six v2 values are 1 ms larger | Precision/rounding difference; same encoded audio |
| Bitrate `0x38` | Apple 1411; v2 varies | Different ALAC bitrate representation |
| Sound Check `0x4C` | Different for all 19 | Loudness metadata difference |
| Artwork size `0x80` | Apple 16,332 or 37,655; v2 307,200 | Different artwork representations |
| Release date `0x8C` | v2 is 43,200 seconds earlier | Exact 12-hour date difference; no cause assigned |
| MPEG audio type `0x90` | 60 versus 0 | Writer metadata difference |
| Purchased AAC flag `0x93` | 1 versus 0 | Native field differs despite ALAC content |
| Genius category `0x98` | One Track: 1 versus 0 | Isolated native metadata difference |
| Last skipped `0xA0` | One Apple Track has a date; v2 zero | Captures have different history |
| Artwork presence `0xA4` | 2 versus 1 | v2 has application artwork |
| Sample count `0xBC`; encoder `0xCC`; gapless Track flag `0x100` | Apple populated / 1 / 1; v2 0 / 0 / 0 | Gapless metadata differs; seamless transitions were not tested |
| Database reference `0x124` | Apple nonzero; v2 zero | Native relationship differs |
| Sort indicators `0x134` | `8080030303800000` or `8080030380800000`; v2 `0000010101000000` or `0000010100000000` | Different flags despite identical sort text |

The extended region from byte 328 onward exists only in Apple. Its nonzero and
unknown bytes remain evidence; missing fields in a short header are not parsed
as proof that firmware requires zero. In particular, Apple has later artist and
composer references and extended flags that v2's layout cannot hold. The field
beginning at `0x13C` is only partially present in the 328-byte header; the audit
records that physical distinction rather than treating its default value as
captured data. Its first twelve bytes are present and zero in both captures.
No nonzero header bytes fall outside the shared definitions' field coverage;
named unknown fields still have unknown meanings. Complete header-byte
differences are retained separately.

These are real compatibility and feature-quality dimensions. Successful library
loading/playback here does not certify Sound Check, gapless playback, date
presentation, every sort operation, or every firmware feature.

## Playlists, browse indexes, and ordering

The fresh snapshot already contains fourteen Playlist MHOD 52 records. Each
synced capture retains seven in each Master Playlist: sort types
`3,4,5,7,18,35,36`. Every populated type-52 payload is a valid permutation of
the nineteen physical Track indexes.

v2 additionally writes five MHOD 53 jump tables per Master Playlist, for sort
types `3,4,5,7,18`; Apple writes none. Their groups are contiguous and cover the
corresponding indexes. Types 35/36 have no added type-53 partner. The working v2
capture demonstrates that these ten concrete type-53 records do not prevent
library loading here. They are **Playlist MHODs**, not Track MHODs.

Physical Track order differs. After resolving indexes back to matched Tracks,
type-52 order is identical for sorts 3,4,5,7,35,36. **Composer sort 18 differs:
Apple places Tracks without a composer last; v2 places them first.** This is an
observed browse-order difference, not an explanation for zero songs.

Both Master Playlists contain all nineteen Tracks. All 38 MHIP Track references
and persistent references resolve correctly. Their native group IDs, timestamps,
entry IDs and MHOD 100 position values differ: Apple uses its allocated position
values; v2 uses sequential positions. Playlist IDs/timestamps differ too. These
identity/position changes must not be interpreted as missing Tracks.

The common Playlist title, opaque type-100 settings, type-102 settings, and
retained Smart Playlist types 50/51 have matching payloads. No wholesale loss
of inherited Playlist settings was observed.

## Media and companion files

All nineteen media files are ALAC in M4A containers. They match one-to-one by
the SHA-256 of their entire `mdat` payloads; every matched ALAC sample entry is
also byte-identical. All whole-file hashes differ because their containers and
tags differ. The v2 media have only encoder tag `©too = Lavf63.6.100` in their
`ilst` metadata, whereas Apple retains embedded tags and covers. v2 media total
**1,381,011 fewer bytes**. File names and distribution across F00–F05 differ.
This comparison does not exercise AAC or MP3 from the reporter's mixed Library.

A further cross-check follows each matched Track's actual MHOD 2 path: all
nineteen paths per capture resolve to distinct existing files, both MHIT size
fields match each file's byte size, and each semantic Track pair references
matching encoded audio and ALAC sample entries. The result is not merely an
unordered match of the two media directories.

`iTunesControl` is exactly 20,971,520 bytes and byte-identical in all three
captures. The sample Contacts and Notes instructions are also unchanged.

### Device metadata and preferences

Fresh/Apple SysInfo identifies model **M9802**, board **iPod Q22B**, build
`0x02618000 (2.6.1)`, and visible build `0x01418000 (1.4.1)`. Identity values
agree across captures. The catalog's original capacity is not a measurement of
installed storage, and these files do not describe the reporter's 128 GB CF card.

v2 changes SysInfo `visibleBuildID` to **1.62**, while its new SysInfoExtended
contains `VisibleBuildID = 1.4.1` and `FireWireVersion = 1.62`. The source trace
finds that `device_registry/metadata.py` prefers FireWireVersion as firmware
evidence, and `authority.py` writes that observation to visibleBuildID. This is
a separate, concrete conflation of differently named metadata fields worth
correcting in its own scoped change.

v2 also retains `updaterFamily = 0x00000006` and adds `UpdaterFamilyID = 7`.
The source reads the latter spelling and preserves the former. The differing
names and values are observed; their firmware equivalence is not established.
Neither metadata discrepancy is a demonstrated cause of zero songs: v2 works.

`Device/Preferences` is 2,876 bytes in all captures. Its only changed byte is
`0xB00`: fresh/Apple `01`, v2 `00`. This offset is not modeled by the current
typed definitions; it remains Unknown Data.

Binary iTunesPrefs is 1,232 bytes in all captures:

| Offset | Fresh Apple | Apple | v2 |
| --- | --- | --- | --- |
| `0x0A`, music Sync mode | 0, manual | 1, automatic | 0, manual |
| `0x0B`, music selection | 1, all | 2, selected | 1, all |
| `0x9C`, unmodeled | 0 | 1 | 0 |
| `0x2C0`, captured username text | Empty | Empty | Populated |
| `0x300`, captured computer-name text | Empty | Empty | Populated |

Each plist's embedded `iPodPrefs` is byte-identical to its binary iTunesPrefs.
All have `DevicesVersion = 1.6.4`. Apple selects two MusicAlbumIDs; fresh/v2
selection arrays are empty. These are desktop Sync settings, not the nineteen
Track records in iTunesDB. Actual Host names and device serials are omitted here.

### Files added only by v2

| Relative path | Bytes |
| --- | ---: |
| `.directory` | 82 |
| `.VolumeIcon.icns` | 287,131 |
| `.xdg-volume-info` | 82 |
| `autorun.inf` | 152 |
| `iPod_Control/Artwork/ArtworkDB` | 9,104 |
| `iPod_Control/Artwork/F1060_1.ithmb` | 409,600 |
| `iPod_Control/Device/iOpenPodSysInfoAuthority` | 2,337 |
| `iPod_Control/Device/SysInfoExtended` | 3,125 |
| `iPod_Control/iOpenPod/library-sync-helper.json` | 99,557 |
| `iPod_Control/iOpenPod/volume-icon.ico` | 44,278 |
| `iPod_Control/iOpenPod/volume-icon.png` | 53,176 |
| `iPod_Control/iOpenPod/Podcasts/listening-history-v1.json` | 86 |
| `iPod_Control/iOpenPod/Podcasts/subscriptions-v1.json` | 88 |

The ArtworkDB/F1060 files follow
[ADR-0118](../adr/0118-write-application-artwork-for-non-cover-devices.md):
application-only artwork for iOpenPod browsing. The iTHMB contains space for two
320×320 RGB565 images. Its presence does not imply native mini artwork display.

## Writer findings and compatibility policy

The current Mini Device Profile selects database baseline `0x13`, a 328-byte
new MHIT, no checksum, no SQLite/CDB, and a configured 32 MiB database write
limit. That last policy is not a measured universal firmware acceptance limit.

`iPodDB/library/_field_policy.py` and `_track_writing.py` author top-level text
fields on every new Track, including empty Show, Episode and Album Artist.
Other supported metadata and chapters are authored when supplied. There is no
per-model MHOD allowlist. A software probe through public Library preparation,
serialization and reparse confirmed this behavior; changing baseline `0x13`
to `0x30` changes MHIT size without changing that MHOD selection.

The relevant policy is also present in v2.0.13. Original iOpenPod similarly
had no model gate for Track MHOD types, but omitted empty optional strings and
applied per-string 4,096/8,192-byte caps. Current 2.x does not apply those caps.
That makes unusually long metadata an inspection target if present in the
reporter's file; it is not evidence that silent truncation is a valid fix.

The Master Playlist writer in `_hidden_writing.py` creates the observed 52/53
pairs. The additional records are explained by source behavior, not accidental
unrecognized bytes. The root version is retained at least as high as the source
version, explaining `0x75` alongside a `0x13` authoring baseline.

No new compatibility restriction or ADR is warranted from these successful
controls. Any eventual change must preserve unrelated metadata and Unknown Data,
follow the shared Chunk definitions, and have a regression at the actual failing
seam. Discarding every type outside 1–6/12 would remove metadata Apple itself
writes and would conceal the original trigger.

## How to isolate the reporter's failure

The next decisive input is the reporter's **exact failing iTunesDB, exact repaired
working iTunesDB, and the trimming script/command**. Capture them before another
Sync overwrites the evidence. Also record actual firmware shown on the iPod,
not merely the reconciled SysInfo label; the app build; and post-eject song count
and playback result for each candidate.

The investigation should proceed in this order:

1. **Diff the actual repair.** Check every changed header, extent, count, trailing
   byte and MHOD, not just the intended deletion list. Determine whether the
   script also repaired malformed framing or rewrote unrelated values.
2. **Inventory what the working controls do not cover.** Rank absent MHOD types,
   large/odd strings, chapters, duplicate records and exceptional Track payloads
   before retesting ordinary 22/23/29/30 records already present in Apple's
   working output. Measure per-type and maximum per-record byte sizes.
3. **Reproduce the endpoint with fixed bytes.** A parser succeeding or Finder
   listing titles is not the failing signal. Use the same device, safe ejection,
   a fresh firmware library load, song count and representative playback. Keep
   the original failing bytes immutable and distinguish candidate construction
   from publication through Storage.
4. **Narrow one dimension at a time.** Construct minimal, structurally valid
   candidates from the failing original. Bisect the implicated type/payload set
   while keeping Tracks, media and unrelated metadata fixed. After identifying
   a sufficient change, reintroduce the precise original record/value to make
   failure return. If deleting a type helps, separately test its payload content
   and size; deletion alone still does not establish a universal type ban.
5. **Separate a format effect from storage.** Verify hashes after publication
   and reconnect, and repeat the same failing/working pair. Stable bytes with
   repeatable opposite outcomes favor a content/format cause. Readback mismatch,
   I/O failures, or inconsistent outcomes make storage/durability a stronger
   candidate. These observations would still need interpretation; this report
   has performed no physical storage-health test.

Candidate explanations remain unproven. A particular unrepresented MHOD/payload
or a repair-script side effect is the first useful differential target, given
the reporter's claimed before/after. A Library-size or metadata-size effect and
firmware variation remain possible. Intermittent CF/filesystem failure also
remains possible. No evidence here ranks failing hardware above a content bug,
and the two-album success cannot exonerate every 1,452-Track workload.

## Local reproducibility and detailed evidence

Private, uncommitted evidence is retained in
`.scratch/mini2-investigation/`. It includes music titles and original metadata;
the full source captures and identifiers are not added to the repository.

| Artifact | Coverage |
| --- | --- |
| `compare_databases.py` | Reproducible production-parser comparison and byte-exact round-trip assertions |
| `database-summary.json` | Counts, lengths, fingerprints, type sequences and field-difference counts |
| `database-evidence.json` | All parsed Chunk headers, prefixes, payloads, raw headers/bodies, trailers and source offsets for all three databases |
| `semantic-chunk-differences.json` | Complete Apple/v2 matched Chunk differences and added/removed Chunks |
| `mhod-inventory.csv` | Every MHOD, parent, offset, type, length, prefix, payload and hash |
| `matched-track-header-differences.csv` | Every defined changed MHBD/MHIT field, including physical absence/partial presence |
| `matched-track-header-byte-differences.csv` | Every changed matched MHIT header byte, including unmodeled regions |
| `matched-track-text-differences.csv` | Every changed, missing or added Track string |
| `matched-container-header-differences.csv` | Semantically matched album, Playlist and entry header changes |
| `snapshot_audit.py`, `snapshot-audit.json`, `snapshot-audit.md` | All-file inventories/hashes, companion comparison, MP4 and audio comparison |
| `track_media_crosscheck.py`, `track-media-crosscheck.json` | Actual database paths, file sizes, and semantic Track-to-audio correspondence |
| `independent_checks.py`, `independent-checks.json`, `independent-review.md` | Separate framing, reference, index and semantic-order checks |
| `writer_probe.py`, `writer-findings.md` | Public authoring probe, version comparison and exact source references |

Run from the repository root with the supplied captures still at the recorded
Host path:

```powershell
uv run python .scratch/mini2-investigation/compare_databases.py
uv run python .scratch/mini2-investigation/snapshot_audit.py
uv run python .scratch/mini2-investigation/track_media_crosscheck.py
uv run python .scratch/mini2-investigation/independent_checks.py
uv run python -c "import runpy; runpy.run_path('.scratch/mini2-investigation/writer_probe.py')"
```

These checks read the captures and write local evidence only. They do not test
an emulator or publish a candidate to the connected iPod. Source inspection and
the successful-control comparison are complete; precise attribution of the
reporter's zero-song failure remains dependent on the missing failing evidence.
