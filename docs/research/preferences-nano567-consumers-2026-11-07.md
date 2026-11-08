# Nano 5/6/7 preference consumers and timezone catalog

This supplements [the registration inventory][baseline] for Nano 5 / 34 / 1.0.2,
Nano 6 / 36 / 1.2, Nano 7 / 37 / 1.0.4, and Nano 7 refresh / 39 / 1.1.2.
Every image was checked independently. Nothing was sent to a physical iPod.
The supplied firmware remains unchanged.

The principal corrections are a missing Nano 5 `Radio.LivePause` registration
and the meaning of `DateTime.TimeZone`: it is a **city ID**, not the row number
in a table. All four images contain city IDs 1 through 205. Nano 5 nevertheless
registers an inclusive maximum of 204. ID 205 is Phnom Penh, not a sentinel.

The [combined machine inventory][inventory] retains every earlier field and
adds scoped semantic annotations. It contains 53 ordinary Nano 5 keys,
89 ordinary Nano 6 keys plus four separate `iPodTimerSettings` keys, and 102
ordinary keys for each Nano 7 image. This pass annotates 8, 15, 19 and 19 fields
respectively; an annotation is not a claim that every effect is resolved.
No new preference gains authoring permission from this report alone.

## Evidence and coverage

Authoritative second-pass artifacts, each with script/helper/input/output hashes:

- [Discovery][discovery]: original missing registration tail plus expanded
  whole-decompiled-corpus references. The final run reuses the earlier scan
  after checking the exact image and every indexed pseudocode hash; it does
  not claim another complete discovery scan.
- [UI tables and consumers][tables]: 1,060 bounded cases covering resource
  bindings, photo timing, radio, fitness conversions, volume and audiobook UI.
- [Locale and rotation][locales]: 4,176 bounded compatibility/provider/selector
  and hardware-byte callback cases.
- [Timezone catalog and joined pipeline][timezones]: all 205 cities per image,
  1,156 lookup/offset/notification/arithmetic cases, all 158 selected packaged
  zone records per later image, and 615 city bindings through original native
  constructors using the original parser's resulting vector.
- [Independent city constructor pass][city-bindings]: another 615 constructor
  cases, using an explicitly host-assembled vector in packaged file order.
  The joined pipeline above is the stronger ordering check.
- [Initializer correction][initializer-correction]: 16 bounded native executions
  with exact Nano 7 and refresh clear/provider call targets, nonzero initial
  memory, and eight explicitly synthetic maximum-volume inputs per image.

The expanded reference scan finds 244 relevant functions / 12 possible owners
on Nano 6 and 292 / 14 on each Nano 7 image. It found no additional later-model
registration owner beyond the earlier captured candidates. Constant aliases
and table dereferences are supported; assembly-only bodies, dynamic strings,
factory flows and unresolved constructor paths still prevent a completeness
claim. Missing references are not evidence of an unused or reserved field.

The binary `Preferences` ledger remains conservative: version word `[0,4)` is
identified, and `[4,2960)` remains unresolved or partial. The live-volume word
at offset 8 has an identified structural role but unresolved hardware units,
limits and adoption. No additional opaque bytes are declared padding.

The current inventory also supersedes the earlier Nano 7 refresh initializer
capture. That harness retained Nano 7's clear/provider adapter addresses;
refresh calls moved from `0840C35A` to `0840C35E` and from `083F872E` to
`083F8746`. Consequently, its generic external-call hook returned zero instead
of the intended synthetic maximum 100, and the clear hook was not reached.
The earlier refresh `+8 = 0` and `+0xB50 = 0` are harness artifacts, not a
firmware default difference. The earlier Nano 7 values 50/100 also depended
on that synthetic maximum; neither is a fixed device default.

Corrected execution establishes the same contract on both images: offset 8
receives an unsigned logical right shift of the provider result by one;
offset `0xB50` receives the provider result; offset 12 receives literal 50.
All 2,960 input bytes were prefilled with `0xA5`, the correct clear call and
extent were asserted, and an untouched byte was checked after initialization.
The fresh derived inventory uses symbolic values for provider-dependent writes
and retains synthetic observations separately. Prior scripts and artifacts
remain unchanged for provenance.

## Radio and audio

Nano 5 constructor `0816C898` registers `Radio.LivePause` in its tail at
`0816CB12..0816CB24`, with boolean default 1. The earlier constructor harness
stopped before this tail while entering unrelated radio services. Native
toggle `08081ED8` reads, inverts and writes it; service consumer `0828759C`
passes its boolean state toward the radio service. This is distinct from
`General.RadioLivePause` on later Nanos. Buffer size, recording interaction and
hardware adoption remain unqualified.

All four radio UI tables bind these values:

