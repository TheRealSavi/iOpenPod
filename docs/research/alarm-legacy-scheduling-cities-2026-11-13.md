# Legacy alarm scheduling and city identity

Research date: 2026-11-13. This continues the
[legacy sound investigation](alarm-sounds-legacy-2026-11-13.md) with independent
Mini 1 scheduling execution, Nano 1 scheduling execution, and the native city
catalogs of Nano 1 and all three available Video updater inputs. It narrows
previous unknowns; it does not establish physical wake or mounted-file adoption.

The subsequent [city-authoring investigation][city-authoring] closes the
creation/removal, collection-growth, manual-DST and empty-store questions for
all five Nano 1 and Video inputs. Its product comparison and checked-in native
fixture cover every catalog entry. The scheduling findings below remain
applicable; firmware-adoption/reload timing is outside the requested scope.

## Inputs and reproducibility

The probes load the original main images and hash-checked runtime memory maps.
The [scheduling receipt][schedule-receipt] contains **60 cases**: 19 each for
Mini 1 families 3/6 and 11 each for Nano 1 families 14/17. The
[city receipt][city-receipt] contains **1,038 cases**: 204 native city lookup
round trips on each of five updater inputs, plus four Add City, two empty-load
fallback and three Radio-availability cases on each Nano 1 input. Each receipt checks every executed instruction against the
original image bytes and records the image and map identities.

