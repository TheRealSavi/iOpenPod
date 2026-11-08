# Nano 5, 6, 7 and refresh Preferences inventory

This pass inventories **52 Nano 5 named entries, 89 ordinary Nano 6 entries plus
four entries in a separate timer store, and 102 ordinary entries on each Nano 7
release**. These are independently captured registration contracts, not a claim
that every preference's effect is understood. The binary Preferences payload and
several named enum/UI contracts remain incompletely understood. Unknown Data must
remain preserved; discovering a firmware fallback does not authorize replacing
an unknown value with that fallback.

The primary sources are the exact latest firmware images and original machine
instructions. Ghidra pseudocode is a navigation aid; native probes corroborate
registration arguments, scalar setters, providers, UI cycles and EQ conversion.
There was no physical device I/O in this pass.

## Reproducible evidence

All paths below are relative to the sibling `ipod-firmware-lab` repository.

| Target | Latest release | Original source | SHA-256 |
| --- | --- | --- | --- |
| Nano 5 / updater 34 | 1.0.2 | `Nano5FW/firmware/decrypted/osos.raw.bin` | `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49` |
| Nano 6 / updater 36 | 1.2 | `Nano6FW/decrypted/osos.bin` | `d529680b7e7662876543d70b6941ddfac123d96c8ed1923432e4909909e896d8` |
| Nano 7 / updater 37 | 1.0.4 | `Nano7FW/decrypted/osos.bin` | `4a55fffbf58cfd04a393e9a40c0c1c42471dfb34d11847b676b85f02a8019999` |
| Nano 7 refresh / updater 39 | 1.1.2 | `Nano75FW/decrypted/osos.bin` | `ac4cf072d3c3f971b6acc03ed4f2ad1baa57d7bae20f89692bd6fb08d8a749e4` |

Nano 5's main block is source offset `0x2E27C`, length `0x6C43A8`, mapped at
`0x08000000`. The later main blocks start at source offset zero and have lengths
`0x88D9C0`, `0x970380`, and `0x970740`, respectively. Every image is checked
against its original hash before execution. The probes instantiate copies in
Unicorn memory, with synthetic construction, settings, lock, event, playback and
filesystem boundaries. Originals are not modified.

Authoritative new artifacts:

- `scripts/inventory_nano567_preferences.py` and
  `artifacts/nano567-preferences-complete-20261107-final-capture/discovery.json`:
  raw native constructor argument captures, candidate failures and key strings.
- `scripts/probe_nano567_preference_domains.py` and
  `artifacts/nano567-preferences-complete-20261107-final-inventory-v3/`:
  corrected `inventory.json`, `scalar-cases.json`, and `receipt.json`.
- `scripts/probe_nano567_ui_preferences.py` and
  `artifacts/nano567-preferences-complete-20261107-final-ui/`:
  `ui-cases.json` and `receipt.json`, including original Unicode comparison.

The corrected inventory is the consumable catalog. Earlier discovery captures
retain raw register observations for auditing. In particular, Nano 5's older
registration ABI does **not** provide the later trailing callback parameter:
values such as `0x10003061` in raw captures are synthetic dispatch addresses,
not firmware flags. The corrected catalog makes that argument null on Nano 5.
Later targets have a callback/hook argument, not a flags bitmask. For example,
UIRotation supplies a non-null callback. Its persistence-side invocation still
requires care before adding host authoring.

Validation in this pass comprises 1,274 native scalar cases, 353 native UI/EQ
cases, 51 native provider cases, and four binary initializer executions. These
are offline instruction tests; they do not prove live USB reload behavior or
audible/visible hardware results. Each receipt pins its script/results and each
executed provider/UI body has its own hash.

## Stores and registration coverage

The ordinary named file is `iPod_Control/Device/iPodSettings.xml`. The first dot
in a setting name separates the XML group from its child. The root is
`iPodSettings`, with version `1.0`; namespaces in the catalog are literal key
prefixes, not XML namespace declarations.

