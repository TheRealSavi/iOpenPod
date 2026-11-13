# Nano 1 and Video city and alarm authoring

Research date: 2026-11-13. This report qualifies existing and new city records
for Nano 1 1.3.1 and Video 1.3, including city names, explicit manual DST,
creation, removal, duplicates and empty stores. It closes the city-management
gaps in the [earlier city investigation](alarm-legacy-scheduling-cities-2026-11-13.md).
Nano 2 uses the user's explicit
[Nano 1 compatibility assumption](../adr/0261-use-nano-1-alarm-compatibility-for-nano-2.md);
its encrypted firmware was not executed. No firmware-adoption timing or
physical device work is part of this investigation.

## Exact inputs and execution boundary

| Updater inputs | Release | Complete main-image SHA-256 |
| --- | --- | --- |
| Nano 1 / 14 and 17 | 1.3.1 | `2d34721c1d36f592b076ca111822cea6afcf718331dcf4117618f0eb338bf4cb` |
| Video / 13 and 20 | 1.3 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| Video / 25 | 1.3 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` |

The [new probe][probe] passes **1,150 cases**, 230 on each of the five updater
inputs. Per input, these comprise 204 native constructor/serializer vectors,
four Add City vectors, duplicate retention, middle and final removal, empty
save, five collection-growth cases, five list-size queries, four manual-DST
toggles, a complete three-city store round trip, and three initialization cases.
[Receipt][receipt]

The original creation controllers, constructors, resource lookups, collection
append, count changes, pointer copying, shifting, removal, serializers and
readers execute. Heap allocation/reallocation/free, exception context, byte
streams, filesystem open/path services and notifications are memory adapters.
The DST toggle's schedule recomputation is adapted. Nano 1 initialization's
observers and scheduling services are adapted; Video's tested Add City DST
source follows its saved-setting route with subsystem mode supplied as zero.
No collection append/remove/count implementation is replaced with a Python
list mutation. [Probe][probe]

Nano 1 loads hash-checked initialized memory blocks. Video executes its native
startup copy/zero routine at `00083848`. The final receipt pins each image,
helpers and available map identities and checks every executed instruction
against its original source bytes. The full Video 25 image is checked even
though its executable content matches Video 13/20 and it has extra zero padding.
[Receipt][receipt], [Video loader][video-loader]

| Artifact | SHA-256 |
| --- | --- |
| `scripts/probe_legacy_clock_city_authoring.py` | `23f26b4967149d32815ee45d229c0c421b634811ebbc945522395ddd34319264` |
| `artifacts/clock-city-authoring-20261113-v6/receipt.json` | `f5a625e169d56499c9dc773f740bf5ff36612a2f4352e4fe220750042b38fb53` |

The artifact directory also contains four independently emitted city records
and a complete three-city store for each input. Each catalog case embeds the
exact 125-byte city record. Repeat from the lab with a fresh directory:

```powershell
uv run scripts/probe_legacy_clock_city_authoring.py artifacts/clock-city-authoring-new
```

## City identity and names

The [existing catalog receipt][catalog] qualifies eight regions and 204 cities
through native resource lookup, inverse lookup and base-offset lookup. The new
probe constructs and serializes **every catalog entry** on each input and
asserts that the emitted region and city ordinals match that catalog. Its input
catalog receipt is pinned to SHA-256
`389951eca198e83805b1bb32fb3e73d7483d345c53011e40a29188e984289dbc`.
[Probe][probe], [receipt][receipt]

Use `(region wire ordinal, city wire ordinal)` as the saved identity, and the
catalog's English name for presentation. The city ordinal is resource-relative,
not the city's position in its region. For example, California is native
region/index `(5, 6)`, but its saved identity is `(5, 203)`. Names and saved
ordinals match across Nano 1 and Video. Their base offsets differ for Colombo
and Ponta Delgada, as recorded in the earlier report; those historic firmware
constants should not be replaced with current geographic timezone data.
[Catalog][catalog], [earlier report](alarm-legacy-scheduling-cities-2026-11-13.md)

Unknown existing city identifiers remain Unknown Data. The qualified catalog
supplies new choices; a human-readable label does not justify silently changing
an unrecognized existing identifier.

## One city owns one alarm

The native city object is 0x24 bytes. Its embedded alarm starts at `+0x0c` and
has a back-pointer to the city at `+0x20`. There is no independent collection of
multiple alarms inside a city. Add City constructs the city and its alarm;
Remove City destroys that embedded alarm and frees its owning city.
[Nano constructor][nano-constructor], [Video constructor][video-constructor],
[Nano removal][nano-owned-removal], [Video removal][video-owned-removal]

Consequently, city creation/removal is also creation/removal of its daily alarm.
An alarm can be switched off while retaining the city. Omitting the nested
alarm container is not a native “delete alarm” operation: the reader constructs
the alarm with defaults before reading its fields. The editor should make the
owning city clear rather than imply that several independent alarms can be
appended to the same city object. [Native stores][nano-store], [Video store][video-store]

## Exact new-record contract

Both native Add City controllers allocate 0x24 bytes, call the city constructor,
append the pointer to the collection, select the returned index, mark the owner
dirty and notify. The Nano 1 dirty byte is owner `+0x88`; Video uses `+0x7c`.
The constructor initializes the following saved alarm fields identically:

| Saved field | Native object offset | New value |
| --- | --- | --- |
| Alarm minute, token 6 | city `+0x10` | 0, midnight |
| Active kind, token 7 | city `+0x14` | 8, off |
| Retained sound mode, token `0x1f` | city `+0x18` | 0 |
| Playlist selection, token 8 | city `+0x1c` | 0 |

[Nano Add City][nano-add], [Video Add City][video-add], [receipt][receipt]

The complete store has container ID 0, each city has container ID 1, and each
embedded alarm has container ID 5. All framing/scalar words are little-endian.
Scalar entries are `token, payload byte count, payload, 0x80000000 | token`.
Containers start with `0x40000000 | token` and end with `0xc0000000 | token`.
There is no city count, record ID or checksum in this framing.
[Nano serializer][nano-record], [Video serializer][video-record], [receipt][receipt]

The native new city record is exactly 125 bytes in this order:

```text
start city 1
  token 2:    u32 region wire ordinal
  token 3:    u32 city wire ordinal
  token 0x14: u8 manual DST
  start alarm 5
    token 6:    u32 minute = 0
    token 7:    u32 active kind = 8
    token 0x1f: u32 retained sound mode = 0
    token 8:    u32 Playlist selection = 0
  end alarm 5
