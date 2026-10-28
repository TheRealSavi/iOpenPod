# Unknown field definitions reconciled with existing firmware research

This is the initial inventory. The subsequent [consumer investigation](unknown-itunesdb-field-consumers.md)
identifies additional fields and replaces several aggregate definitions with
their actual subfields. Use that follow-up for the current adopted schema.

Audited 2026-10-28. Scope: iTunesDB, ArtworkDB and PhotosDB shared Chunk
definitions, their MHOD payload definitions/type registries, and the existing
Preferences and sidecar interpretations. This pass reuses completed research;
it introduces no new firmware experiment or device operation.

The direct firmware evidence is Classic 120GB RetailOS 2.0.1, normalized OSOS
SHA-256 `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`.
Other models are not established by that trace. Offsets below refer to serialized
records unless explicitly labeled runtime, atom-relative or operand-relative.
The local wiki's `content/fields.json` indexes these findings; the linked lab
reports supply the detailed instructions and their evidence boundaries.

## Names now supported by the evidence

| Record / offset | Previous member | Adopted member | Exact meaning |
| --- | --- | --- | --- |
| MHIT `+0x14`, u32 | `unk_class_flag` | `record_class` | 1 selects constructor tag `FILE`, 2 `SHRD`, 3 `HTTP`. Other values make this Classic importer skip the Track and its children. This does not establish complete transport behavior for these classes. |
| MHYP `+0x15`, u8 | `flag_1` | `shuffle_flags` | Bit 0 becomes native list `+0x130` bit 0, which selects shuffled traversal. Upper bits remain unidentified and preserved. |
| MHYP `+0x28`, u16 | `unk_mhyp_0x28` | `serialized_repeat_override` | 0 preserves the existing/default mode; 1 selects off, 2 one, 3 all; any other nonzero value selects off. This is a serialized override, not the runtime or player API enumeration. |

Sources: [Track class selection][track], [playlist import and playback traversal][consumers],
and [repeat mapping and next/previous predicates][playlist]. Class dispatch is
inside `0x08073BB8`; repeat conversion is `0x08073240–0x08073278`; predicates
`0x0815A5E8` / `0x0815A61C` independently establish the native mode meanings.

Offsets, encodings and defaults are unchanged: record class defaults to 1,
shuffle flags to 0, and repeat override to 1. Unknown values still round-trip;
these names do not add Classic rejection rules to the lossless parser or new
editing controls. Low-level attribute/JSON names change for these three fields.
[ADR-0195](../adr/0195-adopt-firmware-database-field-semantics.md) now records the
repeat member rename while retaining its raw-value preservation policy.

## Existing explanations added without inventing names

| Record / offset | What the completed research establishes | Why the raw name remains |
| --- | --- | --- |
| MHIT `+0xFC` | Copied beside `+0xF8` into runtime TrackRecord `+0x108/+0x10C`. | Not proven to be a high size word or any other particular value. |
| MHIT raw region `+0x13C` | Includes word `+0x144`, copied to runtime `+0xB4`. | The copied word's meaning and the rest of the region remain unidentified. |
| MHIT `+0x173` | Any nonzero byte sets runtime flags mask `0x1000` and contributes to extension allocation. | Feature meaning is unknown; this is a whole-byte nonzero test, not bit-zero semantics. |
| MHYP `+0x17` | Bit 0 maps to runtime list `+0x150` bit 2. | Destination bit's role remains unidentified. |
| MHYP `+0x38` | Copied to runtime list `+0x1C0`. | Copy destination alone is insufficient for a semantic name. |
| MHIP `+0x12` | Adjacent podcast grouping bytes have separate handling. | Evidence for neighbors does not identify this whole retained word. |
| String MHOD `+0x20` | Low byte zero selects composition-like processing for source encoding 1; nonzero bypasses it. | Upper 24 bits are unknown; not a proven complete Unicode normalization mode. |
| Smart MHOD51 `+0x1C` / nested SLst `+0x04` | A halfword is checked below 2 after header conversion. | Complete word layout and the other half remain unresolved. |
| Smart MHOD50 `padding_0x26` | Its first byte, payload-relative `+0x0E`, influences metadata attachment. | The inherited “padding” name must not imply unused bytes; exact role is unidentified. |
| Numeric Smart operand `+0x30..+0x43` | Inspected conversion/bound calculations leave these 20 bytes alone. | Other consumers may exist; not proof of padding. |
| Artwork MHFD `+0x0C` | `0x080427E4` requires zero, otherwise returns -208. | Not proof that it is a version field or universally required zero. |
| Artwork MHFD `+0x10` | Low 16 bits may be returned to an optional caller. | Output purpose remains unknown. |
| Artwork MHFD `+0x34` | Copied to runtime library `+0x9C8`; zero/nonzero selects an import-progress channel. | Complete value domain and other uses are unestablished. |
| Artwork MHFD `+0x38` | Copied to runtime library `+0x9CC`. | No established semantic interpretation. |
| Artwork/Photos MHII `+0x24` | The later trace identifies its ascending unsigned ordering comparator and image enumeration consumer. | Adopted as `image_order_key`; see the [MHII follow-up](mhii-image-field-followup.md), including the separate `+0x1C` and inherited rating word. |