Nano 6 additionally creates `iPodTimerSettings` through `0819EBFC → 081CEB58 →
080C6B7C`. Its loader `08083488` and saver `081DAE64` compose `%s%s.xml` under
`iPod_Control/Device/`, using that owner's root name. The actual separate path is
**`iPod_Control/Device/iPodTimerSettings.xml`**. Its four entries are
`Settings.SoftwareVersion`, `Timer.DateTime`, `Timer.SleepiPod`, and
`Timer.SoundIndex`. `Timer.Hours` and `Timer.Minutes` remain ordinary settings.

Nano 7 `081E3E84` and refresh `081E3E9C` instead register the three timer keys on
the ordinary settings singleton. Their timer values therefore belong in
`iPodSettings.xml`. Never transplant the Nano 6 file placement into Nano 7.

The ordinary Nano 7 and refresh catalogs have identical captured key sets,
types, numeric bounds and defaults after provider-derived defaults are kept
symbolic. They were captured from separate binaries. This establishes equality
of these captured schema contracts, not equality of all callbacks, hardware
effects, UI eligibility or unresolved provider predicates.

Discovery audited direct callers of both singleton wrappers and their real
implementations, plus the known separate timer factory. Nano 5 uses a bounded
nearest-push/return candidate heuristic because no complete function corpus is
available. It can miss split functions and helper-mediated registrations.
Indirect owners, dynamically formed keys and further factory callers are not
closed. Constructor errors after successful captures are retained in the
inventory rather than silently presented as complete constructor runs.

The static reference index covers 254 Nano 6 singleton-calling functions and
303 functions per Nano 7 release. It finds candidate references for 84, 98 and
98 distinct registered keys respectively. A reference candidate is not proof
of the setting's effect: constructor, notification, getter and writer uses must
still be separated. Nano 5 does not claim this reference coverage.

Unregistered but relevant strings remain explicit leads:

- Nano 5 `Radio.LivePause`, string `0853D3DE`, pointer slot `08553818`, has
  getters/toggle consumers at `0828759C` and `08081ED8`; a registration was not
  recovered. Do not silently alias it to the later `General.RadioLivePause`.
- Nano 6 retains `Video.TvAlternateAudio`, `Video.TvSubtitles` and
  `Video.TvCaptions` strings, but its captured video constructor registers only
  four video keys. String presence is not hardware video support.

## Accepted values versus UI values

The catalog records the actual registered type and bounds. Scalar tests execute
the original setter with each exact field name, endpoint, out-of-range values,
and representative signed values. Native int32 values outside a registered range
leave the old value intact but can still mark the settings owner dirty. The
setter returns success for a known key even when its candidate value was outside
the range. Dirty state is therefore not proof that the candidate was accepted.
Notifications occur only when the saved value changes in the covered paths.

Native boolean setters retain an input byte, including tested `2` and `255`;
they are not a two-value validator. UI booleans and host-authored XML should use
canonical `0`/`1`. Previously qualified XML conversion also accepts numeric
prefixes such as `-1`, while leading whitespace changes boolean parsing. Preserve
unmodified original text and use the established scalar codec for edits.

The native int32 accepted domain is not its XML lexical domain. For example,
Nano 7's inline XML int32 parser skips space/tab/newline and parses a decimal
prefix, but a leading minus does not parse as a signed negative number. The
serializer's `%lu` spelling can round-trip negative bit patterns as large
unsigned decimal values. This is especially relevant to backlight sentinels.
Do not expose a generic signed-decimal XML editor from registration bounds alone.

Registration provides no finite string enum for `General.Language`,
`Accessibility.SpeechLocale`, or other string fields. A default string is not a
complete accepted vocabulary. The verified enum consumers below narrow specific
UI domains without treating all other stored strings as errors.

### Repeat, Shuffle and Clicker

All four native UI cycles are independently verified:

