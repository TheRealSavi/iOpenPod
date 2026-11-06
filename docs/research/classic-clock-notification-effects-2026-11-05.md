# Latest Classic clock notification effects

Research begun 2026-11-05 and completed 2026-11-06, America/Detroit. Scope is
Classic updater families **24 / 1.1.2, 33 / 2.0.1, 35 / 2.0.4 and 38 / 2.0.5**.
The [target report](classic-latest-firmware-targets-2026-11-05.md) explains why
these are separate latest firmware targets; retail generation names alone do
not distinguish all four. No physical device I/O or application source changes
were performed for this report.

## Findings

Host calendar event `0x11` does reach a concrete application handler that can
change saved Preferences city, DST and clock correction. The earlier
[raw-clock report](classic-raw-clock-origin-followup-2026-11-05.md) correctly
limited its direct-command claim: absence of a city write in the SCSI command
body did not imply absence after its queued notification. This pass closes that
route, including the installed callback, message type, concrete recipient vtable
and thread-identity delivery gate. [Primary receipt][receipt]

Two real differences matter for compatibility:

- **Classic24 matches a city by base offset only.** The other three also compare
  that city's current-date DST predicate with the imported DST boolean.
- **The two persistence routes use different DST representations.** The Host
  calendar handler finishes by saving `0` or `1`; the registered `0x80a9` zone
  observer saves the raw live DST byte, normally `0` or `60`. A saved nonzero byte
  is therefore not proof of a particular normalized value or a historical rule.

Both conclusions are independently verified in all four images. Seventy-two
bounded native ARM cases exercise the actual branch logic and Preferences stores
with explicit mocks at OS, queue, clock and city-service boundaries. These are
not physical-device observations or full firmware boots. [Verifier][script],
[execution records][receipt]

## Primary evidence and reproduction

The verifier rejects unexpected OSOS and memory-map SHA-256 values, records its
own and its imported helper's hashes, and exports **258 exact byte windows**
with ARM listings and individual hashes. Windows are intentionally bounded;
their labels do not assert recovered Apple symbols or complete function extent.
Original firmware and earlier artifacts are preserved. [Receipt][receipt]

| Target | OSOS SHA-256 |
| --- | --- |
| 24 / 1.1.2 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` |
| 33 / 2.0.1 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| 35 / 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` |
| 38 / 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |

Run from the sibling firmware lab, choosing an unused output directory:

```powershell
uv run scripts/check_classic_clock_notifications.py --output artifacts/clock-notification-repeat
```

Python 3.12, Capstone 5.0.6 and Unicorn 2.1.4 are recorded in the receipt. The
emulator maps only isolated RAM, allows execution inside named instruction
windows or declared mock entries, stops on an unexpected instruction address,
and caps each invocation at 200,000 instructions. Firmware file writers and
hardware interfaces never execute. Ruff formatting and lint checks passed for
the verifier and the two read-only discovery helpers. [Verifier][script]

## Host event: registration, queue and concrete recipient

The independently resolved addresses are:

| Role | 24 | 33 | 35 | 38 |
| --- | --- | --- | --- | --- |
| Event mapper | `080bfcf0` | `080c31a4` | `080d9e6c` | `080d9f18` |
| Callback installer | `081b6ec8` | `081c0fe4` | `081db1c8` | `081dbfd0` |
| Installed callback | `081b710c` | `081c1228` | `081db40c` | `081dc214` |
| Message processor | `080eaa28` | `080eeb58` | `08105c98` | `08105e40` |
| Application vtable | `088ccd50` | `08958554` | `089819b4` | `0898961c` |
| Application event handler | `080f0828` | `080f4be8` | `0810bf6c` | `0810c160` |
| Host Preferences effect | `080ee9dc` | `080f2d1c` | `0810a0b0` | `0810a258` |

These are linked by actual ARM branch targets, literal loads, constructor stores
and initialized vtable words, rather than uniform relocation offsets. The
verifier executes the installer and its real callback-pointer setter, then the
event-posting helper, mapper, dispatcher, callback and command-emission wrapper.
With the readiness byte set, input event `0x11` becomes internal code `8` and
emits command **`0x63800026` to the application singleton**. The allocation/queue
builder is mocked at that final boundary. [Receipt: `installer`, `post_event`,
`event_mapper`, `dispatch`, `callback`, `emitter`][receipt]

The static queue builder creates a command event, then the queue-send routine
builds a `MsgS` record containing the application and event pointers. It requires
an available target queue and an eligible current message context. An initialized
12-byte dispatch-table row maps `MsgS` to the message processor; the exported
table-install routine supplies that table to the generic registration loop.
The processor compares the recipient's thread/context identity with the current
one. On equality it calls **recipient vtable `+0x30`**; on inequality it calls an
alternate method on the event. [Receipt: `enqueue_builder`, `queue_send`,
`message_table_row`, `message_table_install`, `message_table_register`,
`message_processor`][receipt]

