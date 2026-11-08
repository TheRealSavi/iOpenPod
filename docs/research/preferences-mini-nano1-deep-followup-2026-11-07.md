# Mini 1, Mini 2 and Nano 1: retained state and remaining consumers

Research date: 2026-11-07. This is a substantive follow-up to the
[whole-file inventory](preferences-mini-nano1-complete-2026-11-07.md), **not an
exhaustive Preferences decoder**. It resolves several domains and distinguishes
current settings, migration inputs, runtime objects and retained bytes. The
large leading gaps remain explicit. No physical device access or application
writing behavior was added. Datetime interpretation remains non-blocking.

## Exact inputs and reproducibility

| Model | Updater | Latest release | Preferences size | OSOS SHA-256 |
| --- | --- | --- | --- | --- |
| Mini 1 | 3 and 6, independently loaded | 1.4.1 | `0xB3C` | `2f844307acf62702fc247b19a148f35d497ce59d6ef7790b242200b5d64b09df` |
| Mini 2 | 7 | 1.4.1 | `0xB3C` | `346504450c5201a632cafa38312093fc04b402b4ca37c79d7ca4a4167bb8f34d` |
| Nano 1 | 14 and 17, independently loaded | 1.3.1 | `0xB64` | `2d34721c1d36f592b076ca111822cea6afcf718331dcf4117618f0eb338bf4cb` |

From the sibling firmware lab:

```powershell
uv run scripts/research_preferences_mini_nano1_deep_followup.py --output artifacts/NEW-directory
```

The [new probe](../../../ipod-firmware-lab/scripts/research_preferences_mini_nano1_deep_followup.py)
refuses an existing output directory. The
[final summary](../../../ipod-firmware-lab/artifacts/preferences-mini-nano1-deep-20261107-final/summary.json)
records **12,831 passing native cases**: 2,317 for each Mini input and 2,940 for
each Nano input. Each target receipt includes source identity, initialized memory
map hashes, original executed instruction addresses/hashes, adapter addresses,
static source hashes and cases. The
[updated full inventory](../../../ipod-firmware-lab/artifacts/preferences-mini-nano1-deep-20261107-final/field-inventory.json)
retains the prior inventory provenance and replaces neither its receipt nor its
files. Earlier `pass1` through `pass4` directories are development receipts;
`final` is the completed checkpoint.

The native environment is Unicorn 2.1.4 with the existing independently pinned
loaders. Files, allocation, UI notifications, resource lookup, string-pool lookup,
playlist identity lookup and hardware/service effects have explicit synthetic
boundaries. The code does not boot a complete operating system. Counts include
exhaustive byte-domain sweeps; they do not measure firmware path coverage.

All offsets below are file-relative. The in-memory payload begins at owner `+8`.
Multi-byte fields are little-endian.

## Leading retained bytes and migration

The current loader was given a deterministic nonzero pattern across the entire
file, with the current version and reset request zero. On **every exact input**,
only `0x91`, `0xB0A` and `0xB0B` changed: all became `1`. Every other byte survived.
A following complete original serializer reproduced this loaded pattern exactly
when its live volume/EQ overlays were explicitly seeded from the payload and
its EQ-text replacement flag was clear.

These are bounded loader/serializer observations, not evidence that the leading
ranges are unused. Per-PC memory access receipts distinguish scalar loader
accesses from bulk copy/default clearing. The synthetic file read copies its
bytes at the documented boundary; live-player seeding is explicit and is not
claimed as a native player-constructor test.

Two previously unmapped ranges now have narrower classifications:

| Offset | Representation/default | Current behavior |
| --- | --- | --- |
| `0x10..0x14` | u32, zero after defaults | Legacy volume migration source. The latest loader copies it to volume `0x08` only when the input version is below 7; it retains the source word. Versions 5/6 versus 7/current were tested independently. This is current firmware reading old-format input, not old firmware research. |
| `0x8E2..0x8E4` | Two bytes, zero after defaults | Playback callers pass them as two arguments to a decoder status routine. Their original meanings remain unknown. The identified current consumer ignores both arguments completely. |