| Value | Meaning |
| --- | --- |
| 1 | Americas |
| 11 | Asia |
| 4 | Australia |
| 2 | Europe |
| 3 | Japan |
| 10 | World Wide (TEST) |

Nano 5 returns five ordinary rows or six when an object capability byte is
nonzero. On Nano 6/7, the region-change callback substitutes the provider
default when value 10 is selected without test capability. Other tested
integers reach the tuner as their low byte. That behavior does not authorize
iOpenPod to truncate or normalize unknown values. Tuner band edges, channel
spacing and the test capability's hardware origin remain open.

`Playback.AudiobookSpeed` uses case-sensitive `slow`, `normal`, `fast`.
The UI cycle is slow → normal → fast → slow. Uppercase, empty and unknown
strings cycle to slow when the firmware UI action is invoked; a Host reader
must preserve them as unknown. The actual playback rate factors are unresolved.
Static consumers distinguish slow/normal/fast mode codes, but those codes alone
do not establish a rate such as 0.75× or 1.25×.

`Playback.VolumeLimit` is registered broadly as an integer, but the runtime
setter clamps an unsigned candidate to `floor(maximum / 10)..maximum`:

| Image | Qualified runtime maxima | Corresponding minimum |
| --- | --- | --- |
| Nano 5, Nano 6 | 216 or 256 | 21 or 25 |
| Nano 7, refresh | 168, 232 or 256 | 16, 23 or 25 |

On Nano 7, restriction/route predicates select restricted versus unrestricted;
the recommended-limit byte then selects 168 versus 232 in the restricted path.
These predicates were independent synthetic inputs; every combination is not
claimed physically realizable. Mode codes 3/5, or mode 1 with its enable byte
clear, bypass the preference write and use runtime 256. Names for these modes,
acoustic units and a percent conversion remain unresolved. Static binary loader
`081545D8` also clamps a saved raw volume at or above 168 to 167 under its
restriction predicate; this has not been qualified as a new binary writer.

## Photos

`Photos.TimePerSlide` values 1..5 mean 2, 3, 5, 10 and 20 seconds. Nano 5 value
0 is visibly **Manual** and returns float -1 in the traced timing path. Later
Nanos register 0 but omit it from the current five-choice UI; their timing path
uses 3 seconds for 0 or an unknown value. On later Nanos transition 7 forces a
nominal 5 seconds. Nano 7 schedules a backend delay of nominal minus 1,150 ms;
this is not proof that the visible slideshow interval is shorter, since the
transition contributes timing. Explicit positive duration overrides remain a
separate path.

Nano 5's full transition label switch is:

| Value | Nano 5 label | Nano 6 label switch |
| --- | --- | --- |
| 0 | None | None |
| 1 | Random | Random |
| 2 | Dissolve | Dissolve |
| 3 | Slide | Slide |
| 4 | Push | Push |
| 5 | Fade Through Black | Fade Through Black |
| 6 | Zoom | Zoom |
| 7 | Ken Burns | Ken Burns |
| 8 | Cube | Cube |
| 9 | Flip | Page Flip |
| 10 | Not registered | Origami |

The current Nano 6/7 transition UI contains only 2, 7, 9, 4, 10, in that order.
Native initializers populate the stored values; examining the zero-filled
pre-initialization table alone would give the wrong answer. Nano 7's registered
2..10 range is broader than this menu. Its non-menu effects are not inferred
from Nano 6's legacy label switch.

## Fitness and accessibility

The later Nano UI tables establish:

| Preference | Values and labels |
| --- | --- |
| `Trainer.VoiceFeedback` | 0 Male, 1 Female, 2 Off; displayed Female, Male, Off |
| `Trainer.DistanceUnits` | 0 Kilometers, 1 Miles |
| `Trainer.MeasurementSystem` | 0 Metric, 1 English, meaning imperial units |
| `Trainer.Gender` | 0 Male, 1 Female |
| `Trainer.BodyLocation` | 0 Waist, 1 Chest, 2 Pocket, 3 Wrist |

Voice, distance and measurement selectors were executed on every later image.
Gender and body-location findings are source descriptor/resource bindings;
their selection and algorithmic effects have not been executed in this pass.

`Trainer.Weight` stores a binary64 floating-point bit pattern in its int64
preference container. Its canonical unit is kilograms. Native imperial input
conversion multiplies by exactly 0.45359237 on all four images. Nano 5's native
display conversion multiplies by 2.2046226; later display code statically uses
the same rounded factor. Thus 150 pounds becomes 68.0388555 kg, matching the
registered default bits, but display round trips need not be exact.
Do not expose this field as an arbitrary integer or treat the registered
int64 bounds as valid human weight bounds.