| Key | Canonical UI values and effect | UI cycle |
| --- | --- | --- |
| `Playback.Repeat` | `off`: no repeat; `one`: current item; `all`: current sequence | `off → all → one → off` |
| `Playback.Shuffle` | `off`: normal ordering; `songs`: shuffle songs; `albums`: shuffle albums | `off → songs → albums → off` |
| `General.Clicker` | `on`: click feedback permitted; `off`: disabled | Nano 5: `on → off`, every other tested non-null string → `on` |

Comparisons are case-sensitive. Native comparison and UTF-8 character decoding
execute in the UI probes. No case-folding or alternate spelling is qualified.
For example, `OFF` is an unknown spelling rather than an alias for `off`.

Runtime enum readers expose an important difference:

| Reader | Nano 5 | Nano 6 | Nano 7 / refresh |
| --- | --- | --- | --- |
| Repeat recognized values | `off=0`, `one=1`, `all=2` | Same | Same |
| Shuffle recognized values | `off=0`, `songs=1`, `albums=2` | Same | Same |
| Other/empty string in covered reader | `0` | `2` | `0` |

Nano 6's `080868A0` and `080868E4` test the first two spellings and use the third
enum value for everything else. Nano 5 readers are `0825FDD8`/`0820D3D8`; Nano 7
readers are `0849F5A0`/`0813F61C`, and refresh uses
`0849F5A0`/`0813F620`. This difference must remain documented even if the host
only writes canonical values. An unknown source value stays unknown in iOpenPod;
the fallback must not become a normalization rule.

Later Clicker consumers gate audio using `on`, and recording paths temporarily
replace `on` with `off`, remember whether that happened, and restore it. Nano 6
anchors include `0823A5FC`, `081BEA50`, and `08193E70`; Nano 7 includes
`083FAAC0` (tail `084A70CC`), `083EE3D0`, and `083EE520`, with separately shifted
refresh counterparts. Hardware routing, headset state and accessibility behavior
still affect whether an enabled click is actually audible. Do not assign the
binary Clicker route-bit encoding to these named strings.

### Equalizer

All four original UI conversion functions map selection index `0..22` to stored
ID `0,100..121`. Out-of-range selection indices map to `0`. The reverse mapping
returns selection index zero for an unrecognized stored ID. This is a UI
fallback, **not proof that an unknown stored ID sounds like Off**.

| Target | UI index → stored ID | Stored ID → UI index | 23-entry table |
| --- | --- | --- | --- |
| Nano 5 | `0825C298` | `081A3F44` | `08430CB4` |
| Nano 6 | `081E7C64` | `081EBB14` | `0859029C` |
| Nano 7 | `0813F45C` | `0816F6AC` | `0875943C` |
| Refresh | `0813F460` | `0816F6B0` | `087594AC` |

Nano 7's audio-name table at `08811364` contains `Disabled`, `Acoustic`,
`BassBooster`, `BassReducer`, `Classical`, `Dance`, `Deep`, `Electronic`, `Flat`,
`HipHop`, `Jazz`, `Latin`, `Loudness`, `Lounge`, `Piano`, `Pop`, `RandB`, `Rock`,
`SmallSpeakers`, `SpokenWord`, `TrebleBooster`, `TrebleReducer`, `VocalBooster`.
Its English UI strings at `0887F620` begin Off, Acoustic, Bass Booster, and so on.
The matching order is a strong label correspondence, but the complete numeric
ID-to-DSP-filter path and each device's label table still need qualification
before this becomes a fully proved cross-device preset-effect catalog.

In Nano 7, `082882D4` reads `Playback.EQ` and passes its low byte to the audio
interface. Vtable thunk `084B67CC` reaches `081F8EC4`, which stores the byte at
playback-owner `+0x89`. That path does not validate the 23 UI IDs. Keep the
source ID exactly, including values outside the known UI list. Nano 7 additionally
registers `Playback.HeadsetEQ`; interaction with preset EQ remains open.

### Backlight timing and temporary overrides

Nano 5 native UI actions `08087368..08087448` independently emit the values
`2,5,10,15,20,30,-1,0` for `General.BacklightTimer`. Registration accepts all
signed int32 values and defaults to `10`. The user-facing positive-duration and
special-value labels require a complete timer consumer trace; numeric registration
alone must not imply that arbitrary integers represent a supported timeout.

