# Legacy Clock Alarm sound selection and native Playlist identity

Research date: 2026-11-13. This follow-up resolves the sound fields and nonzero
Playlist enable path left open by the
[initial legacy investigation](alarms-legacy-firmware-2026-11-13.md).
Mini 1/2 store a persistent Playlist ID in Preferences. Nano 1 and Video store a
native Playlist array index in each saved city clock. These representations are
different and must not share a guessed ID encoder.

The [scheduling and city follow-up](alarm-legacy-scheduling-cities-2026-11-13.md)
adds original Mini 1/Nano 1 scheduling, complete city mappings, Nano 1 creation
defaults and the runtime source of Radio availability.

The qualified new operations are Beep and source-qualified Playlist selection,
and Mini enable changes when the saved nonzero Playlist identity resolves in the
captured native array. Per-city mode 12 is observed Radio, which can be disabled;
new Radio selection remains outside the Host menu because accessory availability
has not been established. No physical device was accessed.

## Exact inputs and independent execution

The original main image identities and runtime maps are retained from the
[first investigation](alarms-legacy-firmware-2026-11-13.md#input-coverage-and-exact-identity).
Every available latest input below was independently loaded and executed. This
is not coverage of every historical firmware release. Nano 2 families 19/29
remain encrypted and are not qualified by similarities with Nano 1.

| Targets | RetailOS | Main image SHA-256 | Cases per input |
| --- | --- | --- | ---: |
| Mini 1, families 3 and 6 | 1.4.1 | `2f844307acf62702fc247b19a148f35d497ce59d6ef7790b242200b5d64b09df` | 10 |
| Mini 2, family 7 | 1.4.1 | `346504450c5201a632cafa38312093fc04b402b4ca37c79d7ca4a4167bb8f34d` | 10 |
| Video, families 13 and 20 | 1.3 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` | 10 |
| Video, family 25 | 1.3 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` | 10 |
| Nano 1, families 14 and 17 | 1.3.1 | `2d34721c1d36f592b076ca111822cea6afcf718331dcf4117618f0eb338bf4cb` | 10 |

The [new probe][probe] passes **80 original-instruction cases**. Its
[receipt][receipt] records the image hashes, input/output vectors, original
native record bytes and every executed instruction with source-byte equality.
Script SHA-256 is
`8ede7fbb918f8a328afbf60fb18ceb45c8048a3d753175705b40a347d4027885`;
receipt SHA-256 is
`715ba9bb96cb5f41ada543775f19d335e5740878e096f2998078c0410419acb2`.
The pinned script uses Unicorn 2.1.4 and Capstone 5.0.7 through UV.

Mini cases execute the original UI sound event, persistent-ID getter, off/on
events and whole-file save. Nano/Video cases execute sound events, original
tagged serialization and reload, off/on events, and bounded native Playlist
array count/fill loops. All inputs also execute dataset-dispatch branch vectors.
Adapters provide memory objects, allocation, stream I/O, city resource lookup,
UI notifications and next-alarm recomputation. Dataset payload importers are
adapted in the dispatch cases. The complete importers and audio hardware are
not executed by this probe; those import-field findings are separately identified
below as static native evidence.

Run in the sibling firmware lab using a new output directory:

```powershell
uv run scripts/probe_legacy_alarm_sounds.py artifacts/alarm-sounds-NEW
```

## Mini 1/2: exact sound and enable transitions

The source is the previously qualified 2,876-byte (`0xB3C`) Preferences file with
LE u32 version `0x16`. Owner addresses are eight bytes greater than file offsets.

| File location | Representation | Sound role |
| --- | --- | --- |
| `0xB18` | LE u16, mask `0x0C` | 0 enabled Beep, 4 enabled Playlist, 8 disabled |
| `0xB24` | LE u64 | Selected Playlist persistent ID; low word first |
| `0xB22` | LE u16, mask `0x0FFF` | Minute-of-day, independently editable |

Mini 1 [sound setter `0xC220C`][mini1-setter] and
[menu `0xC5098`][mini1-menu] handle sound property `0x2822`.
Mini 2 uses setter `0xC250C` and [menu `0xC5230`][mini2-menu].
The event carries a native Playlist array index. Row zero is the Beep resource
`0x2824`; positive rows are Playlists. Choosing any row enables the Alarm Clock:
mode becomes 0 for row zero, otherwise 4, retaining every bit outside `0x0C`.

**Beep selection copies the Master Playlist ID.** It does not necessarily store
zero. The setter copies native Playlist `+0x14/+0x18` into owner
`+0xB2C/+0xB30`. The [Mini 1 MHYP importer][mini1-import] and
[Mini 2 MHYP importer][mini2-import] copy MHYP `+0x1C/+0x20` into those native
fields, proving the LE u64 word order independently of the Host encoder.

The native probe supplies three distinct asymmetric IDs. For Master ID
`0x0102030405060708`, selecting Beep writes `0807060504030201` at file `0xB24`.
Selecting Playlist ID `0x1122334455667788` writes `8877665544332211`; selecting
`0xAABBCCDDEEFF0011` writes `1100FFEEDDCCBBAA`. The entire saved Preferences file
matches its starting bytes except for the ID and the mode mask. Each choice
survives disable and enable through the original menu.

The [Mini 1 lookup `0x666F8`][mini1-lookup] and
[Mini 2 lookup `0x66A44`][mini2-lookup] search the native array by exact persistent
ID, returning the first matching index. All-zero saved ID returns `FFFFFFFF`
without searching; an absent ID also returns `FFFFFFFF`. Enable property
`0x282C` uses a **signed greater-than-zero** comparison: positive lookup gives
mode 4; Master index zero or negative lookup gives mode 0. Disable gives mode 8
without changing the ID. Mode 12 has not been established as a Mini sound choice.

The pure Preferences API therefore accepts paired `sound_playlist_id` and
`sound_playlist_index`: index zero with the captured Master ID for Beep, or a
positive index with that row's ID for Playlist. Selection occurs first and
explicit `enabled` intent applies last, allowing sound changes while leaving an
alarm disabled. Enabling an existing nonzero ID requires a separate qualified
`playlist_index`; disabling does not. A zero saved ID requires no Library lookup.
The Application Layer binds these inputs to the retained Library source.

## Nano 1 and Video: active mode and retained sound are separate

These families persist each city in `iPod_Control/Device/clock`, using the
[tagged framing already qualified](alarms-legacy-firmware-2026-11-13.md#video-and-nano-1-a-persistent-alarm-per-city-clock).
There is no alignment padding. The following are tag meanings, not fixed file
offsets:

| Alarm child tag | Native city offset | Meaning |
| --- | --- | --- |
| 6 | `+0x10` | Minute-of-day |
| 7 | `+0x14` | Active kind: 0 Beep, 4 Playlist, 8 off, 12 Radio |
| `0x1F` | `+0x18` | Retained sound mode: 0 Beep, 4 Playlist, 12 Radio |
| 8 | `+0x1C` | Native Playlist index, or `FFFFFFFF` for Beep/Radio |

The [Nano 1 setter `0x1909C0`][nano-setter] and
[Video setter `0x237A40`][video-setter] write all three sound/control fields:
chosen mode into `+0x18`, index into `+0x1C`, and the same mode into `+0x14`.
They request the native projection refresh and mark the collection dirty.
Nano 1 getters `0x191970/0x1919B4` read the retained mode/index; disabling does
not erase the sound displayed by that getter.

The [Nano 1 menu `0xED5D4`][nano-menu] handles property `0x60C9`; the
[Video menu `0x1919D8`][video-menu] handles `0x6098`:

| Menu state and row | Active kind | Retained sound | Index |
| --- | ---: | ---: | --- |
| Row zero | 0 | 0 | `FFFFFFFF` |
| Positive row, no Radio row | 4 | 4 | Row number |
| Radio available, row one | 12 | 12 | `FFFFFFFF` |
| Radio available, row two or later | 4 | 4 | Row number minus one |

The Radio-available byte is UI `+0x94`. The probe supplies this byte to exercise
the branch; it does not prove the accessory's physical presence or playback.
Nano 1 resource `0x60CB` says Beep and `0x5872` says Radio, reached by sound-label
getter `0xEED8C`. The original city serializers and loaders preserve all three
fields in every sound vector, including Radio.

Original toggles Nano 1 `0x191714` and Video `0x238A20` set any enabled canonical
kind to 8. From 8 they set kind 4 only when tag 8 is a positive signed i32;
otherwise kind becomes 0. **The retained sound mode is unchanged.** Thus a Radio
record `(12,12,FFFFFFFF)` becomes `(8,12,FFFFFFFF)` when disabled and
`(0,12,FFFFFFFF)` when enabled again. This is an observed native transition,
not a reason to overwrite the retained Radio field. Beep and Playlist records
restore their expected active modes through the same rule.

`update_clock_alarm(..., sound_playlist_index=-1)` selects Beep; a positive
qualified native index selects Playlist. It writes tags 7, `0x1F` and 8 together.
Explicit `enabled` applies afterward. Radio is readable and can be toggled; it
cannot be newly selected through this Host API. Unknown active kinds retain their
bytes until an explicit qualified sound selection replaces them; an ordinary
enabled edit does not guess an unknown kind.

## Which Playlist does the index identify?

### Dataset selection and source order

The whole-file importers Mini 1 [`0xB095C`][mini1-datasets],
Mini 2 [`0xB0C70`][mini2-datasets], Nano 1 [`0x319F4`][nano-datasets] and
Video [`0xAF930`][video-datasets] accept **the first encountered MHSD type 2 or
3** and skip subsequent 2/3 datasets. There is no unconditional type-3 priority.
Original branch probes cover orders `(1,2,3)`, `(1,3,2)`, `(2,1,3)` and `(4,3,2,1)`
on every input. Type-1 Track datasets are imported as encountered; an unresolved
Track reference in an earlier Playlist is not retrospectively repaired.

Static constructor/append evidence preserves MHYP import order: Mini 1
`0x486B4 -> 0xD2F10 -> 0x3246C` and Nano 1
`0x1B1FC -> 0x37CCC -> 0x10AAC` append to the list tail. Their array builders
iterate that list. A Master flag does not independently move a late row to zero.
Host sound choices therefore require one Master Playlist at native index zero.

### Imported array filters

The [Mini 1 loader `0xCBE7C`][mini1-array] excludes internal native flag `0x40`
and podcast flag `0x80` in the following byte. Imported ordinary Playlists are
included even when empty. MHYP byte `+0x2A` bit zero becomes the podcast flag.
Later folder flag `0x0100` and parent-Playlist ID do not create a legacy Playlist
tree or reorder this array. Generated New Voice Memos receives internal `0x40`
and is excluded.

The [Nano 1 builder `0x363BC`][nano-array] and
[Video builder `0xB4A64`][video-array] use the same imported-order filter:

1. Exclude internal `native +0xEC & 0x40` and podcast `+0xED & 0x80`.
2. Include Master `+0xEC & 0x20`, regardless of member count.
3. Include Smart `+0x10C & 1`, regardless of member count or media flags.
4. Otherwise require nonzero native u16 root Track-member count and a media OR
   which is zero or intersects `0x12D`.

The independent array probe supplies Master, audio, empty, video-only, podcast,
empty Smart, video Smart, media-zero and internal candidates. Original count and
fill loops select source ordinals **`[0,1,5,6,7]`** on every Nano 1/Video input.
The standalone Host fixture reproduces those imported candidates and indices.

Static [Nano 1 MHYP import][nano-import] sets Smart for successfully imported
MHOD 50 or 51. [Nano 1 Track import][nano-tracks] accepts MHIT record class 1;
[Video Track import][video-tracks] accepts classes 1, 2 and 3. Other classes are
skipped. These class differences require separate `CLOCK` and `VIDEO` layouts.
Native Track `+0xB6` receives MHIT media-type `+0xD0` truncated to u16; each added
Track ORs that value into native Playlist `+0x108`.

MHIP group byte `+0x11` distinguishes groups from Track occurrences. Group ID
is `+0x14`, Track ID `+0x18`, parent-group ID `+0x20`. Parent zero selects root;
nonzero parents must already exist when the row is imported. Unresolved groups
or Track IDs cause that occurrence to be skipped. Group creation alone adds no
Track count. Nested successful Track occurrences increment the root count,
including duplicates, with native u16 wrap. These rules follow importer
`0x4EF80`, recursive lookup `0x783D0`, Track insertion `0x10538` and ancestor-count
update `0x4E900` on Nano 1. Ambiguous duplicate/zero group IDs are conservatively
unqualified in the Host projection.

### Runtime additions and Sync

The qualified Host projection is the **imported database prefix**. Firmware can
append runtime/generated collections afterward. Sound-menu counts subtract
special collections using native `+0x128` on Mini and `+0x16C` on Nano 1/Video;
this does not change indices of the earlier captured source rows. A saved
nonzero Mini ID absent from the captured catalog is consequently not proof that
the runtime getter returns -1. The application must leave that enable lookup
unqualified, or let an explicit source sound selection replace it.

Nano 1/Video tag 8 is an ordinal, not a persistent identity. A Sync that reorders
Playlists, changes their membership/media eligibility, or changes which dataset
is first can make the same saved index target another Playlist. Resolving the
current captured ID/name before editing is necessary. Preserving that association
across a later Library change requires comparing old/new native catalogs and
coordinating dependent clock edits in the same publication workflow; it cannot
be achieved by pretending that tag 8 is a persistent ID. This research does not
independently qualify every generated runtime collection or a live-device Sync
acceptance scenario.

The initial implementation included a Clock index remapper and a Mini selected-ID
deletion check. Both were subsequently removed by explicit user direction in
[ADR-0262](../adr/0262-leave-alarm-selections-unchanged-during-library-writes.md).
Library saves now leave Alarm bytes unchanged and accept the native result of
changed positions or deleted Playlists. The source projection remains necessary
for displaying and explicitly selecting an Alarm sound, independently of Sync.

## Implementation and validation boundary

[Alarm Playlist projection](../../src/iPodDB/library/alarm_playlists.py) exposes
`AlarmPlaylistLayout.MINI/CLOCK/VIDEO`, immutable `AlarmPlaylist` rows and an
`AlarmPlaylistCatalog` with `complete` and `issues`.
`IPodLibrary.alarm_playlists(layout)` uses its retained Chunk tree, preserving
dataset and record order. It consumes shared Chunk field definitions and
distinguishes captured short headers from authoring defaults. Duplicate IDs,
missing/late Master, unsupported relevant structures and ambiguous group
identities prevent qualified choices; no partial array is silently treated as
complete.

[Clock sound edits](../../src/iPodDB/alarms/clock.py) retain all unrelated source
bytes, patch only complete unique tagged fields, reject incoherent mode/index
pairs and retain unknown fields. The [standalone Clock tests][clock-tests] cover
sound plus explicit disabled intent, Radio off/on, reselecting the same sound,
unknown-kind repair by explicit sound selection and rejected invalid indices.
The [native-array fixture tests][catalog-tests] cover dataset order, both Track
class policies, empty/Smart/podcast/video filters, Master identity, unresolved
Tracks, prior-parent groups and duplicate identities. They require neither the
firmware lab nor a connected device.

The initial handoff's 79-case Clock/catalog suite included nine remapping cases.
Those cases were removed with the remapper under ADR-0262; replacement application
tests verify that selected-Playlist deletion succeeds while leaving Alarm files
unchanged, including changed or malformed Alarm files after Review.

These results prove captured-file transformations and bounded native behavior.
They do not prove physical sound output, accessory Radio reception, wake from
every power state, city creation/deletion defaults, or immediate adoption by
firmware already running while the Host replaces its files.

[probe]: ../../../ipod-firmware-lab/scripts/probe_legacy_alarm_sounds.py
[receipt]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-legacy-20261113-v6/receipt.json
[mini1-setter]: ../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000c220c.c
[mini1-menu]: ../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000c5098.c
[mini2-menu]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000c5230.c
[mini1-lookup]: ../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000666f8.c
[mini2-lookup]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00066a44.c
[mini1-import]: ../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000af598.c
[mini2-import]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000af8ac.c
[mini1-datasets]: ../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000b095c.c
[mini2-datasets]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000b0c70.c
[mini1-array]: ../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000cbe7c.c
[nano-setter]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/001909c0.c
[nano-menu]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000ed5d4.c
[nano-datasets]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000319f4.c
[nano-array]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000363bc.c
[nano-import]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/0004ef80.c
[nano-tracks]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/0004f948.c
[video-setter]: ../../../ipod-firmware-lab/artifacts/preferences-video-clock-export-20261107-v1/00237a40.c
[video-menu]: ../../../ipod-firmware-lab/artifacts/preferences-video-menu-20261107-export-v1/001919d8.c
[video-array]: ../../../ipod-firmware-lab/artifacts/preferences-video-owner-export-20261107-v1/000b4a64.c
[video-datasets]: ../../../ipod-firmware-lab/artifacts/eq-nano-video-20261106/video13-deep/000af930.c
[video-tracks]: ../../../ipod-firmware-lab/artifacts/eq-nano-video-20261106/video13-deep/000d7888.c
[clock-tests]: ../../tests/iPodDB/test_clock_alarms.py
[catalog-tests]: ../../tests/iPodDB/library/test_alarm_playlists.py
