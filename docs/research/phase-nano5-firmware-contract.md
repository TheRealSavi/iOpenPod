# Phase on nano 5: firmware contract

Research date: 2026-10-30. This independently traces nano 5 RetailOS **1.0.2,
34A20020**, rather than assuming the Classic binary database importer applies to
SQLite. No physical iPod was accessed or changed.

## Result

Phase continues to use its game SDK and separate **Phase Library** and per-song
analysis files on nano 5. The SDK provides the native library abstraction; the
game does not need to parse SQLite or an iTunesDB MHYP/MHIT header itself.

- Playlist selection still uses the full persistent ID stored in the Phase
  Library header, then the exact title `Phase` if no ID matches.
- Nano 5 exposes the same 64-bit persistent identities through the relevant SDK
  slots. SQLite `container.pid` and `item.pid` correspond to the binary database
  persistent IDs; ordinary 32-bit Track IDs are not substitutes.
- The writable game directory remains
  `iPod_Control/GameData_RW/1D000/Phase Data/`. Neither the index nor user analysis
  files move into the SQLite database bundle.
- There **is** a native consumer of distinguished kind **25**: nano 5's user
  Playlist classifier explicitly accepts it. It also accepts ordinary kind 0.
  Kind 25 is therefore recognized, but is not required by this classifier and
  does not select the Phase Playlist by itself.

These conclusions combine static firmware tracing, native instruction probes,
and captured SQLite/CDB identity comparisons. They do not establish physical
custom-song playback or reproduce iTunes' audio-to-gameplay analysis algorithm.

## Exact images and SDK identity

| Input | SHA-256 |
| --- | --- |
| Nano 5 plaintext OSOS, 7,284,288 bytes | `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49` |
| Decrypted Phase build 3168002, 947,252 bytes | `35834fede51f170a0b0bda8e380e1c12af0f86ca1a7952e5abfbb24ab4082258` |

The firmware is mapped independently: raw offsets `0..0xe27c` to SRAM
`0x22000000`, `0xe27c..0x2e27c` to SRAM `0x22030000`, and the following
`0x6c43a8` initialized bytes to DRAM `0x08000000`. The
[map receipt][map-check] checks every initialized byte against the source.

All eleven SDK module UUIDs referenced by the game occur exactly once in the
nano image, with the same function counts as the Classic descriptors. In
particular:

| Module | UUID bytes, in image order | Nano descriptor | Function table | Count |
| --- | --- | --- | --- | --- |
| Metadata | `1eeeb60309134d1b77a8c3ca3298fa7b` | `0x086c41e4` | `0x086c3f40` | 169 |
| AsyncFileIO | `0012f0601105c3a75125314e17aa989a` | `0x086c398c` | `0x086c3948` | 17 |

The module match identifies import indices; each important function was then
traced separately. Nano function pointers have their Thumb bit set. Addresses
below omit that bit when naming a function.

## Persistent IDs and duration

| Game operation | Metadata slot | Nano SDK entry | Native consumer |
| --- | --- | --- | --- |
| Playlist PID | 162 | `0x0800dd98` | `0x0827e7a4`, resolves Playlist row and returns its `+0x10/+0x14` |
| Track PID | 97 | `0x0800e348` | `0x0827bad0`, returns game Track object's `+0x08/+0x0c` |
| Whole seconds | 119 | `0x0800e1e4` | `0x08279d54`, unsigned milliseconds divided by 1,000 |
| Milliseconds | 120 | `0x0800e1f8` | `0x0826369c`, numeric metadata lookup followed by conversion to unsigned integer |
| User Playlist count | 61 | `0x0800dd40` | `0x0830a384`, excludes the root/master entry |

Both PID getters return through **R0/R1**. The SDK resolves handles through the
game context's Playlist table at `+0x90/+0x94` and Track table at `+0xac/+0xb0`.
The context singleton is referenced at `0x0855080c`.

