# Classic Auto appearance: native clock and UI timer

Date: 2026-11-17. Scope: shared Classic 2.0.5, Auto appearance with Light from
07:00 inclusive until 18:00 exclusive. No device was accessed.

Use the native adjusted Firmware Calendar and the existing UI model's clock
timer. Read the clock on the UI event-delivery path, after preserving its native
timer rearm. This requires no additional timer, alarm, worker thread or scheduled
preference writes. A time change is reflected on the next delivered clock tick;
immediate repaint before the first tick after wake is not established.

## Pinned inputs and tests

The primary source is the exact Apple executable. Existing lab research
`scripts/check_later_classic_calendar_contracts.py` and
`scripts/check_classic_clock_observers.py` supplied discovery coordinates;
the instructions and ABIs below were checked independently on 2.0.5. Prior
annotations come from
[osos-lab d2c8e357](https://github.com/lgreitis/osos-lab/tree/d2c8e357d58591bdaa70bb6be9da191f489554a6).

| Input | SHA-256 |
| --- | --- |
| Lab `Classic38FW/decrypted/osos.bin` | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |
| Prepared stock 2.0.5 | `660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e` |
| 0.4.3-dev build-2 OS | `aded6a1559bf767092701139c2abc4ac16a7e697ad74e3160f0aaeae8913fd7c` |
| 0.4.3-dev build-2 payload | `86020fbfe2dfa1e4425c2e3a480b8d18d2c79bdbecc0a54c1b3a36b1e353132c` |

Raw file offset `0xaf98` maps to DRAM `0x08000000`; prepared/modded images use
`0xb798`. The ignored native reproduction is:

```shell
uv run .scratch/classic-dark-native-20261117/probe_auto_appearance.py --build .scratch/classic-auto-appearance-20261117/build-2
```

Its adjacent `auto-native-report.json` records ten native calendar cases, three
stock timer-dispatch cases, native Settings interface lookup, timer queue capture
and posting, and six cases through the actual compiled hook. It executes ARM
instructions, with synthetic RTC input, queue/locking boundaries, model-refresh
dependencies and final notification recipients. It does not emulate hardware
sleep, an entire booted GUI, or task scheduling.

## Read the displayed local calendar

`0x08059408(out)` fills a 12-byte calendar. Treat its return as unused:
the final tail call computes a calendar ordinal, rather than returning a useful
clock-read status. Initialize the output buffer before calling.

| Offset | Meaning |
| --- | --- |
| `+0`, 16 bits | Full year |
| `+2`, `+3` | Binary month, day |
| `+4`, 16 bits | Derived day within year |
| `+6`, `+7` | Live offset/DST metadata |
| `+8`, `+9`, `+10` | Binary hour, minute, second |
| `+11 & 1` | Calendar time-valid flag |
| `+11 & 2` | Separate metadata-valid flag |

The bridge calls `0x080592f0(0, out)`. That reader samples the raw RTC through
`0x082dc324`, converts its packed BCD fields to a day/seconds pair, adds the
software bias at `0x089d30e4`, and converts back. The bridge supplies metadata
from `0x08a6e938`. The displayed clock uses this same bridge through
`0x0804b678` and compact-calendar helper `0x08083ba4`.

Consequently Auto must not add the zone or DST offset a second time, substitute
Host time, or read the raw RTC directly. Validate the time flag and component
ranges; retain the current effective appearance on invalid data. The higher
`0x0804b678` wrapper substitutes midnight when time is invalid, which is why the
12-byte bridge is preferable here.

Native tests covered 06:59:59, 07:00:00, 17:59:59, 18:00:00, midnight, 23:59:59,
positive and negative one-hour software biases, and a bias crossing midnight.
A simulated raw-provider error clears time validity even when metadata remains
valid. This verifies the native conversion and validity behavior without
claiming the synthetic RTC is a physical measurement.

## Reuse the UI clock timer

The exact patch site is `0x0817e320`, originally ARM word `0xebfffcf0`
(little-endian bytes `f0fcffeb`), a call to `0x0817d6e8(model)`. The installed
build-2 word is `0xeb26fb04`, targeting the compiled appearance wrapper.

Native event handler `0x0817e23c` reaches this call only when event word `+4`
is `0x0f` and event pointer `+8` equals `model+0x11c`. The derived handler
`0x081c0c98` delegates this event to it. The preceding clock-model refresh at
`0x0817e318` can be skipped by a native guard; the rearm call still runs.

`0x0817d6e8` sets the timer period from `model+0x148`, then starts the timer
through `0x08121268`. The constructor's default period is 60,000 milliseconds.
Native `0x0817d800` can select a 500-millisecond period or align the first
60,000-millisecond tick using the current second. The patch preserves all of
these choices and adds no wake source.

The wrapper first calls the original rearm routine, preserves its return value,
then polls appearance. Native compiled-path tests confirm that ordering, the
event's return value of one, stack restoration, and unchanged selected Auto
mode. They also confirm both scheduled transitions, polling despite the native
refresh guard, and no polling for an unrelated timer or event.

## Why bitmap writes remain on the UI thread

This is a queued UI timer, not a callback executed by the timer worker:

1. `UI_InitializeEventTimer` at `0x0810635c` enters `0x0812197c`, which stores
   recipient `+0x24` and queue `+0x28`. A zero queue argument captures the
   creator's current context queue through `0x080c09f4`, field `+0x1c`.
2. Worker `0x08121504` constructs a `time` packet and posts it to that stored
   queue through `0x081213a4`; it does not invoke the model directly. Native
   probes verify queue identity and the packet's timer pointer.
3. Static startup evidence identifies the creator: `0x081391b8` registers the
   21-entry factory table at `0x089d4cec` and launches `MP3ExampleTask`, entry
   `0x08139118`. That entry constructs the UI controller and invokes virtual
   `+0x204` at `0x08139168`, resolving to `0x081c7734`.
4. Its `+0x208` method resolves to `0x081c7960`, whose table loop invokes each
   factory at `0x081c798c`. The first factory pointer at `0x089d4cf4` is
   `0x0817da84`, constructing the model through `0x081c0dc4` and `0x0817e3a8`.
   That constructor creates the clock timer with queue argument zero.
5. The same task subsequently runs the UI loop `0x08288a94`; its event processing
   includes `0x081215d8` at `0x08288b98`.

This instruction chain ties timer creation and delivery to the existing UI
execution context. It is static ownership evidence plus native queue-contract
tests, not an observed operating-system thread trace. The patch does not move
palette writes into the RTC getter, timer worker or manual clock-change callback.
It retains the same UI ownership assumption as the existing manual appearance
switch, documented in the
[switching audit](classic-appearance-switching-2026-11-17.md).

## Settings preview notifications without retaining a controller

Settings constructor `0x081e4010` installs vtable `0x08997afc` and registers
itself as service `0x8900` at `0x081e403c..0x081e4040`. Registry lookup
`0x081c7d44(0x8900)` can therefore obtain the current object for each transition.

Vtable `+0x14` is `0x081e0fac`: interfaces `0x8900`, `6`, and `5` return the
same object pointer without retaining it. Vtable `+0x58` is the native property
notifier `0x08268cf8`. A native interface-5 probe confirms the unchanged pointer
and absence of subsidiary calls. This supports notifying the current Settings
preview model without caching a potentially stale controller `+0xb0` pointer.

## Integration boundary

Persist selected Light/Dark/Auto separately from effective Light/Dark. Scheduled
transitions change only effective appearance, notify the Settings preview and
existing Now Playing properties, and invalidate the root. Manual Light/Dark
polls can return before reading the clock; unchanged Auto polls need no artwork
mutation, notification or preference I/O. The implementation lives in
[appearance.c](../../scripts/firmware/classic_about/appearance.c).

Stationary menus use the existing periodic event. After manual clock changes or
sleep/wake, reevaluation occurs on the next delivered clock tick. These tests do
not establish exact wake latency or behavior while the UI task is suspended.
No timer is added solely to wake the device for a theme change.