The later firmwares retain `General.BacklightTimer` and `Temp.BacklightTimer`,
but this pass has not located an equivalent complete set of user-visible timeout
choices. Do not carry the Nano 5 UI menu over by assumption. Later radio and other
mode transitions save/replace/restore the ordinary value. `Temp.BacklightTimer`
defaults to `-3`; Nano 6 `081C1D68`, Nano 7 `083DAAC0`, and refresh `083DAADC`
treat `-3` as no saved override. Another saved value is copied back to
`General.BacklightTimer`, then the temporary key is reset to `-3`.

Nano 7 `083BEB9C` preserves the ordinary value into the temporary slot only while
the temporary slot is `-3`. Other mode paths preserve a zero value instead of
overriding it. Those couplings make editing the temporary key independently
inappropriate even though the generic native setter accepts it.

## Date/time and timer meaning

`DateTime.TimeZone` is a firmware table index, not an IANA zone, UTC offset, or
host-local timestamp. Nano 5 computes its registered upper bound as
`082510BA() - 1`: the original constant provider returns `205`, so the maximum is
`204`. Nano 6 and Nano 7 load an inclusive maximum `205` directly. Resolve those
indexes against each exact target's timezone table; do not reinterpret the index
as minutes or transfer city numbering from the Classic family.

Nano 7 and refresh add two World Clock indexes, with defaults `79` and `194`.
`TwentyFourHourClock`, `UserSet24HourSetting`, and `TimeOnWake` are distinct keys.
Clock faces differ: Nano 6 registers `0..17`; Nano 7 and refresh register `0..5`.
The face-number-to-artwork mapping and locale override rules remain open.

The timer registers hours `0..23` (default zero) and minutes `0..59` (default
15). The persisted running timer has a separate `Timer.DateTime` string, empty
by default, `Timer.SleepiPod` false by default, and `Timer.SoundIndex` `0..24`,
default zero. Original count providers return 25. A sleep timer sets an internal
sound selection sentinel `-1` when loading `SleepiPod=true`; that sentinel is not
an additional accepted `Timer.SoundIndex` preference value.

Nano 6 writer `0819ED4C`, Nano 7 `083F283C`, and refresh's corresponding writer
format calendar components with `%04d%02d%02d%02d%02d%02d`. This is a local civil
deadline spelling, with no UTC offset or zone ID. Readers `0802BE40` (Nano 6)
and `081EEB8C` (Nano 7) parse components, compare the deadline with the current
clock and either restore an active timer or transition it to an expired state.
The native reader does not establish a safe validation contract for arbitrary
malformed strings: it does not check the component-scan count in the recovered
path. Exact malformed-input behavior, DST overlap/gap resolution and clock-change
rescheduling remain open. iOpenPod must preserve unrecognized timer text, explain
uncertainty, and keep all datetime issues non-blocking.

## Other important registration differences

- Photos: Nano 5 Music allows `0..5`; later targets allow `1..5`. Transitions are
  `0..9`, default `7` on Nano 5; `0..10`, default `7` on Nano 6; `2..10`, default
  `2` on both Nano 7 releases. Do not equate ordinal values with seconds or
  transition names without their consumers.
- Video: Nano 5 TvOut registers `0..2`, later targets `0..1`. Nano 7 adds
  alternate audio, captions, CC/SDH preference and StartPlaying. Registered
  fields alone do not prove connector/hardware eligibility.
- Fitness: Nano 5 `Trainer.RemoteState` is int32 `0..1`, default zero; later
  versions register a boolean, default true on Nano 6 and false on Nano 7.
  PedometerStepGoal is int64 `0..100000` on Nano 5 and `0..100900` later.
- MeasurementSystem, DistanceUnits and WeightUnits defaults depend on a runtime
  provider. The constructor's booleanized return must not be published as a
  universal default. `Trainer.Weight`'s default int64 bits reinterpret as
  binary64 `68.0388555`; later Height bits reinterpret as `172.0`. Units and
  numeric authoring/validation are not established by those default bit patterns.
