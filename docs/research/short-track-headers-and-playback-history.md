# Short Track headers and playback history in Original iOpenPod

## Scope and confidence

**2026-10-26 correction:** the historical source descriptions below retain the
labels used by the pinned revisions. Direct Classic 2.0.1 analysis identifies
MHIT `+0x98` as total skips, fitting exactly within 156 bytes, and `+0x9c` as an
independent secondary counter. A 158-byte header ends inside the secondary
counter. Last-skipped and played-state boundaries are unchanged. The current
implementation adopts that correction in
[ADR-0195](../adr/0195-adopt-firmware-database-field-semantics.md).

Investigated on 2026-10-14 in response to
[PR #249](https://github.com/TheRealSavi/iOpenPod/pull/249). The question is whether
Original iOpenPod handled playback evidence whose fields do not fit a retained
156-byte MHIT header, and whether it preserved that evidence after consumption.

The Original iOpenPod source examined is `origin/1.x`, commit
[`a20242428b93b672d14b37230772dbad75139c69`](https://github.com/TheRealSavi/iOpenPod/tree/a20242428b93b672d14b37230772dbad75139c69).
The PR comparison is pinned to
[`a8e4be82d394161550352e7f8d0e13e1987cd27c`](https://github.com/TheRealSavi/iOpenPod/tree/a8e4be82d394161550352e7f8d0e13e1987cd27c).
This is source evidence about those revisions, not evidence that a physical nano
6G accepts any particular rewritten header. Repository context included
`CONTEXT.md`, `GLOSSARY.md`, `docs/source_architecture.md`, ADR-0006, ADR-0085, and
ADR-0100. No device files were changed.

## Findings

### 1.x understood short headers and omitted fields outside the output header

The shared MHIT definitions identify the same boundaries at issue in PR #249:

| Field | Offset | Minimum header length |
| --- | --- | --- |
| Main play count | `0x50` | Within the 156-byte core |
| Pending-scrobble play count | `0x54` | Within the 156-byte core |
| Last played | `0x58` | Within the 156-byte core |
| Skip count | `0x9C` | `0xA0` / 160 bytes |
| Last skipped | `0xA0` | `0xA4` / 164 bytes |
| `not_played_flag` | `0xB2` | `0xB3` / 179 bytes |

[Original MHIT definitions](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/mhit_defs.py#L78-L127)

`write_fields()` skips a field when its minimum header length exceeds the chosen
output header. It does not reject a nonzero value merely because that value cannot
be written. `write_mhit()` explicitly relies on this behavior. Consequently, a
156-byte output MHIT omits skip count, last skipped, and the separate played flag.
This is direct implementation evidence, not an inferred firmware rule.
[Field writer](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/field_base.py#L394-L431),
[Track writer](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhit_writer.py#L423-L426)

### It rebuilt headers from the database version, rather than retaining each size

The Original writer chooses these header lengths:

| Selected database version | Output MHIT header length |
| --- | --- |
| At most `0x12` | 156 bytes |
| `0x13` through `0x19` | 328 bytes |
| `0x1A` through `0x2D` | 504 bytes |
| Above `0x2D` | 624 bytes |

When resolved device capabilities provide a database version, the writer chooses
the higher of that version and the reference database version. Otherwise it uses
the reference version or its default. It passes that database-wide version to
every Track writer. Although the persistence path extracts the first reference
MHIT header size into `reference_info`, this is not the size argument used by
`write_mhit()`.
[Version-to-size mapping](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/mhit_defs.py#L28-L44),
[Database version selection](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhbd_writer.py#L367-L384),
[Reference header observation](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhbd_writer.py#L1070-L1088)

The nano 6G capability entry supplies database version `0x30`. Therefore, with
that resolved profile, the source path reconstructs 624-byte MHIT headers, even
if incoming Tracks used 156-byte headers. That output has room for skip history.
This conclusion follows from the writer and capability table; it does not prove
that expanding the reported device's headers is safe for its firmware or Unknown
Data.
[Nano 6G capabilities](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/device/capabilities.py#L473-L496)

### Playback evidence was merged before output size was considered

The binary `Play Counts` parser reads skip count when each record has at least
24 bytes and last skipped when it has at least 28. The merge accumulates play and
skip totals and accepts newer timestamps without checking the Track's original
header length. Conversion then carries those values into `TrackInfo`.
[Sidecar reader](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_parser/playcounts.py#L144-L179),
[Playback merge](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_parser/playcounts.py#L224-L270),
[Track conversion](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/_track_conversion.py#L81-L112)

Thus there are two different outcomes in 1.x: an expanded output header can store
the merged skip evidence, while an output that remains 156 bytes silently omits
it. The omission is a generic writer behavior, not a nano-specific playback
policy. For SQLite-capable devices, the database workflow also passes the same
Tracks to the SQLite writer, whose `Dynamic.itdb` rows contain skip count and last
skipped independently of MHIT size.
[SQLite publication path](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/_db_io.py#L387-L452),
[Dynamic statistics writer](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sqlitedb_writer/dynamic_writer.py#L81-L108)

The separate played flag has a limitation. `_resolve_not_played()` derives it from
play count only when `played_mark` is negative. Reading an absent extended field
returns its default zero; Track conversion passes that zero through, so the
fallback is not automatically used for every parsed short-header Track. The
SQLite `has_been_played` column is directly derived from positive play count.
[Read defaults](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/field_base.py#L178-L185),
[Missing-field read](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/field_base.py#L294-L303),
[Played-flag conversion](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/_track_conversion.py#L137-L142),
[Played-flag resolution](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhit_writer.py#L352-L358)

### Loading could continue when automatic persistence failed

On load, 1.x tries to commit pending Play Counts. If that raises a write-safety
error or another exception, it logs the failure and continues loading with the
pending evidence merged in memory. Successful auto-commit disables that second
merge. This supplied another way to avoid making an unsuccessful history save
look like a completely unreadable Library.
[Runtime loading](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/application/runtime.py#L1842-L1861)

### The auto-commit path deleted consumed sidecars without archiving them

After a successful database commit, `_commit_playcounts_guarded()` calls
`delete_playcounts_files()`. That function durably removes `Play Counts`,
`iTunesStats`, `PlayCounts.plist`, and the base `OTGPlaylistInfo`. This path does
not create an inactive sidecar archive for evidence omitted from its database
outputs; the SQLite statistics described above are a separate output path.
The database writer's `.backup` copies contain the previous databases; they do
not capture newly pending Play Counts evidence that was omitted during writing.
This finding concerns the automatic consumption path, not any separately
requested Backup Snapshot.
[Commit and cleanup](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/_db_io.py#L518-L580),
[Sidecar deletion](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/_db_io.py#L467-L494),
[Database backup](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhbd_writer.py#L1498-L1517)

## Authored experiment

The investigation executed the unmodified 1.x Python source from a temporary
`git archive` using the repository's UV runner. No physical iPod was accessed.
For a `TrackInfo` containing three plays, two skips, and last skipped Unix time
`1717155300`, the direct writer and reader produced:

| Requested database version | Header bytes | Skip count read back | Last skipped read back |
| --- | --- | --- | --- |
| `0x12` | 156 | 0; field absent | 0; field absent |
| `0x19` | 328 | 2 | `1717155300` |
| `0x2D` | 504 | 2 | `1717155300` |
| `0x30` | 624 | 2 | `1717155300` |

A second experiment parsed an authored 156-byte Track, merged three plays and
two skips with a fixed-zero-offset Device Time Context, converted the result
through `track_dict_to_info()`, and called `write_mhbd()` with the actual nano 6G
capabilities and reference version `0x12` / header size 156. Output contained a
624-byte MHIT with three plays, two skips, and last skipped `1717155300`. Its
separate played flag remained zero, confirming the parsed-default limitation
above. These experiments confirm serializer behavior; they do not validate
firmware acceptance, device publication, or recovery after interruption.

## Implications for PR #249

The PR has a historical precedent for allowing a write to proceed when fields
cannot fit a short header. It does not reproduce the whole 1.x behavior: it
filters evidence against each retained header, whereas 1.x first rebuilt a
database-version-sized header. For an identified nano 6G, that difference can
mean preserving a 156-byte header and omitting skip history in the PR versus
reconstructing a 624-byte header and storing skip history in 1.x.
[PR filtering](https://github.com/TheRealSavi/iOpenPod/blob/a8e4be82d394161550352e7f8d0e13e1987cd27c/src/iPodDB/library/_sidecar_projection.py#L82-L101),
[Original header selection](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhit_writer.py#L423-L426)

Original iOpenPod supplies no separate archive for evidence omitted from all
database outputs. The current 2.0 contract improves on that by
archiving consumed sidecars as `.bak`, but replacing one archive on the next
consumption is not cumulative history retention. PR #249 still marks a sidecar
consumed after filtering its unrepresentable metadata. Therefore, the 1.x source
does not resolve the earlier review concern about repeated imports losing
understood skip history.
[PR consumption](https://github.com/TheRealSavi/iOpenPod/blob/a8e4be82d394161550352e7f8d0e13e1987cd27c/src/iPodDB/library/_sidecar_projection.py#L184-L197),
[Current sidecar contract](../playback-sidecars.md#selection-saving-and-recovery),
[ADR-0100](../adr/0100-reconcile-firmware-playback-sidecars-on-device-selection.md)

This research does not choose a new policy. A deliberate header expansion needs
device-format evidence and preservation rules; retaining omitted evidence needs
an explicit identity and lifecycle design; accepting its eventual loss needs an
explicit documented exception. Copying the Original writer's reconstruction
strategy wholesale would also conflict with 2.0's retained-byte contract for
unchanged databases.
[ADR-0006](../adr/0006-require-lossless-ipoddb-round-trips.md)

## Follow-up: device-aware expansion evidence

The following investigation supports the requested repair and distinguishes
device-profile policy, captured-file observations, and implementation hazards.
Neither a retained 156-byte MHIT nor a small reference database version establishes
that an identified device requires that representation.

### Related device profiles

Both Original iOpenPod and the current registry provide this matrix. Header sizes
are the Original writer's version mapping, not an independently established
firmware maximum. The checksum columns describe database publication requirements,
which must remain enforced after changing any bytes.

| Profile | Registry binary version | Original mapped MHIT size | Binary checksum | Compressed / SQLite |
| --- | --- | --- | --- | --- |
| Nano 1 / 2 | `0x13` | 328 | None | No / no |
| Nano 3 / 4 | `0x30` | 624 | HASH58 | No / no |
| Nano 5 | `0x30` | 624 | HASH72 | Yes / yes, HASH72 |
| Nano 6 / 7 | `0x30` | 624 | HASHAB | Yes / yes, HASHAB |
| Full-size iPod 5 / 5.5 | `0x19` | 328 | None | No / no |
| Classic 6 / 6.5 / 7 | `0x30` | 624 | HASH58 | No / no |

[Current catalog](https://github.com/TheRealSavi/iOpenPod/blob/a8e4be82d394161550352e7f8d0e13e1987cd27c/src/device_registry/data/catalog.py#L212-L374),
[Original catalog](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/device/capabilities.py#L224-L520)

### Retained nano captures

Read-only inspection of existing capture files under
`C:/Users/JohnG/Coding/ipods` found 624-byte MHITs throughout five valid CDBs.
Physical reads were bounded to 16 MiB and decompression to 64 MiB. No titles,
identities, or other private Track metadata are reproduced here. The directory
names identify the retained captures; firmware behavior and writer provenance
were not independently re-established in this investigation.

| Capture relative to `ipods` | Root version | Tracks | Header size | Positive skip counts / dates |
| --- | --- | --- | --- | --- |
| `nano5/MINE/iPod_Control/iTunes/iTunesCDB` | `0x73` | 51 | 624 | 9 / 9 |
| `nano5/USER2/iPod_Control/iTunes/iTunesCDB` | `0x73` | 4 | 624 | 0 / 0 |
| `nano5/USERS/iPod_Control/iTunes/iTunesCDB` | `0x73` | 4 | 624 | 0 / 0 |
| `Nano6/myiTunesCDB` | `0x6F` | 522 | 624 | 0 / 218 |
| `orig_nano7/iPod_Control/iTunes/iTunesCDB` | `0x75` | 832 | 624 | 814 / 423 |

Their physical-file SHA-256 fingerprints, in the same order, are:

```text
cc701817f656b1c41fe489f6452551e7eb477c3ac6e8cee44d1ab21c16526b78
33f8b2300cc887f9e5d70c5bd4981a36b2b48ccf3bb812a2b557b187812cee90
d87145f83fe9d44c105946d3dc8a3743dcb6519554be52d59e0bb128c95e8042
69e38476e775ce2b2720af002241816df6e4d2667fbf77ca623fb97b1521671e
7ea2e4c19dbb3fd37b66ec5ea055710087c59b3df854a753f5c5b5ff346b03cf
```

For each valid capture, decompressing, parsing, and serializing without edits
reproduced the logical database bytes exactly. These were local executions of
the existing codec under UV. The accompanying `nano5/MINE/.../iTunesDB` was an
empty stub, not a second valid database. The observed root versions exceed the
registry's `0x30`: a repair must not downgrade those retained versions merely to
match the catalog. These observations support regression coverage across nano
5, 6, and 7; they do not constitute a physical acceptance test of expanded output.

The ADR-0144 implementation was also exercised through public Library no-op
preparation with `WriteTarget(database_version=0x30)` against the first nano 5G,
nano 6G, and nano 7G captures above. The prepared compressed files exactly matched
all 14,134, 173,182, and 280,067 original bytes respectively. This additionally
checks that supplying the expansion capability does not normalize a loaded
database or rewrite its CDB framing when no edit requires expansion.

### Expansion hazards and recommendations

The shared parser defaults any fixed field whose complete extent is outside the
header, while retaining its existing raw bytes. Blindly padding and rewriting a
partially present numeric field therefore replaces real source bytes with the
default. Examples include lengths 158 inside skip count, 162 inside last skipped,
and 170 inside the secondary persistent ID. Reject such numeric-boundary
expansion rather than guessing missing bytes. Opaque fields require a different
treatment: the known 328-byte header ends inside the declared 24-byte raw range
at `0x13C..0x154`, so retain its existing prefix and initialize only the appended
suffix. A blanket rejection of every partial field would reject that established
header size.
[Bounded field parsing and writing](https://github.com/TheRealSavi/iOpenPod/blob/a8e4be82d394161550352e7f8d0e13e1987cd27c/src/iPodDB/shared/binary_struct.py#L119-L231),
[MHIT raw range](https://github.com/TheRealSavi/iOpenPod/blob/a8e4be82d394161550352e7f8d0e13e1987cd27c/src/iPodDB/iTunesDB/shared/chunk_defs/mhit.py#L89-L101)

Newly exposed bytes are not all semantically interchangeable with zero. The
shared definitions contain nonzero defaults for played state, media type, and
several opaque fields. Identity and metadata dependencies also matter: the
secondary persistent Track ID should follow the primary identity when newly
introduced; a newly introduced played flag should reflect the desired state;
artwork and sort flags must agree with retained relationships and MHODs. Only
initialize fields that were absent, never normalize an existing noncanonical
value. Verification must independently distinguish newly introduced fields from
retained ones instead of accepting any writer-provided expanded header as proof.
[Shared defaults](https://github.com/TheRealSavi/iOpenPod/blob/a8e4be82d394161550352e7f8d0e13e1987cd27c/src/iPodDB/iTunesDB/shared/chunk_defs/mhit.py#L55-L119),
[Native Track verification](https://github.com/TheRealSavi/iOpenPod/blob/a8e4be82d394161550352e7f8d0e13e1987cd27c/src/iPodDB/library/_track_verification.py#L108-L215)

libgpod supplies additional historical evidence for secondary identity, artwork,
media, and database-reference fields, but its writer uses a 584-byte MHIT. Thus
the Original project's 156/328/504/624 table should be labeled compatibility
policy, not a universal enumeration of valid MHIT lengths. Preserve longer and
unfamiliar retained headers; do not shrink them to a preferred size.
[libgpod MHIT writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L3749-L3889)

Keep expansion in explicit Library preparation with an identified device-format
policy. Unchanged parsing/serialization must remain byte exact. Unsupported or
ambiguous expansion must retain pending evidence and report a diagnostic; dropping
that evidence is not a substitute. The existing shared serializer can recompute
Chunk and ancestor lengths, but signing, CDB framing, SQLite regeneration, and
transaction verification must still use the resulting verified database.
[Shared Chunk serialization](https://github.com/TheRealSavi/iOpenPod/blob/a8e4be82d394161550352e7f8d0e13e1987cd27c/src/iPodDB/shared/chunk_writer.py#L173-L300),
[CDB and SQLite research](itunescdb-and-sqlite-library.md),
[Lossless contract](../adr/0006-require-lossless-ipoddb-round-trips.md)