The actual application constructor installs the vtable shown above. Its `+0x30`
entry recognizes command-event type `0x13` on 24 or `0x16` on the later three,
extracts the payload, and dispatches `0x63800026` to the Host Preferences effect.
Native cases execute that concrete route and separately verify the message
processor's same-thread and other-thread branches. Event allocation, type-cast
services and destruction are mocked. Queue acceptance, delivery timing, startup
ordering and the alternate callback's eventual effects remain OS scheduling
boundaries. [Receipt: `app_constructor`, `app_vtable`, `app_handler`,
`command_handler`; cases `message_thread_gate`][receipt]

## What changes in Preferences

Let `P` be the native Preferences context. The on-disk Preferences payload begins
at `P+4`, explaining the four-byte difference between file and context offsets.
The store's Preferences pointer is at `store+0xce8` on 24/33 and `store+0xf00` on
35/38. The Host effect performs these steps in order:

1. Mirror both current live clock-correction words into `P+b7c` and `P+b80`
   (file **`b78` and `b7c`**), marking dirty if either differs.
2. Reconcile the clock-settings model's city against live base offset and DST.
   If a selection is needed, save its city ID to `P+b74` (file **`b70`**), apply
   the selected zone, and mirror the resulting correction again.
3. Fetch live DST again, normalize nonzero to `1`, and save the byte at `P+b70`
   (file **`b6c`**).
4. Mark the Preferences context dirty unconditionally. The dirty byte is
   `P+b8c` on Classic24, `P+b90` on 33/35 and `P+b94` on 38; it is not a date field.

These are actual stores or transitive calls to exported, executed setters.
Marking dirty is not proof that a file flush has completed. A city selection can
also change the live correction before its second mirror, so the final saved
correction need not equal the first Host-command value. [Receipt: `host_effect`,
`mirror_bias`, `save_dst`, `save_city`, `dirty`, `select_city`][receipt]

The 80-byte Host effect SHA-256 values are:

| Target | SHA-256 |
| --- | --- |
| 24 | `e0ab219626279d5387a93fbcae7b217927e13a04f5043b7f8a4740842ec4f9c2` |
| 33 | `238af27c8b2edfeb84e77f20aefa5af217a3ef923717f2ca60073dcd37f16255` |
| 35 | `5f4c706347d2523bb0bb115858835c7f8cbeef98053a095e9f98142e383f43cf` |
| 38 | `335d1d0ddadcb43c15d7a05751a0a56c6cc5cbd527e06d4ff1381b8ba2f5a6d8` |

### Exact city policy

The reconciliation entry is `081488e0` (128 bytes) on 24, and `0814f160`,
`08166c0c`, `081673d0` (188 bytes each) on 33/35/38. [Receipt: `reconcile`][receipt]

| Decision | Classic24 | Classic33 / 35 / 38 |
| --- | --- | --- |
| Live clock metadata invalid | Return without selecting a city. | Same. |
| Current model city matches | Compare cached base offset only. | Compare base offset and the city's current-date DST predicate against boolean live DST. |
| Current model city differs | Reuse saved city if its base matches. | Reuse saved city if its base and DST predicate both match. |
| Saved city differs | Reverse lookup by base offset. | Reverse lookup by base offset and DST predicate. |
| Reverse lookup ordering | Preferred group first; then groups 1–8, skipping that group; first matching row. | Same, with additional DST test. |
| Reverse lookup fails | Pass city ID `0` to selection. | Same. |

The preferred group comes from a runtime setting through a switch; this report
does not assign an unverified language/locale meaning to that setting. The real
205-row city tables contain no ID `0`. With an unsupported base offset such as
32767 minutes, native reverse lookup returns `0`. Native city-base lookup for
ID `0` returns `0x7fffffff`; the selection routine narrows that to signed 16-bit
**-1 minute** and calls the zone-apply function without rejecting the ID.
This is a specific firmware fallback, not evidence that city zero represents UTC
or a valid city. [Receipt: `reverse_city`, `city_scan`, `city_table`, `city_base`,
`select_city`; cases `actual_city_table_unmatched_offset` and
`actual_select_missing_city`][receipt]

Classic24 selection retains the imported DST boolean in its city model and
converts it to `0/60` when applying the zone. Later selection asks the selected
city's date predicate again. The missing-city selection probe mocks that later
predicate to zero; it proves the unguarded ID/base handling, not the outcome for
every possible runtime DST resource. The seven reconciliation probes per target
also mock city-query results explicitly, separating branch-policy proof from
historical DST accuracy. [Verifier][script], [native cases][receipt]

## Zone event and registered observers

The clock-settings constructor calls the clock-model getter and registers itself
as an observer. Its installed vtable's `+0x30` handler recognizes event type
`0x10` on 24 or `0x13` on 33/35/38 and property code **`0x80a9`**. It invokes its
concrete mirror method at slot `+0xe8` on 24/33/35, **`+0xec` on 38**. [Receipt:
`settings_constructor`, `settings_vtable`, `settings_handler`][receipt]