- VolumeLimit default providers return `256` or `216` on Nano 5/6 and `256` or
  `232` on Nano 7/refresh. Hardware/region predicates select the result. The
  registered accepted range remains full signed int32; these provider outputs
  are not authoring bounds.
- RadioRegion's default provider maps selector `0`/`0x10 → 1`, `0x20 → 2`,
  `0x30 → 3`, `0x40 → 11`, `0x50 → 4`, otherwise `0`. Region labels and actual
  tuner eligibility are separate from that default mapping. TvSignal also has a
  runtime-derived default on every target.
- Wallpaper's maximum provider returns `12` on Nano 6 and `5` on Nano 7/refresh.
  Those exact return bodies are separately executed and hashed. A synthetic
  provider return of zero in an exploratory constructor run is not the bound.

## Retained binary Preferences payload

All four targets retain `iPod_Control/Device/Preferences`, length `2960`
(`0xB90`), and initialize version `62` (`0x3E`). The payload starts at binary
owner `+4`, not at the named settings owner. The saver refreshes the file word
at `+8` from live volume state. This is not an XML offset.

| File byte range | Qualification |
| --- | --- |
| `[0,4)` | Little-endian format version; initializer writes 62. Tested loader versions do not establish a version-rejection validator. |
| `[4,8)` | Unresolved retained word. No reset-request meaning qualified. |
| `[8,12)` | Partial: little-endian live-volume snapshot, refreshed by saver; initial default comes from half the maximum-volume provider. Maximum, units and live adoption remain unresolved. |
| `[12,2960)` | Unresolved semantic ownership in this pass; includes explicitly initialized fields, arrays and possible retained legacy state. |

The machine inventory provides 50 explicit original initializer writes per
target, each with integer offset, width, value and instruction address, after
the bulk clear. Provider-dependent bytes remain identified as synthetic in the
initializer receipt. These writes are useful leads, **not** a 50-field semantic
model. A zero-filled region is not established padding, and absence of a
reference is not proof that bytes are unused. The semantic unresolved intervals
cover 2,956 of the 2,960 bytes, including the partially identified volume word.

The [consumer supplement](preferences-nano567-consumers-2026-11-07.md)
supersedes Nano 7 refresh's initializer capture: its provider and clear adapter
addresses had moved. Earlier refresh zeros at offsets 8 and `0xB50` were
synthetic-hook artifacts. Corrected native runs establish provider-u32 shifted
right one at offset 8, provider-u32 at `0xB50`, and literal 50 at offset 12 on
both Nano 7 images. The current derived inventory keeps these provider values
symbolic rather than publishing a false fixed default.

Eight bytes have identified structural roles; only the four-byte version is
excluded from unresolved semantic coverage. Volume hardware maximum, units and
live adoption remain unresolved.

The earlier independently qualified raw loaders/savers and preservation cases
remain applicable; see [Nano 3/4/5 research](preferences-nano345-2026-11-07.md)
and [Nano 6/7 research](preferences-nano67-2026-11-07.md). No historical Classic
byte offsets acquire write support merely because an initializer looks similar.

## Remaining work and authoring boundary

The inventory below is concrete progress toward complete preference knowledge,
but it does not meet a zero-unknown completion criterion. Remaining questions are:

1. Close indirect/factory registration coverage, especially Nano 5 Radio.LivePause
   and helper-created settings owners. Separate dormant inherited code from
   settings reachable on actual target hardware.
2. Trace every numeric enum to its UI labels and actual consumer. Large gaps
   include photo transition ordinals, speech modes, VoiceOver triple-click,
   workout activity/body-location/gender/voice modes, menu bit masks, clock faces,
   language/locale lists, radio region labels and video route restrictions.
3. Trace all registration callbacks and persistence hooks, especially
   UIRotation, locale changes and clock changes; qualify dependent writes as a
   single device workflow rather than independent scalar mutations.
