# Remaining iTunesDB fields: firmware consumers and schema adoption

Research and adoption date: 2026-10-28. This follows the
[earlier definition audit](unknown-field-reconciliation.md) with new instruction
exports and downstream consumer traces. The source is Classic 120GB RetailOS
2.0.1, normalized OSOS SHA-256
`220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`.
Other models remain a compatibility inference; these are static and Host-test
results, not physical playback observations.

## Actual field definitions

| Serialized location | Adopted representation | Established meaning |
| --- | --- | --- |
| MHBD +0x20 / +0x21 | Separate platform byte and `played_mark_threshold_percent` byte | The second byte supplies the strict bookmark-percentage comparison for played status. Preserve values above 100 too. |
| MHBD +0x22 / +0x23 | Two separate raw u8 fields | Independently imported and exposed through distinct game-library getters. Feature meanings remain unknown. |
| MHBD +0xA4 | `genius_target_count`, u16 | A ready generator stops when collected occurrence count equals this target. Zero is literal. |
| MHBD +0xA6 | `genius_minimum_count`, u16 | A ready result passes when occurrence count is unsigned >= this minimum. Independent of the target. |
| MHIT +0xF8..+0xFF | `gapless_audio_payload_size`, u64 | The getter returns both words as one 64-bit value. The formerly unknown +0xFC word is included in serialization, projection and verification. |
| MHIT +0x144 | `protected_timing_selector`, u32 | Second identifier passed beside user ID to the protected timing-window query. Unknown bytes before and after remain separate raw fields. |
| MHIP +0x10 | `unchecked_override`, u8 | An eligible ordinary row with any nonzero byte sets the shared Track unchecked flag. Zero leaves its current state unchanged. |
| MHIP +0x11 | `group_marker`, u8 | Any nonzero byte selects a group row and bypasses the ordinary Track route. This byte does not exchange position with +0x10 in a reversed-endian database. |
| MHOD51 +0x1C / nested SLst +4 | `format_version`, big-endian u16, followed by an unidentified halfword | Both halfwords are swapped independently. The version gate accepts 0/1 and rejects 2..65535. |
| Smart rule +8 / +9 | Separate raw u8 nesting and disabled markers; remaining two bytes retained | Each known byte uses whole-byte nonzero semantics. 2 and 255 are as nonzero as 1. |
| MHOD51 +0x27 / SLst +0x0F | `conjunction`, u8, preceded by three raw unknown bytes | Zero means ALL; every nonzero value means ANY. Unchanged meaning preserves noncanonical bytes. |
| MHOD50 +0x1C | `limit_sort`, u32 | All four bytes reach native sort conversion; upper bytes are not padding. |
| MHOD50 +0x26 | `attachment_inhibit`, u8, followed by 57 retained bytes | Nonzero prevents this import visit from setting a sticky attachment flag; it does not clear an earlier decision. |
| String MHOD +0x20 | `bypass_pair_composition`, u8, followed by three retained bytes | For source encoding 1, nonzero bypasses adjacent-unit composition. The physical first byte controls this even on the reversed-endian path. |

The schema expresses these widths and separations directly. Raw retention is not
used as a substitute for representing known subfields. Binary offsets and
existing authoring defaults remain unchanged; low-level constructor/JSON member
names change where aggregates are split. No normalization of noncanonical but
retained bytes is introduced.

## Reader, writer and application effects

The full 64-bit audio-size value reaches the existing Track projection and media
preparation/verification path. Its inherited gapless payload-size label is not
independently re-proven by this getter alone; the verified improvement is that
the upper word is no longer treated as unrelated Unknown Data. The timing selector
is retained as an explicit identifier, without inventing license-authoring rules.

Smart nested parsing uses its separate nesting byte. Writers retain noncanonical
nesting values, disabled state, unidentified control bytes and header data during
semantic operand edits. The previous nested writer normalized the entire control
word; the widened editable leaf path also needed to preserve retained header bytes.

Disabled conditions, unsupported versions and nonzero attachment controls remain
read-only in the current product model. The model has no disabled-node or
import-order latch representation, so it preserves native saved membership and
the complete configuration. This prevents known-looking operands from becoming
active after an unrelated edit. Unsupported full-width sort selectors likewise
cannot be treated as their low byte. No new Smart evaluator or Unicode
normalization policy is introduced.