| Inputs | Main image SHA-256 |
| --- | --- |
| Mini 1 families 3/6, 1.4.1 | `2f844307acf62702fc247b19a148f35d497ce59d6ef7790b242200b5d64b09df` |
| Nano 1 families 14/17, 1.3.1 | `2d34721c1d36f592b076ca111822cea6afcf718331dcf4117618f0eb338bf4cb` |
| Video families 13/20, 1.3 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| Video family 25, 1.3 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` |

Run in the sibling firmware lab with new output directories:

```powershell
uv run scripts/probe_legacy_alarm_scheduling.py artifacts/legacy-scheduling-NEW
uv run scripts/probe_legacy_clock_cities.py artifacts/legacy-cities-NEW
```

The [scheduling script][schedule-probe] SHA-256 is
`1db1d1d5bf6d6ad4482c4c7755f4da501715bad8307452009506d50b2d225271`;
receipt SHA-256 is
`d4a3ba6fa816f93d07655706ba6765dd2ce7de660c139b48dd82c2fa6f2aff01`.
The [city script][city-probe] SHA-256 is
`6db3ea4a495fd5606cf012483d15b4fbe401e984647cfe02558b88e7eee73a4d`;
receipt SHA-256 is
`389951eca198e83805b1bb32fb3e73d7483d345c53011e40a29188e984289dbc`.

Scheduling adapters supply the current clock and UI properties. Mini's native
calendar arithmetic and registration-record construction execute, but the slot
handoff and cancellation endpoints are adapted; RTC hardware is excluded.
Nano's native scalar conversion, timezone table arithmetic and manual DST helper
execute; the selected city's base offset is supplied at its lookup boundary.
The separate city probe then executes the actual base-offset lookup over the
complete native catalogs. Add City adapts allocation, collection append and
UI notification, while executing its native controller and constructors.
Initialization's store load, observers and schedule recomputation are adapted;
Radio cases adapt message delivery and backend attach/detach hooks. They do not
simulate a physical accessory or claim to execute its connection protocol.

## Mini 1 independently confirms the five-second boundary

Original routine `0x000D875C` reads the alarm minute and enabled properties.
Disabled clears the runtime enabled byte and cancels slot 3. Enabled constructs
the native slot-3 calendar record. It selects today only when
`alarm_minutes * 60 - current_seconds_of_day > 5`; otherwise it advances one
civil day. Native date conversion handles the month/year boundary and leap-day
cases in this probe. Six seconds before fires today; five seconds before,
equal time and later times select tomorrow. [Native routine][mini-schedule],
[executed vectors][schedule-receipt].

This closes the previous Mini 1 arithmetic-parity gap with Mini 2. It does not
extend the Mini 2 hardware-register probe to Mini 1 or prove sound and wake on a
physical Mini. The five-second exclusion belongs to firmware scheduling and
must not be implemented by changing the saved minute value.

## Nano 1 does not use Video's scheduling calculation unchanged

Original routine `0x001738A4` first truncates current seconds to zero. It builds
the selected alarm hour/minute on that same civil date, then adjusts by the
current effective timezone hours minus the selected city's base minutes and
manual DST hour. The current setting is resolved through a native 50-byte
signed-hour table, with standard/DST menu entries. The selected city lookup
supports fractional-hour offsets. [Native scheduler][nano-schedule],
[timezone difference][nano-zone], [city DST helper][nano-dst].

If the candidate is less than or equal to the truncated current time, the
routine adds exactly 86,400 seconds once. It does not normalize through an IANA
timezone database or loop until future. In the synthetic extreme-offset vector
current UTC−12, target UTC+12, current 23:50 and target 00:01, that single
correction still leaves the result earlier on the current date. This is a
component-level boundary finding, not a claim of an observed hardware failure.
[Original-instruction cases][schedule-receipt].

The probe also confirms equal/current-minute rollover, next-minute acceptance,
manual DST differences, +05:45 and −03:30 selected-city offsets, and a
spring-gap-shaped 02:30 civil time. The latter is simply civil arithmetic; it
does not establish what happens when a physical iPod's clock is adjusted.

## City names and saved ordinals are now mapped

Nano 1 and Video each contain eight regions and 204 city entries:

| Region | Entries |
| --- | ---: |
| Africa | 31 |
| Asia | 57 |
| Atlantic | 3 |
| Australia | 8 |
| Europe | 34 |
| North America | 49 |
| Pacific | 5 |
| South America | 17 |

Every region/city was passed through native resource lookup, inverse lookup and
base-offset lookup. English resource names and serialized ordinals match across
these five inputs; native resource IDs differ by four between Nano and Video.
The on-disk city ordinal is a resource-relative ID, **not the city's position
within its region array**. The complete mapping and original table addresses
are retained in the [receipt][city-receipt].

Two base offsets differ. These are firmware constants, not current geographic
timezone guidance:

| City | Saved city ordinal | Nano 1 1.3.1 | Video 1.3 |
| --- | ---: | --- | --- |
| Colombo | 149 | +360 minutes | +330 minutes |
| Ponta Delgada | 33 | 0 minutes | −60 minutes |

The other 202 entries match in name, ordinal and base offset. The subsequent
[city-authoring investigation][city-authoring] uses this qualified mapping for
city labels and creation; scheduling remains tied to the exact firmware family.
These native results do not qualify Nano 2 or historical releases outside the
inspected corpus. Nano 2 compatibility is a separate explicit user assumption.

## Initial Nano 1 Add City and removal findings

Native Add City `0x00190C74` takes the pending native region/city indices, derives
the new city's manual DST byte from the current timezone-menu enum, constructs
the city and appends it. It selects the returned collection index, marks the
collection dirty at `+0x88`, and notifies observers. The native constructor sets
alarm minute 0, active kind 8 (off), retained sound mode 0 and playlist index 0;
the alarm gets a back-pointer to its city. Four standard/DST enum cases were
executed on each Nano 1 input. [Add City][nano-add], [constructor][nano-city-ctor],
[executed cases][city-receipt].

Initialization `0x00191018` copies the current timezone-menu enum into the owner
before loading. When the loaded collection is empty, it resolves the native
North America / California entries and calls Add City. Two original-instruction
vectors execute this fallback after an adapted load leaves zero entries, proving
the default identity, off/midnight alarm, inherited DST flag and selected index
zero. This does not yet prove every malformed/missing-file outcome of the real
loader. [Initialization][nano-initialize], [executed cases][city-receipt].

Native Remove City `0x00190CE0` removes the selected collection entry, decrements
the selection if it was positive, marks the collection dirty and notifies.
The underlying removal routine frees the owned city/alarm object, validates
indices and shifts the array. These removal findings are **static evidence**;
the full collection mutation and empty-list UI were not executed in this pass.
[Removal controller][nano-remove], [owned removal][nano-array-remove].

The later [city-authoring investigation][city-authoring] supersedes this pass's
pending authoring questions with executed Nano 1 and Video Add/Remove, native
collection growth, complete store readers/writers, explicit DST and empty/missing
store cases. It verifies deletion of the final city, duplicate identities and
the exact 125-byte defaults for every catalog entry. Firmware-adoption timing
is explicitly outside scope; it is not an outstanding prerequisite for the
qualified pure file operations.

## Radio availability is a runtime service query

Nano 1 UI getter `0x000EC6CC`, property `0x60CC`, clears UI `+0x94`, obtains service
`0x5800`, calls `0x001994F0`, then caches the returned availability byte and adds
a Radio row when nonzero. This is separate from the saved alarm's active kind
and retained sound mode. The getter dispatches through the service's `+0x68`
object and its vtable slot `+0x58`. [UI query][nano-radio-ui],
[service lookup][nano-radio-service], [availability dispatch][nano-radio-getter].

The service constructor creates that object through `0x00122A98`. Its native
vtable at `0x00507298` resolves slot `+0x58` to `0x000B532C`, a byte getter for
object `+0x14`. The base constructor initializes it to zero; attach-style
notification `0x000B53FC` sets it to one and emits event `0x58000000`, while
`0x000B5334` clears it and emits `0x58000001`. This narrows the source of the UI
flag to runtime accessory-service state. The hardware event that establishes
availability and usable Radio reception is still unexecuted. The probe executes
the original available/unavailable notification routines and original virtual
getter with message delivery/backend hooks adapted: the getter returns 0, then
1 after the available notification, then 0 after the unavailable notification.
It is not safe to
infer a connected accessory from a saved alarm mode. [Service constructor][radio-ctor],
[backend constructor][radio-backend], [base constructor][radio-base],
[availability set][radio-set], [availability clear][radio-clear].

## Scope and remaining uncertainties

The retained-state save paths are more specific than a generic RAM warning.
Mini 1's `0x000DD840` checks owner dirty byte `+0xB44`, copies the retained
Preferences payload into a write buffer, writes the file and clears the dirty
byte. Nano 1's flush coordinator `0x0003B77C` calls clock-save wrapper
`0x0003B8D8`, which obtains the clock owner and tail-calls `0x00191BE4` with
mode 1. That routine skips saving when owner `+0x88` is clear; otherwise it
serializes the retained city collection. These are static lifecycle traces in
this pass, supplementing the earlier native serialization probes. They locate
the overwrite mechanism but do not establish its exact ordering against Host
USB publication/eject. [Mini dirty save][mini-save], [Nano flush][nano-flush],
[Nano save wrapper][nano-save-wrapper], [Nano clock store][nano-store].

- Firmware-adoption/reload timing across eject, restart and device-side edits is
  excluded at the user's direction. The static save traces above are retained
  as findings, not a request for additional lifecycle research.
- City removal, Video creation, collection growth and missing/empty-store
  behavior are covered by the [completed authoring investigation][city-authoring].
- Complete accessory hardware attachment/detachment and alarm-time Radio
  delivery; current runtime availability is not exposed by a qualified disk file.
- Validate physical wake, audio routing, clock changes and manual DST changes.
- Nano 2 remains encrypted. The user subsequently chose
  [Nano 1 compatibility](../adr/0261-use-nano-1-alarm-compatibility-for-nano-2.md)
  for its editor; this assumption does not substitute for native code evidence.

[schedule-probe]: ../../../ipod-firmware-lab/scripts/probe_legacy_alarm_scheduling.py
[schedule-receipt]: ../../../ipod-firmware-lab/artifacts/legacy-alarm-scheduling-20261113-v3/receipt.json
[city-probe]: ../../../ipod-firmware-lab/scripts/probe_legacy_clock_cities.py
[city-receipt]: ../../../ipod-firmware-lab/artifacts/legacy-clock-cities-20261113-v3/receipt.json
[city-authoring]: alarm-legacy-city-authoring-2026-11-13.md
[mini-schedule]: ../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000d875c.c
[nano-schedule]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/001738a4.c
[nano-zone]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000ee5b4.c
[nano-dst]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000a6c20.c
[nano-add]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00190c74.c
[nano-initialize]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00191018.c
[nano-city-ctor]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000a6e38.c
[nano-remove]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00190ce0.c
[nano-array-remove]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/001d982c.c
[nano-radio-ui]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000ec6cc.c
[nano-radio-service]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00199940.c
[nano-radio-getter]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/001994f0.c
[radio-ctor]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/0019a078.c
[radio-backend]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00122a98.c
[radio-base]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000b5460.c
[radio-set]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000b53fc.c
[radio-clear]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000b5334.c
[mini-save]: ../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000dd840.c
[nano-flush]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/0003b77c.c
[nano-save-wrapper]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/0003b8d8.asm.txt
[nano-store]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00191be4.c