Thirty native ID cases cover zero, one, mixed high/low words, values above signed
64-bit range, all bits set, and valid/invalid handles. These execute actual SDK
lookup, original vtables, and getter instructions without function adapters.
The objects and handle tables are synthetic. They are not a booted SQLite
library.

The separate [database note](phase-nano5-database-notes.md) checks three retained
nano 5 libraries: every SQLite Track PID equals the corresponding CDB persistent
ID set, and every SQLite Playlist PID exists among binary MHYP Playlist IDs.
Signed SQLite presentation does not change the underlying 64 bits.

Eight duration cases verify truncation at the same boundaries as Classic:
29,999 ms becomes 29 seconds, 30,000 becomes 30, 1,800,999 becomes 1,800,
and 1,801,000 becomes 1,801. The millisecond provider is explicitly modeled in
this probe; the native SDK dispatch and integer division run unchanged. The
probe does not exercise the underlying SQLite floating-point conversion.

## Where kind 25 is consumed

The container reader at `0x082d30ec` uses the SQL statement at `0x084333a0`:

```sql
SELECT container.pid, distinguished_kind, name, parent_pid, media_kinds,
       is_hidden, smart_is_folder, smart_is_dynamic, smart_is_filtered,
       smart_is_genius, smart_is_limited, smart_limit_kind, smart_limit_order,
       smart_limit_value, smart_reverse_limit_order, smart_criteria,
       description, container_ui.play_order, container_ui.is_reversed
FROM container, container_ui
WHERE container.pid IS NOT NULL
  AND name IS NOT NULL
  AND container.pid = container_ui.container_pid
ORDER BY name_order;
```

The join means a `container` row alone is insufficient for this reader: a
matching `container_ui` row must also exist. Ordered membership comes from the
statement at `0x08432964`:

```sql
SELECT item_pid FROM item_to_container
WHERE container_pid = ?1 ORDER BY physical_order;
```

The initialization path reaches `0x081edaae`, which visits every container row
through `0x08228320`. That routine builds lookup caches and populates the user
Playlist vector at native `+0x14c/+0x150`. Its kind predicate is
`0x0820777e`, proposed name **Research_Library_IsUserPlaylistKind**:

```text
kind = ReadPlaylistKind(row)       // 0x0822b8dc, integer property 1
return kind in {0, 17, 101, 20, 25}
```

The literal comparisons include `cmp r0,#0x19` at `0x08207796`.
Seventeen native probe cases verify this exact acceptance set, including rejected
values immediately around the accepted ones. Only the row accessor is modeled.

Other Boolean and media checks in `0x08228320` still apply. It converts the
row's media mask and admits zero or an intersection with `0x0020015d` before
adding the row to this vector. Kind 25 does not bypass these checks.

The SDK's count path reads that vector through `0x082a2b1a`, adding a root
entry internally, and `0x0830a384` subtracts it again for user enumeration.
Playlist lookup follows `0x0825cca0` -> `0x0826eada`, resolving user ordinal
`n` through internal ordinal `n + 1`.

This resolves part of the previous uncertainty: **25 has a real native
classification consumer on nano 5**. It does not prove that every observed MHYP
`+0x52 == 25` was copied to SQLite `distinguished_kind`, nor recover the original
Apple enum name. None of the three retained captures contains a Phase Playlist
or kind 25. An iTunes producer-side instruction to generate analysis remains a
hypothesis. Ordinary kind 0 passes the same native kind predicate.

## Game selection and media masks

Five bridge probes execute the real ARM `Phase_SelectMusicPlaylist`
(`0x180416c4`) and its PID wrapper, resolving Metadata 162 to the actual nano 5
Thumb SDK entry:

- A matching stored PID selects a renamed Playlist before the `Phase` fallback.
- IDs with equal low words and different high words select the correct Playlist.
- With no stored PID, exact `Phase` matches.
- An absent stored PID falls back to exact `Phase`.
- `Phase Music` alone does not match the fallback.