Later weight UI source also couples `WeightUnits`, `MeasurementSystem` and
`WeightCustomized`. Nano 7 height code uses canonical centimeters, divides by
2.54 for inches, and formats feet/inches using 12. Height/weight UI bounds,
rounding, invalid floating-point input and workout consumers remain open.

Nano 7 `Accessibility.TripleClickHome` labels 0 Off, 1 Toggle VoiceOver,
2 Toggle Invert Colors. Registered value 3 returns resource ID 0 in the
traced label getter. Its meaning remains unknown; it is not documented as Off,
a combined toggle, or padding.

## Language, speech and rotation

Nano 6 has 29 language UI strings. Nano 7 and refresh have 35; they add
`en-GB`, `uk-UA`, `id-ID`, `ms-MY`, `ca-ES`, `vi-VN`. Both later images were
qualified separately. All three have the same 29 speech locale strings.
The complete case-sensitive values and native language IDs are in the
machine inventory and locale table artifacts; these are distinct domains.
Language table membership does not prove that a particular voice payload is
installed on the connected device.

The language setter preserves a compatible `Accessibility.SpeechLocale`.
Otherwise its provider chooses a matching speech locale. Native region
overrides are English + Australia → `en-AU`, English + Europe → `en-GB`,
Spanish + Americas → `es-MX`, French + Americas → `fr-CA`. Unsupported languages
may have no speech match. Compatibility is an exact byte comparison; unknown
or case-changed values must remain representable in iOpenPod.

Nano 7's language observer (`0827841C`, refresh `0827843C`) also reads
`DateTime.UserSet24HourSetting`. Only when false does it update
`DateTime.TwentyFourHourClock` from the locale's clock-format property. Preserve
the user override; do not make a Host language change silently reset it.
This outer observer was traced statically; its providers and comparison helpers
were executed separately.

`General.UIRotation` callback notification 0 reads one low-level hardware-buffer
byte at offset 12 into the named preference. Other tested notification values
write the preference's low byte back. The bridge was executed in both directions
on Nano 6/7/refresh, with the hardware read/write boundary mocked. This offset
is **not** offset 12 of the binary `Preferences` file. Rotation-angle meanings,
peripheral persistence and complete notifications remain unresolved.

## City IDs, packaged timezone files and clock offsets

The machine catalog contains every ID, English resource label, group and
offset linkage for each image. Important anchors:

| City ID | Label | Role |
| --- | --- | --- |
| 0 | No lookup result | Registered but no table row |
| 1 | California | Default primary timezone |
| 79 | London | Nano 7 default first world clock |
| 194 | Tokyo | Nano 7 default second world clock |
| 204 | Kuwait | Last ID inside Nano 5 registration range |
| 205 | Phnom Penh | Real city; outside Nano 5 registration maximum |

Nano 5 table `08434110` uses 16-byte rows: resource u32 at 0, group u16 at 4,
city ID u16 at 6, two unresolved u16 fields at 8/10, offset code u16 at 12,
and an unresolved final halfword. Offset codes resolve through the original
32-entry signed-minute table at `08434090`. Native lookup `08153A60` resolves
all 205 IDs; offset lookup `08256D30` returns signed minutes and uses
`INT32_MAX` for an unknown code. Do not turn that sentinel into a clock error.

Nano 6/7 rows are 12 bytes: resource u32 at 0, group u16 at 4, city ID u16 at 6,
and a timezone-vector index byte at 8. The remaining three bytes are retained
without a padding claim. Tables are `08593F50`, `0872C99C`, and the exact refresh
address recorded in the artifact. Native lookup compares the city ID, not its
row ordinal. The group affects reverse selection of a city matching a base/DST
pair and a preferred geographical group; it is not itself a UTC offset.

These later firmwares load `Resources/DST/iPodTZData.dat`, with an override at
`iPod_Control/Device/iPodTZData.dat`. Packaged files were extracted read-only
from the signed plaintext RSRC FAT16 payload in each hash-pinned IPSW:

| Image | Version / bytes | Selected section | Zone records / rule records |
| --- | --- | --- | --- |
| Nano 6 | 2 / 9,249 | kind 0, flags 0 | 158 / 210 |
| Nano 7 | 6 / 16,168 | kind 1, flags 0 | 158 / 166 |
| Nano 7 refresh | 6 / 16,168 | kind 1, flags 0 | 158 / 166 |

The Nano 7 files are byte-identical, SHA-256
`5d3ee4bc2c1d25e4e2c26b3906cb896e10cba2d55bf67c18032ccf5560af189d`.
Nano 6 is
`f438de4a0b671e5aaa7c4a72284e85d6dad2d0d44187b6db2e5a7ca56a4fe606`.