4. Resolve binary ownership/bridges: which retained bytes still matter at boot,
   in disk mode, diagnostics, audio resume or timezone conversion, and which
   named changes update them. Preserve every unresolved byte meanwhile.
5. Establish real-device adoption after host XML edits, retained-RAM overwrite
   timing, battery/region restrictions and visible effects. Offline acceptance
   is not a guarantee that an edit is effective immediately after disconnect.

This pass does not widen the app's write allowlist. Existing qualified
Brightness and SoundCheck remain distinct from newly discovered registration
facts. Future authoring should use canonical values and target-specific codecs,
preserve unfamiliar scalar text, and keep all date/time ambiguity non-blocking.

## Complete captured registration matrix

The matrix contains every entry in the corrected inventory, not every possible
firmware preference. `—` means not captured on that target, not unsupported.
`i32`/`i64` mean the full signed container range unless bounds follow. `b` means
a native boolean container; UI booleans use 0/1. `s` means string. The value after
`=` is the default; `provider` means a runtime-derived default. Numeric bounds
are inclusive. Per-field constructor/callsite/body hashes and unresolved effect
status are retained in the machine inventory.

### `iPodSettings.xml`

| Registered key | Nano 5 | Nano 6 | Nano 7 / refresh |
| --- | --- | --- | --- |
| `Accessibility.Invert` | — | `b=0` | `b=0` |
| `Accessibility.MonoAudio` | — | `b=0` | `b=0` |
| `Accessibility.Speech` | — | `i32[0..2]=2` | `i32[0..2]=2` |
| `Accessibility.SpeechLocale` | — | `s="en-US"` | `s="en-US"` |
| `Accessibility.SpeechRate` | — | `i32[50..400]=130` | `i32[50..400]=130` |
| `Accessibility.TripleClickHome` | — | — | `i32[0..3]=0` |
| `Accessibility.VoiceOverConfirm` | — | `b=1` | `b=1` |
| `Accessibility.VoiceOverSpeakHints` | — | `b=1` | `b=1` |
| `Bluetooth.Enabled` | — | — | `b=0` |
| `DateTime.ClockFace` | — | `i32[0..17]=0` | `i32[0..5]=0` |
| `DateTime.TimeInTitle` | `b=0` | — | — |
| `DateTime.TimeOnWake` | — | `b=0` | `b=0` |
| `DateTime.TimeZone` | `i32[0..204]=1` | `i32[0..205]=1` | `i32[0..205]=1` |
| `DateTime.TwentyFourHourClock` | `b=0` | `b=0` | `b=0` |
| `DateTime.UserSet24HourSetting` | — | `b=0` | `b=0` |
| `DateTime.WorldClock1TimeZone` | — | — | `i32[0..205]=79` |
| `DateTime.WorldClock2TimeZone` | — | — | `i32[0..205]=194` |
| `General.BacklightTimer` | `i32=10` | `i32=10` | `i32=10` |
| `General.Brightness` | `i32[0..100]=40` | `i32[0..100]=40` | `i32[0..100]=40` |
| `General.Clicker` | `s="on"` | `s="on"` | `s="on"` |
| `General.FontSize` | `s="standard"` | `s="standard"` | `s="standard"` |
| `General.GroupCompilations` | `b=0` | — | — |
| `General.HomeScreen` | — | `i64=0x000000200B160041` | `i64=0x000000200F160041` |
| `General.Language` | `s="en-US"` | `s="en-US"` | `s="en-US"` |
| `General.MainMenu` | `i64=0x000000240F180201` | — | — |
| `General.MusicMenu` | `i64=13822` | `i64=8318` | `i64=12414` |
| `General.PreviewPanel` | `b=1` | `b=0` | `b=0` |
| `General.RadioLivePause` | — | `b=1` | `b=1` |
| `General.RadioRegion` | `i32=provider` | `i32=provider` | `i32=provider` |
| `General.RequirePasscodeLock` | — | `i32=0` | `i32=0` |
| `General.Rotate` | `b=1` | `b=0` | `b=0` |
| `General.SBIconHint` | — | `b=1` | — |
| `General.SleepWakeButton` | — | `i32[0..1]=0` | `i32[0..1]=0` |
| `General.SleepWakeButtonEnabled` | — | `b=1` | `b=0` |
| `General.SortContacts` | `s="last"` | `s="last"` | `s="last"` |
| `General.SpokenMenus` | `i32[0..2]=2` | — | — |
| `General.SpringboardSmallIcons` | — | `b=0` | — |
| `General.UIRotation` | — | `i32[0..3]=0` | `i32[0..3]=0` |
| `General.Wallpaper` | — | `i32[0..12]=0` | `i32[0..5]=0` |
| `NowPlaying.EnergySaver` | `b=1` | `b=1` | `b=1` |
| `Photos.Music` | `i32[0..5]=1` | `i32[1..5]=1` | `i32[1..5]=1` |
| `Photos.Repeat` | `b=0` | `b=0` | `b=0` |
| `Photos.Shuffle` | `b=0` | `b=0` | `b=0` |
| `Photos.TimePerSlide` | `i32[0..5]=3` | `i32[0..5]=3` | `i32[0..5]=3` |
| `Photos.Transitions` | `i32[0..9]=7` | `i32[0..10]=7` | `i32[2..10]=2` |
| `Playback.AirplaneMode` | — | — | `b=0` |
| `Playback.AudiobookSpeed` | `s="normal"` | `s="normal"` | `s="normal"` |
| `Playback.Compilations` | — | `b=0` | `b=0` |
| `Playback.Crossfade` | `b=0` | `b=0` | `b=0` |
| `Playback.EQ` | `i32=0` | `i32=0` | `i32=0` |
| `Playback.EnergySaver` | `b=1` | `b=1` | `b=1` |
| `Playback.HeadsetEQ` | — | — | `b=1` |
| `Playback.MonoAudio` | `b=0` | — | — |
| `Playback.Repeat` | `s="off"` | `s="off"` | `s="off"` |
| `Playback.Shake` | `b=1` | `b=1` | `b=1` |
| `Playback.Shuffle` | `s="off"` | `s="off"` | `s="off"` |
| `Playback.SoundCheck` | `b=0` | `b=0` | `b=0` |
| `Playback.UseRecommendedVolumeRange` | — | — | `b=0` |
| `Playback.VolumeLimit` | `i32=provider` | `i32=provider` | `i32=provider` |
| `Resume.IsSingleSong` | — | `b=0` | `b=0` |
| `Resume.IsValid` | — | `b=0` | `b=0` |
| `Resume.Playlist` | — | `i64=0` | `i64=0` |
| `Resume.Repeat` | — | `i32=0` | `i32=0` |
| `Resume.Shuffle` | — | `i32=0` | `i32=0` |
| `Resume.Track` | — | `i64=0` | `i64=0` |
| `Resume.TrackMS` | — | `i32=0` | `i32=0` |
| `Settings.SoftwareVersion` | — | `s=provider` | `s=provider` |
| `Settings.TransitionVersion` | `i32=0` | — | — |
| `Speakers.BacklightTimer` | `i32=10` | — | — |
| `Temp.BacklightTimer` | `i32=-3` | `i32=-3` | `i32=-3` |
| `Timer.DateTime` | — | — | `s=""` |
| `Timer.Hours` | — | `i32[0..23]=0` | `i32[0..23]=0` |
| `Timer.Minutes` | — | `i32[0..59]=15` | `i32[0..59]=15` |
| `Timer.SleepiPod` | — | — | `b=0` |
| `Timer.SoundIndex` | — | — | `i32[0..24]=0` |
| `Trainer.BodyLocation` | — | `i32[0..3]=0` | `i32[0..3]=0` |
| `Trainer.BodyLocationCustomized` | — | `b=0` | `b=0` |
| `Trainer.DistanceUnits` | `i32[0..1]=provider` | `i32[0..1]=provider` | `i32[0..1]=provider` |
| `Trainer.Gender` | — | `i32[0..1]=0` | `i32[0..1]=0` |
| `Trainer.GenderCustomized` | — | `b=0` | `b=0` |
| `Trainer.HRMState` | — | — | `b=0` |
| `Trainer.HROWorkout_LastActivity` | — | `i32[1..17]=12` | `i32[1..17]=12` |
| `Trainer.Height` | — | `i64=0x4065800000000000` | `i64=0x4065800000000000` |
| `Trainer.HeightCustomized` | — | `b=0` | `b=0` |
| `Trainer.MeasurementSystem` | — | `i32[0..1]=provider` | `i32[0..1]=provider` |
| `Trainer.Orientation` | `i32[0..2]=0` | `i32[0..2]=0` | `i32[0..2]=0` |
| `Trainer.Pedometer` | `i32[0..1]=0` | `i32[0..1]=0` | `i32[0..1]=0` |
| `Trainer.PedometerActivty` | — | `i32[0..4]=1` | `i32[0..4]=1` |
| `Trainer.PedometerStepGoal` | `i64[0..100000]=0` | `i64[0..100900]=0` | `i64[0..100900]=0` |
| `Trainer.PedometerStepGoalSet` | — | `b=0` | `b=0` |
| `Trainer.PersonalSettingsCustomized` | — | `b=0` | `b=0` |
| `Trainer.PowerPlaylist` | `i64=0` | `i64=0` | `i64=0` |
| `Trainer.PowerSong` | `i64=0` | `i64=0` | `i64=0` |
| `Trainer.RemoteState` | `i32[0..1]=0` | `b=1` | `b=0` |
| `Trainer.Sensor` | — | — | `b=0` |
| `Trainer.TrainerSplashScreenShown` | — | `b=0` | — |
| `Trainer.VoiceFeedback` | `i32[0..2]=1` | `i32[0..2]=1` | `i32[0..2]=1` |
| `Trainer.Weight` | `i64=0x4051027C9BC77143` | `i64=0x4051027C9BC77143` | `i64=0x4051027C9BC77143` |
| `Trainer.WeightCustomized` | `b=0` | `b=0` | `b=0` |
| `Trainer.WeightUnits` | — | `i32[0..1]=provider` | `i32[0..1]=provider` |
| `Trainer.ZoneWorkout_Enabled` | — | `b=0` | `b=0` |
| `Trainer.ZoneWorkout_High` | — | `i32[15..240]=100` | `i32[15..240]=100` |
| `Trainer.ZoneWorkout_Low` | — | `i32[15..240]=90` | `i32[15..240]=90` |
| `Trainer.ZoneWorkout_ZoneSet` | — | `b=0` | `b=0` |
| `Video.StartPlaying` | — | — | `i32[0..1]=1` |
| `Video.TvAlternateAudio` | `b=0` | — | `b=0` |
| `Video.TvCaptions` | `b=0` | — | `b=0` |
| `Video.TvOut` | `i32[0..2]=0` | `i32[0..1]=0` | `i32[0..1]=0` |
| `Video.TvPreferCCorSDH` | — | — | `b=0` |
| `Video.TvScreenAspect` | `i32[0..1]=0` | `i32[0..1]=0` | `i32[0..1]=0` |
| `Video.TvScreenFitToScreen` | `b=0` | `b=0` | `b=0` |
| `Video.TvSignal` | `i32[0..1]=provider` | `i32[0..1]=provider` | `i32[0..1]=provider` |
| `Video.TvSubtitles` | `b=0` | — | — |

### `iPodTimerSettings.xml`

| Registered key | Nano 5 | Nano 6 | Nano 7 / refresh |
| --- | --- | --- | --- |
| `Settings.SoftwareVersion` | — | `s=provider` | — |
| `Timer.DateTime` | — | `s=""` | — |
| `Timer.SleepiPod` | — | `b=0` | — |
| `Timer.SoundIndex` | — | `i32[0..24]=0` | — |