Playlist enumeration, titles, temporary handles, configuration, lazy SDK
initialization, and UI are modeled. This bridge proves the game and nano PID
calling conventions agree; it is not full firmware boot or SQLite integration.

Metadata 57 at `0x0800def4` dispatches to the game browser's media-mask setter
`0x0830a3aa` and then `0x082a889c`. The latter retains Phase's SDK include mask
`1` and exclude mask `0x7e` at native `+0xbc/+0xc0`, marks browse caches dirty,
and invalidates cached row selection with `0xffffffff` at `+0x14c`.
Three native cases verify these writes. These are game-browser fields, not
serialized SQLite column offsets or the native container-collection vector.

## Companion storage

Native directory selector `0x081c1d50` returns:

| Directory kind | Exact firmware string |
| --- | --- |
| 0 or 4 | `games_RO` |
| 1 | `gamedata_RW` |
| 2 | `gamestats_WO` |
| 3 | `gamedata_ShareRW` |

Five native cases execute its inline Thumb switch table and ARM switch helper
`0x0818f268` without adapters. Linear decompilation misses that switch and can
misleadingly display one constant return.

`0x08193c30` combines directory kind 1, installation identity and relative path:

```text
iPod_Control/gamedata_RW/1D000/Phase Data/Phase Library
iPod_Control/gamedata_RW/1D000/Phase Data/F007/8877665544332211
```

Existing FAT directory capitalization may differ. `F007` remains a shard from
the game's index, and the filename is the full Track PID in uppercase hex.
The same Phase executable owns index and PHZ parsing, so SQLite changes the
library provider, not these game-owned formats. Their detailed native parser
evidence is in the [original Phase report](phase-playlist-contract.md).

## iOpenPod implications

A nano 5 implementation must publish the Playlist in **both** the CDB generation
and the complete SQLite companion set, including `container_ui` and ordered
membership. Its Phase Library header and analysis records must use the final
published Playlist/Track PIDs. CDB-only creation or preserving the old halfword
alone cannot establish the device-visible SQLite Playlist.

The evidence supports using an ordinary visible music Playlist for the game's
ID/name selection. It does not justify inventing a mandatory `25` flag gate or
claim that simply authoring the Playlist makes songs playable. Valid Phase
Library records and musically useful per-song analysis remain necessary.
No product behavior or architectural decision was changed by this investigation.

## Saved deobfuscation and reproduction

Fifteen analyst-proposed names and comments are saved in
`Nano5FW/ghidra-final-keys/Nano5FinalKeys.gpr`, program `osos.raw.bin`, using
runtime addresses. The two SDK PID functions and two model PID getters have
explicit unsigned 64-bit return types. The
[annotation receipt][names] confirms all initialized image bytes were unchanged.
These are proposed semantic names, not recovered Apple source symbols.

From `ipod-firmware-lab`:

```powershell
uv run scripts/phase_nano5_map_sdk.py
uv run scripts/phase_nano5_find_sql_refs.py
uv run scripts/probe_phase_nano5.py
```

The final script passes **68** cases: 30 identity, 8 duration, 17 kind classifier,
3 filter setter, 5 directory selector, and 5 game-to-nano PID bridge cases.
Every adapter is recorded in the [native receipt][probes]. Static function and
instruction exports are retained below [the lab artifact directory][artifacts].
No physical game launch or custom-chart playback is claimed.

[map-check]: ../../../ipod-firmware-lab/artifacts/phase-nano5/runtime-map-check.json
[names]: ../../../ipod-firmware-lab/artifacts/phase-nano5/applied-research-names.tsv
[probes]: ../../../ipod-firmware-lab/artifacts/phase-nano5/native-sdk-probes.json
[artifacts]: ../../../ipod-firmware-lab/artifacts/phase-nano5/