File framing is version u16, declared file size u32, followed by sections with
kind u16, flags u16, declared length u32. A kind-0 record is a NUL-terminated
name, signed base minutes i16, rule count byte, then 30 bytes per rule.
Kind 1 adds a u16 between base minutes and rule count; its role is unresolved.
Each rule carries a 16-byte label that the native parser skips and a 14-byte
payload: start/end years i16, month/weekday/day/day-selector bytes, transition
minutes i16, adjustment minutes i16, and time-basis code i16. The retained
machine artifact includes every raw rule and decoded scalar. Day selectors
0/1/2 and time-basis codes 0/1/2 require their distinct calendar algorithms;
no modern tzdb interpretation is substituted.

Nano 7 kind-1 declared length is 16,146, while 8,231 bytes remain at its payload
start. The declared number equals the combined payload sizes of both sections.
The original parser also checks absolute file length and successfully consumes
the section. The producer convention is not yet pinned, so this is an observed
length convention/tolerance, not a claim that Apple's supplied file is corrupt.

The original record parser appends zone-constructor return pointers in stream
order. The joined native probe verifies that resulting vector, then executes
the original city constructors and vector helpers against the same vector in
the same emulator. It does not reconstruct or sort that vector between stages.
File reads, allocations, string ownership and zone constructors are boundaries;
initial vector capacity is synthetic. The outer singleton/file-selection path
is statically traced, not executed end to end. All supplied rule counts are below
128; malformed counts at or above 128, allocation growth and real zone-object
construction remain outside this qualification.

That bounded pipeline exposes an apparent discrepancy: later city 118, labelled
Cape Town, selects zone index 6, whose packaged record is `Africa/Bissau`, base
0. Nano 5's Cape Town offset is +120. This is not yet a physical-device finding
or permission to correct the clock automatically. Record the firmware mapping
separately from geographical expectations. Twelve other city base offsets differ
between the Nano 6 and Nano 7 packages, including Russian cities and Tripoli;
there is no universal Nano offset table.

Native timezone-change paths narrow a stored city to 16 bits, look up its zone,
pass signed base minutes and a signed-byte DST result to the clock setter, then
notify dependent UI. Unknown IDs produce no setter call in the tested path.
The original setters were separately executed with synthetic current time and
offset boundaries. They save base/DST with mask `0x180` and calculate:

```text
new_clock = old_clock + 60 × (new_base − old_base + new_DST − old_DST)
```

This independently establishes sign and minute units. It does not settle raw
RTC origin, all saved-bias precedence, clock overflow/epoch boundaries or the
current-date DST evaluator.
The DST evaluator is still a boundary in the notification probe. Saved offsets,
raw city IDs, manual overrides where present, firmware rule data and Host
timezone choices must remain separate. Any uncertain or invalid datetime stays
nonblocking and preserves its source bytes.

## Remaining work

- Finish indirect/dynamic/factory registration and unresolved constructor paths;
  the missing Nano 5 radio tail demonstrates why the earlier count was not final.
- Resolve all remaining field consumers, especially Bluetooth, video routing,
  menu masks, fitness activity algorithms, timer end states and notification IDs.
- Qualify complete locale changes and speech payload eligibility; Nano 5 locale
  tables have not been brought to the later-model level in this pass.
- Execute DST rule selection and transition builders against the packaged rules,
  confirm file override precedence, manager initialization and reverse city
  selection, and explain kind-1 extra u16 and the section-length producer.
- Establish physical adoption, route/hardware restrictions and precise unit/UI
  bounds before widening Host writes. Preserve the binary ledger's partial and
  unresolved ranges rather than interpreting them from another model's layout.

The registration and semantic inventory remains a research model. This pass
adds evidence and corrections without introducing application datetime errors,
new write permissions or dependencies.

[baseline]: preferences-nano567-complete-2026-11-07.md
[inventory]: ../../../ipod-firmware-lab/artifacts/nano567-preferences-round2-20261107-final-inventory-v3/inventory.json
[discovery]: ../../../ipod-firmware-lab/artifacts/nano567-preferences-round2-20261107-final-discovery/results.json
[tables]: ../../../ipod-firmware-lab/artifacts/nano567-preferences-round2-20261107-final-tables/results.json
[locales]: ../../../ipod-firmware-lab/artifacts/nano567-preferences-round2-20261107-final-locales/results.json
[timezones]: ../../../ipod-firmware-lab/artifacts/nano567-preferences-round2-20261107-final-timezones-v2/results.json
[city-bindings]: ../../../ipod-firmware-lab/artifacts/nano567-preferences-round2-20261107-final-city-bindings/results.json
[initializer-correction]: ../../../ipod-firmware-lab/artifacts/nano7-binary-initializer-correction-20261107-final/results.json