| Target | Settings vtable | `0x80a9` mirror method |
| --- | --- | --- |
| 24 | `088d405c` | `08148f98` |
| 33 | `0895f9f8` | `0814f854` |
| 35 | `08988ee4` | `08167300` |
| 38 | `08990b58` | `08167b08` |

That method saves the **raw live DST byte** to file `b6c`. If it changes, the
method updates the city model's cached boolean; it also invalidates a separate
world-clock cache byte and emits property notifications `0x6094`, `0x6095` and
`0x6096`. It has no direct city-ID or correction-word store. With the actual
`0x2a2a2a2a / 0x80a9` notification payload, the two further generic settings
handlers take their nonmatching paths; their initialized singleton getter also
executes in the probe. The downstream property-notification method and
world-clock getter remain mocked. [Receipt: `mirror_live`, `generic_handler1`,
`generic_handler2`, `generic_singleton`; cases `zone_persist_dst_0/60`][receipt]

Three other concrete observer classes were connected to their registration
methods and `+0x30` handlers in all four images: the Calendar view, a city-clock
view/model, and the world-clock model. These are analyst descriptions. The
Calendar handler has a `0x80ab` day-change branch and a dynamic property-code
comparison; the city-clock handler has `0x80aa` and `0x80ab` branches; the
world-clock handler has a `0x80aa` branch and a base-handler delegation. Their
full transitive UI/delegate effects are not claimed closed. [Receipt:
`calendar_subscribe`, `calendar_vtable`, `calendar_handler`,
`city_clock_subscribe`, `city_clock_vtable`, `city_clock_handler`,
`world_constructor`, `world_vtable`, `world_handler`][receipt]

This is a bounded recipient graph, not an exhaustive dynamic subscriber list.
The receipt also records nearby clock-getter/registration call pairs. Proximity
alone is insufficient: for example, two Classic33 candidates replace the source
object with another model before registration. Generic observers, virtual
registration paths and resource-created objects can escape that search.
[Receipt: `nearby_clock_registration_candidates_not_all_preserve_source`][receipt]

## Smart reevaluation: what is and is not closed

The [previous observer report](classic-clock-change-observers-2026-11-05.md)
established that an actual membership evaluation creates a fresh, lazily sampled
day context. It also separated the protected-media cache update from ordinary
Track dates. This pass does not find a new ordinary Track date write in the
closed Preferences effect bodies. It does not claim that every indirect
notification recipient preserves every Track field.

The separately verified Smart refresh gates are `0804ac94`, `0804bf18`,
`080620a8`, `08062148`. An aligned ARM immediate-branch scan finds three direct
call sites for each: two Playlist selection/access paths and a list-enumeration
path. Their exported windows call refresh with `force = 0`; none is inside the
closed clock-settings or Host Preferences handlers. Existing Classic33 research
explains the additional readiness, live-update, dirty and reentry gates before
the synchronous `plsu` membership evaluation. [Receipt:
`smart_refresh_gate`, `smart_request_0/1/2`][receipt],
[Smart command and dirty-gate evidence][smart]

**Still unanswered for each of the four targets:** which clock/zone/day-change
notification, timer, or later UI action marks date-dependent Smart Playlists
dirty or requests refresh, and how promptly that refresh is scheduled. Native
context freshness on an evaluation is proved; immediate evaluation after a
clock change is not. An aligned direct-call scan excludes neither indirect
calls nor other instruction encodings or alternate membership entry points.

Also open for each target are exact queue-delivery ordering against `0x80a9`,
the final persisted DST representation when both routes run, full downstream
recipient effects, and the timing/success of the Preferences file flush. The
latest images have the same investigative coverage here, with the Classic24
city-policy and Classic38 virtual-slot differences recorded explicitly.

## Consequences for iOpenPod

Treat the saved city as firmware selection evidence, not proof of the user's
intended geographic timezone: the firmware can choose the first matching city
automatically or persist an invalid city zero after an unsupported offset.
Preserve raw saved DST and correction words when unchanged; derive a boolean
only where the model explicitly needs one. A normalization to `0/1` would lose
the distinction between the two observed firmware write paths. [Evidence above
and receipt][receipt]

The invalid-city fallback justifies an explanatory, nonblocking diagnostic and
best-effort time context. It does not justify emulating the firmware's -1-minute
fallback in Host timezone selection, rebasing existing Track dates, or blocking
load, Sync, playback-history import or Smart evaluation. Unknown event ordering
and remaining datetime uncertainty stay nonblocking under the user's explicit
policy and [ADR-0240](../adr/0240-treat-calendar-dates-as-best-effort-metadata.md).

[receipt]: ../../../ipod-firmware-lab/artifacts/classic-clock-notification-effects-20261105-v9/receipt.json
[script]: ../../../ipod-firmware-lab/scripts/check_classic_clock_notifications.py
[smart]: ../../../ipod-firmware-lab/notes/itunesdb/smart-reevaluation.md