Sources: [Track import][track], [playlist/MHOD consumers][consumers],
[string conversion][text], [Smart date operands][smart], and
[ArtworkDB import][artwork]. Source comments carry these qualifications.
PhotosDB's separate root definition explicitly avoids treating ArtworkDB's
validation as a proven PhotosDB contract.

The common iTunesDB MHOD header's `+0x10/+0x14` words remain unidentified:
Classic's endian helper swaps the preceding four words but leaves these alone.
MHBD's unknown 20-byte range at `+0x32` is zeroed in the *temporary legacy digest
input*; that does not establish its stored purpose or authorize clearing it.
Also, the historical u16 `platform` member spans a separately observed byte
`+0x21`, used as a strict bookmark-percentage threshold for played status. That
partial observation does not rename the entire word. See [loader/authentication
and sidecar analysis][lifecycle].

## Knowledge already incorporated

The audit found several apparent gaps already handled by earlier changes:

- MHNI `image_time_key` is named and retained as the raw serialized key.
- Chapter `hedr +0x18` already has a typed `.flags` accessor: mask 1 enables
  named chapters; mask 2 enables chapter artwork import. Its raw `unk_0x18`
  member remains compatible under ADR-0202. `hedr +0x14` is a different word.
- Total skips and the independent secondary counter are correctly mapped to
  MHIT `+0x98/+0x9C`. An older Track-import report labels these differently;
  later counter research and ADR-0195 supersede it.
- Clock city ID, saved DST and software bias already have qualified Classic
  Preferences definitions. Their storage does not establish hardware UTC/local
  provenance. Alternate Audio also already has a named qualified field.
- Chapter names/starts and the MHOD32 codec FourCC already have typed readers.
  The remaining descriptor bytes are retained, not newly identified by the
  video subtitle/caption research.

See [artwork/Chapter adoption](../adr/0202-adopt-native-artwork-and-chapter-semantics.md),
[clock adoption](../adr/0196-adopt-firmware-clock-and-date-evidence.md) and
[video adoption](../adr/0205-adopt-native-video-playback-contracts.md).

## Remaining unknowns

These definitions were checked, but the existing research does not establish
additional semantic names. Partial cases above remain included as unknown.