Affected folders also reject disabled or nested membership rules and unsupported
SLst versions before reconciliation. Prepared-output verification independently
checks those conditions, so a disabled child cannot silently become active while
the Host rebuilds aggregate membership.

The Genius thresholds are named raw fields. No producer defaults such as 25/10,
automatic repair, UI controls, or replacement Host ranking policy is inferred.

MHIP's former combined `podcast_group_flag` is removed. Group creation uses
`group_marker=1`; projection, reconciliation and verification use the common
`is_group` predicate. Existing unchecked overrides and noncanonical group markers
remain independent during edits and Podcast normalization. This represents the
bytes accurately without claiming a complete emulation of runtime checked state:
the firmware visits only the first Playlist dataset (type 2 or 3), resolves row
parents sequentially and applies overrides only to successfully created ordinary
occurrences. Host Track metadata continues to use the retained MHIT checked flag.

## Remaining unknowns and qualified discoveries

MHYP +0x2A bit 0 has an additional confirmed effect: its native flag blocks
shuffle modification and participates in fallback list selection. Its existing
broader `playlist_kind_flags` name remains appropriate. MHYP +0x17 bit 0 and
+0x38 still lack identified semantic consumers after the bounded scan.

MHIT +0x173 sets native mask 0x1000 but remains unnamed. A neighboring policy
path uses mask 0x2000 instead; merging those flags would be an error. The new
timing-query trace identifies whole-day and expiry calculations, not a complete
security format. MHBD +0x22/+0x23 now have individually represented bytes, but
their game API exposure is not sufficient to assign feature names.

## Evidence and deobfuscation

The lab reports contain exact instruction addresses, branch values, rejected
candidates, variable aliases and reproducible byte checks:

- [Genius thresholds][genius]: import, constructor, exact target predicate,
  unsigned minimum predicate, candidate iteration and UI acceptance.
- [Metadata subfields][metadata]: version halfwords, rule flags, full sort word,
  attachment ordering and first-byte composition control.
- [Track consumers][track]: two-register value, protected timing identifiers,
  expiry sentinels and the still-unidentified 0x1000 flag.
- [Playlist consumers][playlist]: shuffle restriction, fallback selection and
  bounded negative results for remaining flags/words.
- [Database byte bridge][bridge]: separate raw getters, virtual slots and game
  wrappers with unavailable-handle zero fallback.
- [MHIP control bytes][mhip]: independent unchecked/group bytes, checked-only
  filtering, byte-order behavior and the first-Playlist-dataset import gate.

Twelve qualified function names and variable/member aliases were also applied
to the separate Ghidra research project. Function names are actual annotations;
the variable aliases are plate comments, not claimed recovered source variables.
Signatures were not changed. The annotation transaction reverified unchanged
firmware bytes. See the [name model][names] and its retained application report.

## Validation

Literal binary fixtures exercise the new widths, split fields, noncanonical
bytes, unknown halfwords, short headers, no-op serialization, unrelated edits
and semantic nested/leaf edits. Research scripts separately verify exported
instruction bytes and selected modeled boundary cases; they do not claim to
execute the firmware.

Final integration validation passed `uv lock --check`, Ruff formatting and
linting, Rumdl, Mypy and `git diff --check`. The default eight-worker
`uv run pytest` run, including the MHIP follow-up, finished with
**9,445 passed, 47 skipped and one warning** in 290.52 seconds. The warning is the existing intentionally large photo fixture
triggering Pillow's image-size warning. The wiki build and all 297 field-page
render checks also passed; interactive visual inspection was unavailable because
local browser use is disabled in Work settings.

[genius]: ../../../ipod-firmware-lab/notes/itunesdb/mhbd-genius-thresholds.md
[metadata]: ../../../ipod-firmware-lab/notes/itunesdb/metadata-unknown-field-consumers.md
[track]: ../../../ipod-firmware-lab/notes/itunesdb/track-unknown-field-consumers.md
[playlist]: ../../../ipod-firmware-lab/notes/itunesdb/playlist-unknown-field-consumers.md
[bridge]: ../../../ipod-firmware-lab/notes/itunesdb/database-byte-getter-bridge.md
[mhip]: ../../../ipod-firmware-lab/notes/itunesdb/mhip-control-bytes.md
[names]: ../../../ipod-firmware-lab/notes/itunesdb/classic201-unknown-fields-names.json