end city 1
```

The one-byte DST payload has no alignment padding. In this native default
layout only, the DST byte is at city-record offset 44; subsequent tokens are
unaligned. Existing files can contain other retained fields/orderings, so
writers must locate their tokens rather than use this illustrative fixed
offset. A store of these native default records has length `8 + 125 * cities`.
[Receipt][receipt]

The native three-city store round trip retains duplicate California records,
different DST values and a third Asian city in their original order. It
executes both complete store writer and complete store reader, with byte/file
services adapted. The emitted files are
`clock-store-{14,17,13,20,25}-3.bin` in the receipt directory.
[Probe][probe], [receipt][receipt]

## Manual daylight saving is explicit saved state

Token `0x14` has a one-byte payload at city object `+8`. The native DST action
changes zero to one and any nonzero value to zero. Executed cases cover 0, 1,
2 and 255, verify that only that city byte changes, and serialize the result.
The alarm's minute, enabled kind and sound choices are preserved.
[Nano DST action][nano-dst], [Video DST action][video-dst], [receipt][receipt]

Nano 1 Add City derives its default DST byte from the owner's current timezone
menu enum. Video calls its current settings DST getter before construction;
the tested getter route reads the saved settings byte. For Host authoring an
explicit DST checkbox with byte value 0 or 1 supplies the required native field
without inferring the Host timezone or current geographic DST rules. Preserve
other existing byte values until an explicit edit replaces them.
[Nano Add City][nano-add], [Video Add City][video-add], [Video DST getter][video-dst-source]

## Duplicates, growth and removal

The native Add City controllers do not search for an existing matching city.
The probe adds the same California identity twice with different DST states and
verifies two distinct owned city objects. Repeated native Add City calls grow
the real collection to 1, 4, 8, 32 and **64 duplicate entries**, with the original
collection growth/count/copy code executing. [Receipt][receipt]

No fixed city maximum is enforced in the inspected Add City, generic growth or
list-query paths. Nano 1 list query `00190070` / property `0x619b` and Video
`002370f0` / property `0x619f` return `city count + 1`, including the Add City
row. Native query vectors at 0, 1, 64, 204 and 4,096 all follow that rule.
The 4,096 case is a list-query test, not 4,096 actual allocations. The evidence
does not establish unlimited memory or a safe physical maximum; it does rule
out deriving a four-city or last-city restriction from these paths.
[Nano list query][nano-list], [Video list query][video-list], [receipt][receipt]

Remove City takes the selected index, frees its owned city/alarm, validates the
index, shifts later pointers and decrements the count. The controller decrements
the selected index only if it was positive, then marks the collection dirty.
The middle-removal case confirms preserved ordering. Repeated removal reaches
zero entries with selection zero, including successful deletion of the final
city. The probe uses valid selected indices; it does not claim malformed indices
are safe, particularly because the ownership/free path precedes generic index
validation. [Nano controller][nano-remove], [Video controller][video-remove],
[Nano owned removal][nano-owned-removal], [Video owned removal][video-owned-removal],
[receipt][receipt]

## Empty and missing store semantics

After deleting the final city, the original store writer emits exactly:

```text
00 00 00 40 00 00 00 c0
```

That is a valid empty outer container. Its lack of city entries does not require
the Host to invent a replacement city. [Receipt][receipt]

Separately, the original initialization routines inspect the resulting
collection after their original store loader returns. If it is empty, they
choose North America / California, call the native Add City controller and
select index zero. Native initialization was executed for each of:

- A successfully opened, correctly framed empty store.
- A file-open error supplied by the filesystem adapter, representing a missing
  or unavailable store. The firmware's precise error number is not distinguished
  by this branch.
- A successfully opened zero-byte stream whose first read fails at EOF.

Each case produces one California city with its default off/midnight alarm.
This is initialization behavior, not a Host instruction to recreate a deleted
city, and not a promise about when initialization occurs. A zero-byte file is
not the qualified format for a new empty store: write the eight-byte framed
container. Other malformed/truncated inputs were not exhaustively tested and
should not be treated as permission to replace damaged source bytes.
[Nano initialization][nano-init], [Video initialization][video-init],
[Nano store][nano-store], [Video store][video-store], [receipt][receipt]

## Implementation boundary

The independent [product comparison][product-validation] checks `cities.py`
and `clock.py` against the captured native results. **No mismatches** were found
in all five images' 204 city names, region names, saved identifiers and complete
125-byte default records: 1,020 native record vectors. Each record also passes
product parse, byte-identical unchanged write, creation and final-city removal.
Twenty Add City vectors, twenty manual-DST transitions (including existing bytes
2 and 255), and five complete three-city stores match as well. The store checks
include duplicate identities and middle/final removal. This comparison executes
product code against prior original-instruction results; it is not a second
firmware execution or a physical-device test. [Validation receipt][product-receipt]

The checked-in [native fixture][product-fixture] retains every independently
emitted default record, names and region identifiers, the four explicit Add
City vectors, empty framing and all source/image hashes. The 204 default records
are stored once because all five firmware inputs emitted byte-identical
records for the corresponding city. It can drive product tests without a lab
checkout; it contains captured outputs rather than product-generated expected
bytes. Fixture SHA-256:
`50cf516d3a3944e70a0c841ef9ce9643cf1399529635c20e33dc4652b7fc16b1`.

The comparison receipt pins the inspected product files: `cities.py`
`06d1e4bbb159e6e34e600c4f3fbdf1a4e0d77abe036beda259db09a86a6bb191` and
`clock.py` `b814e1411e7efab6cd617617093fadce40b3c5319e92c17094f7878bdf659cc7`.
Run the comparison from iOpenPod with a fresh output path:

```powershell
uv run python ../ipod-firmware-lab/scripts/validate_iopenpod_clock_cities_20261113.py ../ipod-firmware-lab/artifacts/clock-city-product-validation-new.json
```

The verified contract supports catalog-based city labels, explicit city identity
and manual-DST edits, native-default city/alarm insertion, and removal of the
selected complete city container. Preserve Unknown Data and unrelated city
records byte-for-byte. Duplicate city identities are valid, so selection and
deletion must identify the source record rather than collapse by city name.
Do not impose a firmware-derived last-city block or a fixed four-city maximum.
The firmware's default-city initialization remains firmware behavior; no Host
repair is introduced.

Only the pure file operations are qualified here. Nano 2 remains an explicit
compatibility policy, and physical memory limits, wake/audio delivery and
mounted-file adoption are outside this investigation. No product source or
physical device files were changed by this research pass.

[probe]: ../../../ipod-firmware-lab/scripts/probe_legacy_clock_city_authoring.py
[receipt]: ../../../ipod-firmware-lab/artifacts/clock-city-authoring-20261113-v6/receipt.json
[catalog]: ../../../ipod-firmware-lab/artifacts/legacy-clock-cities-20261113-v3/receipt.json
[product-validation]: ../../../ipod-firmware-lab/scripts/validate_iopenpod_clock_cities_20261113.py
[product-receipt]: ../../../ipod-firmware-lab/artifacts/clock-city-product-validation-20261113-v1.json
[product-fixture]: ../../tests/fixtures/alarms/native_clock_cities.json
[video-loader]: ../../../ipod-firmware-lab/scripts/sidb_video_native.py
[nano-constructor]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000a6e38.c
[video-constructor]: ../../../ipod-firmware-lab/artifacts/clock-city-authoring-20261113-video/00142238.c
[nano-add]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00190c74.c
[video-add]: ../../../ipod-firmware-lab/artifacts/clock-city-authoring-20261113-video/00237cdc.c
[nano-remove]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00190ce0.c
[video-remove]: ../../../ipod-firmware-lab/artifacts/clock-city-authoring-20261113-video/00237d48.c
[nano-owned-removal]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/001d982c.c
[video-owned-removal]: ../../../ipod-firmware-lab/artifacts/clock-city-authoring-20261113-video/00299dc0.c
[nano-record]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000a6c44.c
[video-record]: ../../../ipod-firmware-lab/artifacts/clock-city-authoring-20261113-video/00142068.c
[nano-store]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00191be4.c
[video-store]: ../../../ipod-firmware-lab/artifacts/clock-city-authoring-20261113-video/00238f2c.c
[nano-dst]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/0019177c.c
[video-dst]: ../../../ipod-firmware-lab/artifacts/preferences-video-clock-export-20261107-v1/00238a90.c
[video-dst-source]: ../../../ipod-firmware-lab/artifacts/clock-city-authoring-20261113-video/001931dc.c
[nano-list]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00190070.c
[video-list]: ../../../ipod-firmware-lab/artifacts/clock-city-authoring-20261113-video-array/002370f0.c
[nano-init]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00191018.c
[video-init]: ../../../ipod-firmware-lab/artifacts/clock-city-authoring-20261113-video/002381f8.c