The ignored-argument routines are Mini 1 `D5180`, Mini 2 `D5318`, Nano 1 `66674`.
Each has six original instructions: read the decoder header, replace incoming
`r1` with a magic constant, compare, return `-4` for a matching header or `-50`
otherwise. Incoming `r2` is never read. There are 1,536 cases per target covering
each byte value independently and complementary pairs under both header states.
There are no writes. This proves lack of effect **at this consumer**, not absence
of other indirect uses or the historical purpose of those two bytes.

Mini 1 callers include `A19D0`, `A1A94`, `A26AC`, `A2B8C`, `A3F5C`, `C3450`;
Mini 2 has independent corresponding code; Nano callers include `2E420`,
`2E4C0`, `2EB8C`, `2F464`, `34E58`, `34E80`, `5DB9C`. The exact call edges are in
the target receipts. These offsets are **not** the EQ count at file `0x8EA`.

The apparent large buffers in Mini `B28C4` remain excluded: its object has not
been tied to the Preferences owner. Playback state, Play Counts and On-The-Go
records also have separate owners/writers; matching numeric offsets alone cannot
turn them into leading Preferences structures.

## Artist prefix sorting: the forced `0xB0B` flag

This byte controls use of a generated alternate **artist** sort string. It is
not an encoding selector. It defaults to `1` and every current load forces `1`.

| Model | Selection getter | Primary/alternate record slots | Primary/alternate string pools | MHOD parser and generation chain |
| --- | --- | --- | --- | --- |
| Mini 1 | `74990` | `+28` / `+2C` | `+DC` / `+108` | `AFF90`, MHOD type 4 → `3C500` → `DB634` → `3D998` |
| Mini 2 | `74CC4` | `+28` / `+2C` | `+DC` / `+108` | `B02A4`, MHOD type 4 → `3C958` → `DB794` → `3DDF0` |
| Nano 1 | `243F8` | `+2C` / `+30` | `+E0` / `+10C` | `4F948`, MHOD type 4 → `17D50` → `7A7A4` → `182E4` |

The exact parser branches bind this to MHOD type 4, the shared
[`ARTIST` definition](../../src/iPodDB/iTunesDB/shared/constants.py). These parser
and generation chains are static original-firmware evidence; the selection
getters are executed for all 256 flag bytes with and without an alternate key,
512 cases per target:

- `0`: use the original artist string.
- `1..255`: use the generated alternate when present; otherwise use the original.
- The getter converts the pool's byte length to UTF-16 code-unit length.

Mini `3D998` compares bounded counted UTF-16 prefixes and substitutes the matched
prefix with its table replacement. The prefix table, its count and alternate
string pool are runtime data. Mini owner `+B58/+B5C`, for example, lie beyond
the serialized extent. This pass does not claim the full multilingual prefix
grammar is a preference or enumerate every collation rule. No normal UI toggle
for the forced byte was found; authoring it would be undone on the next load.

## Week-start field `0xB20`

The u8 default is `0`. Independently executed label callbacks on all inputs give
the exact mapping: **0 Sunday, 1 Monday, 2 Tuesday, 3 Wednesday, 4 Thursday,
5 Friday, 6 Saturday**. Mini 1 `6BE8C`, Mini 2 `6C1D8` and Nano `EED8C` request
resource `0x99 + value` and copy the actual English resource text.

All 256 byte values pass through the original Settings callback and complete
serializer without normalization; every other file byte is preserved. The
calendar header renders `(stored + column) % 7` in Mini 1 `59DAC`, Mini 2 `5A0F8`
and Nano `C6C28`. Therefore a raw value outside `0..6` is retained and participates
in modulo-seven rendering, rather than being a new weekday enum. The current
native setting callback also notifies observers of property `2832` on Mini or
`60DB` on Nano.

Matching `Strt` view records contain bounds 0/6 (Mini key `FFFFFF13`, Nano
`FFFFFEA4`). The seven label choices and renderer semantics are established;
reachability of this control from each current normal menu is still unproved.
This is sufficient to document interpretation, not to enable new host writes or
reject unusual values while loading a device.