| Definition area | Unresolved fields/ranges |
| --- | --- |
| MHIT | `+0x84`, `0x94`, `0xB3`, `0xC4`, `0xEC`, `0xF4`, `0xFC`, `0x104` (20 raw bytes), `0x118`, `0x11C`, `0x130`, `0x13C` (24 raw bytes), `0x154`, `0x158` (8 raw bytes), `0x164`, `0x168`, `0x173`, `0x197`, `0x1A0`, `0x1C8`, `0x1D8`, `0x1EC`, `0x20C`, `0x229`, `0x22B`. |
| MHBD | `+0x22`, `0x2C`, `0x32` (20 bytes), `0x50`, `0x54`, `0xA4`, `0xA6`. |
| MHYP / MHIP | MHYP `+0x16`, `0x17`, `0x24`, `0x38`, `0x4C`, `0x54`, unknown flag bits and suffix; MHIP `+0x12` and unnamed header bytes. |
| Common/string MHOD | Common `+0x10/+0x14`; string `+0x24` and upper bits at `+0x20`. |
| Smart and index payloads | MHOD50 retained padding ranges; MHOD51 version slot, header data, per-rule data and numeric tail; MHOD52/53 `+0x20` padding and MHOD53 row `+0x02`; MHOD100 position padding and opaque MHYP display preferences; MHOD102 opaque settings words. |
| Chapter payloads | MHOD17 preamble `+0x18/+0x1C/+0x20`; `sean +0x08/+0x10`; `chap +0x10`; `name +0x08/+0x0C/+0x10`; `hedr +0x08/+0x10/+0x14` and unknown bits at `+0x18`. Atom offsets are relative to each atom. |
| Artwork / Photos root | MHFD `+0x0C`, `0x10`, `0x18`, `0x20` (u64), `0x28` (u64), `0x30`, `0x34`, `0x38`, `0x3C`, `0x40`; separate PhotosDB definition has the same unresolved coordinates. |
| Other Artwork / Photos | MHII `+0x1C/+0x24`; MHBA `+0x18/+0x1C/+0x2C`; MHSD `+0x0E`; MHOD `+0x0E/+0x10`; string prefix-relative `+0x05/+0x08`; opaque MHAF body. |
| Opaque type identities | iTunesDB MHOD 11, 33–36, 38, 40–41, 101; Artwork/Photos MHOD 4 and 6. Known container shape or a skip branch does not establish purpose. |
| Unnamed bytes and other formats | MHLP/MHLT tails, album/artist header gaps, opaque payload tails and uninterpreted Preferences bytes remain retained. No new Classic-derived meaning is assigned to SQLite columns or sidecar fields without a matching format/consumer. |

The separate [MHOD10 investigation](mhod-10-provenance.md) also invalidates
treating the current `LYRICS` label as native evidence. It remains a documented
legacy application mapping in this naming pass; removing its projection/writer
requires separate preservation and migration work. It is not renamed to
“podcast description” merely because the observed payloads contain that text.

## Verification

Independent literal-offset fixtures check the renamed class word, arbitrary
unknown class values, exact round trips and isolated edits. Playlist fixtures
exercise upper shuffle bits, raw repeat values including zero and `0xFFFF`, both
dataset copies, text edits and short headers. Comments introduce no new parser
validation or writer defaults. Repository checks and the full eight-worker test
suite validate integration; these are Host tests, not physical firmware tests.

Validation on 2026-10-28: lockfile, Ruff formatting/lint, Rumdl, Mypy and
`git diff --check` passed. The default eight-worker `uv run pytest` run completed
with **9,259 passed, 47 skipped**. Its one warning was Pillow's size warning from
the intentional large-photo fixture, unrelated to these field changes.

[track]: ../../../ipod-firmware-lab/notes/itunesdb/track-import.md
[consumers]: ../../../ipod-firmware-lab/notes/itunesdb/consumers-and-playlists.md
[playlist]: ../../../ipod-firmware-lab/notes/itunesdb/playlist-record-semantics.md
[text]: ../../../ipod-firmware-lab/notes/itunesdb/track-text-import.md
[smart]: ../../../ipod-firmware-lab/notes/itunesdb/smart-time-rules.md
[artwork]: ../../../ipod-firmware-lab/notes/itunesdb/artwork-import-and-file-contract.md
[lifecycle]: ../../../ipod-firmware-lab/notes/itunesdb/lifecycle.md