## Nano slideshow music `0xB3F` and playlist identity `0xB40..0xB48`

The default is mode `1`, identity zero. The original selector `CE124`, compound
commit `EEBD0`, resolver `CD388` and complete Preferences serializer were tested
with and without the iPhoto provider and with persistent and zero-ID playlist
records. Resource-label callback `CEA74` supplies the three fixed labels.

| Mode | Meaning | Identity and resolution |
| --- | --- | --- |
| `0` | From iPhoto | Offered only when the photo provider's `+4C` word is 1. Selection clears the saved identity. If unavailable during resolution, saved mode becomes `1`. |
| `1` | Off | Selection clears the identity. The slideshow startup consumer does not select a music playlist. |
| `2` | A named persistent playlist | Selection stores its nonzero 64-bit identity. Resolution finds that identity in the current playlist collection. A missing identity changes saved mode to `1` but **retains the stale identity bytes**. |
| `3` | Temporary/zero-ID playlist | Selection clears the identity. A non-final zero-ID row is remembered only in the slideshow UI's signed 16-bit `+82` field. If that row is unavailable, resolution uses the final playlist row. Selecting that final row stores transient `-1`. The dynamic row label comes from the playlist, not a fixed mode label. |
| `4` | Now Playing | Selection clears the identity; `CCB5C` returns immediately, preserving current playback. |

The master playlist row shares the Off position and is not offered as a named
music choice. A synthetic four-record collection exercised persistent playlist
index 1, an intermediate zero-ID playlist and the final playlist separately.
The identity provider is an explicit lookup adapter; original `21E80`, `22D6C`,
selector and resolver instructions execute around it.

Every stored mode byte was also tested under both provider states. Bytes
`5..255` go through the resolver's default branch, return row zero and leave the
stored mode/identity unchanged. Do not rewrite every unknown mode to Off. The
unavailable-iPhoto fallback also retains any existing identity bytes, whereas
an explicit user selection clears them.

## Nano volume and brightness

`0xB50` is a u32 volume-limit percentage, default `100`. Setter `35B58` stores a
whole word without clamping. Original consumer `22558` computes:

```text
if runtime owner+BEB == 0: maximum = regional_maximum
else: maximum = floor(((max(10, saved_limit) * regional_maximum) mod 2^32) / 100)
```

The regional maximum is 216 or 256, selected outside the file. The 48-case probe
includes both maxima, both runtime-enabled states, values below the floor, 100,
above 100 and `FFFFFFFF`. It verifies that consumption does not normalize the
saved word. Player `7D504` clamps its live volume against this result; the
serializer persists that live volume separately at `0x08`. Sensible offered
percentages, the actual limit editor and PIN lifecycle still need qualification.
Raw representability is not a reason to author values above 100.

`0xB54` has default `100` and getter `205B4`. However the actual property `6054`
Settings callback updates UI values and calls hardware service `D75A8` with
unsigned `max(4, input)`. It does **not** update this saved byte. Ten inputs,
including values above 100, were passed through that callback and the complete
serializer; the **entire Preferences file remained unchanged**. The separate
saved-field writer, if any, and current menu reachability remain open. This
callback alone cannot qualify persistent host brightness editing.

## Nano hidden booleans and Nike receiver latch

`0xB4C`, default `1`, property `60E9`, is a service switch. On a changed raw value,
`34BBC` obtains manager `118F70`: zero calls `118DB8(manager, 1)`; nonzero calls
`118C54(manager)`. It then saves the low byte and marks Preferences dirty.
The manager iterates registered participants, calls their virtual operations,
changes an aggregate resource pool and updates its state. Cross-family research
found the analogous native class name `TTrackExtrasCache`; that name was **not**
found independently in the Nano ASCII or defined-string corpus. Track-extras
caching is a strong follow-up lead, not yet a fully qualified Nano effect model.
Nearby Large Album Art does not prove this switch is only an artwork toggle.

The raw setter tests the full u32 before truncating: an input of 256 takes the
enable path but stores zero. Native/UI booleans and raw argument bit patterns
therefore must not be conflated. The probe covers unchanged/changed states and
boundary values while recording service-boundary calls.

`0xB4D`, default `1`, property `60EB`, has a simpler `35B28` setter: store the low
byte and mark dirty. The Settings cache holds it at UI `+81` and announces its
property. Its final subscribers, name and user effect remain unresolved.

`0xB60` is now a qualified **Nike receiver-seen latch**, default `0`:

- `A4D4C` reports availability when either the saved byte is nonzero or the live
  receiver query succeeds.
- `A5610` stores `1` if its explicit availability argument, the saved latch or
  the live receiver says available; a disconnect does not clear an old `1`.
- Nonzero raw bytes such as 2/255 are truthy and normalize to `1` through this
  update. Full defaults clear it to `0`.

The 16-case truth table runs those original routines and complete serialization.
Live receiver objects and notification state are outside the file. A normal
clear action other than resetting defaults was not identified. The earlier
distance-unit, spoken-feedback, remote-command and PowerSong mappings stand;
this pass does not claim all workout-state transitions have been emulated.

## Measured coverage and remaining work

| Model/input | File bytes | Individually identified | Resolved stated representation/meaning | Unmapped | Unresolved including partial fields |
| --- | ---: | ---: | ---: | ---: | ---: |
| Mini 1/3, Mini 1/6, Mini 2/7, each | 2,876 | 604 | 551 | 2,272 | 2,325 |
| Nano 1/14, Nano 1/17, each | 2,916 | 643 | 574 | 2,273 | 2,342 |

“Resolved” concerns the stated field interpretation, not permission to edit or
proof of all surrounding UI paths. No bytes are classified as padding. Counts
include the previously understood EQ text buffer and do not count every byte
as a separate preference. Whole-file persistence coverage is distinct from
semantic coverage. The JSON retains exact end-exclusive unresolved intervals.

Common unmapped intervals after this pass:

```text
[019,08A) [08B,091) [092,8E0) [8E1,8E2) [8E4,8EA)
[AEA,AEC) [B01,B02) [B09,B0A) [B0E,B10) [B17,B18)
[B1A,B1C) [B21,B22) [B31,B38)
Mini additionally: [B39,B3C)
Nano additionally: [B4F,B50) [B61,B64)
```

The two decoder-option bytes are identified but remain semantically partial.
Other partial fields are also included in the JSON's larger unresolved union.
Next questions, with concrete entrypoints:

1. **All three models:** finish owner/payload pointer-escape and indirect consumer
   closure for the large leading ranges. Defaults zeroing and unchanged copy
   behavior cannot establish padding. Determine whether any undetected current
   path consumes them.
2. **All three models:** finish the separate forced flag `0x91` media-buffer path
   (Mini `84C54/A327C`, Nano `259EC/5DD88`) and forced `0xB0A`. Do not merge these
   with the newly bound artist-sort flag or the Nano extras-cache candidate.
3. **Mini 1/2:** resolve `B00` reset/setup role, legacy font `B02`, word `B04`,
   standalone `B08/B30` setters (Mini 1 `C21E0/C3350`), remaining alarm flag/time
   grammar, physical contrast behavior and the second volume argument. No direct
   caller found in this pass is not proof a setter is globally unreachable.
4. **Nano 1:** trace registered participants of `118F70/118C54/118DB8`, actual
   subscribers of `60EB`, the volume/PIN editor, any brightness writer, and the
   remaining transition IDs/backlight-policy conditions. The default `B4C/B4D`
   values and byte setters do not identify user-facing meanings by themselves.
5. **All inputs:** establish normal-menu reachability versus inherited/hidden
   property support. Keep invalid or unfamiliar datetime/preferences values as
   preserved Unknown Data; these research gaps must not block loading the iPod.

Validation: the final pinned probe passed all 12,831 cases; the new script passes
Ruff formatting and lint checks. The application codec, Registry and writer
allowlists were not changed by this research checkpoint.
