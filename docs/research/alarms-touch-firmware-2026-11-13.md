# Touch Nano countdown alarms and Sleep Timer

Investigated 2026-11-13 against the retained Nano 6, Nano 7 and 2015 Nano 7
firmwares. These devices expose a countdown timer that either sounds an alert or
puts the iPod to sleep. Its saved duration and deadline are distinct from a
Classic-style collection of Clock Alarms. This investigation performed no device
I/O and did not establish a mounted-file start, pause, cancel or reload protocol.

The [timer controls follow-up](timer-controls-touch-2026-11-13.md) subsequently
qualified saved duration, end-action and named sound editing, and traced the
native application initialization and restore boundaries. Its implementation
contract supersedes this report's initial read-only limit.

## Coverage and provenance

All local firmware paths below are relative to the sibling `ipod-firmware-lab`
repository. Each complete OSOS hash was recalculated in this pass. Function
addresses below are runtime addresses, using the main image's source offset zero
at `0x08000000`.

| Workspace | Updater / release / build | OSOS SHA-256 | Main mapped bytes |
| --- | --- | --- | --- |
| `Nano6FW` | 36 / 1.2 / 36B10147 | `d529680b7e7662876543d70b6941ddfac123d96c8ed1923432e4909909e896d8` | `0x88d9c0` |
| `Nano7FW` | 37 / 1.0.4 / 37A40005 | `4a55fffbf58cfd04a393e9a40c0c1c42471dfb34d11847b676b85f02a8019999` | `0x970380` |
| `Nano75FW` | 39 / 1.1.2 / 39A10023 | `ac4cf072d3c3f971b6acc03ed4f2ad1baa57d7bae20f89692bd6fb08d8a749e4` | `0x970740` |

The acquisition and verified startup-map records are the
[Nano 6 workspace](../../../ipod-firmware-lab/notes/nano6-firmware-workspace.md)
and [two Nano 7 workspaces](../../../ipod-firmware-lab/notes/nano7-firmware-workspace.md).
The new read-only audit compared every listed instruction byte in 24 selected
timer-function exports with its original OSOS: 860 bytes across eight Nano 6
functions, 828 across ten Nano 7 functions, and 740 across six refresh functions.
The reproducible private script and receipt are
`.scratch/alarms-touch-research/audit.py` and `native-byte-audit.json`.
This verifies the static evidence's byte provenance; it is not native execution
of the complete timer, audio or power-management graph.

## User-visible behavior

Apple's [Nano 6 User Guide, pages 45–46][manual6] and
[Nano 7 User Guide, pages 44–45][manual7] describe the same basic workflow:
open Clock from Home, swipe left twice to the timer, choose a duration, select
an alert or Sleep iPod, and start it. Nano 6 stops the timer with Stop; Nano 7
uses Cancel and labels its end-action control When Timer Ends. Both guides state
that the countdown continues when the device is off, but its alarm is then
inaudible. This supports device-specific guidance and the Sleep Timer capability;
it does not establish that writing saved XML starts a timer.

The Nano 7 document is Apple's current 2015 guide, matching the refreshed
product. The original and refreshed firmware timer paths were independently
inspected below. Neither guide describes a collection of recurring Clock Alarms.
Do not infer that collection from leftover Alarm strings in Nano 6's binary or
from the shared low-level alarm scheduler. Calendar support is separately
[declared false by these native firmwares](calendar-nano-coverage-2026-11-08.md).

The two PDFs were obtained from Apple's current document index on 2026-11-13.
Their SHA-256 values are `b8a49894d1c19d44c22ce2cd184c74e567c1be4f612486a4680af4b4d73eb23e`
(Nano 6) and `4e067a18f31322ced7c4641a62c03d77028d59fffb372d056dedcd88eaae4b87`
(Nano 7). Copies and extracted text remain private research artifacts.

## Saved files and fields

The ordinary store is `iPod_Control/Device/iPodSettings.xml`. Nano 6 additionally
uses `iPod_Control/Device/iPodTimerSettings.xml`. Both XML documents have the
`iPodSettings` root and `version="1.0"`; the second filename is not a different
XML root. The timer keys use a `Timer` group containing the named child elements.
The shared bounded named-settings parser already owns this framing.

| Saved key | Qualified domain and native default | Nano 6 location | Nano 7 and refresh location |
| --- | --- | --- | --- |
| `Timer.Hours` | Integer 0–23; default 0 | Ordinary store | Ordinary store |
| `Timer.Minutes` | Integer 0–59; default 15 | Ordinary store | Ordinary store |
| `Timer.DateTime` | String; default empty | Separate timer store | Ordinary store |
| `Timer.SleepiPod` | Boolean; default false | Separate timer store | Ordinary store |
| `Timer.SoundIndex` | Integer 0–24; default 0 | Separate timer store | Ordinary store |

These domains come from independently executed original registration routines,
with synthetic settings boundaries, in the
[native registration inventory][inventory]. Constructors and providers were
executed per image; their arguments, bodies and original hashes are recorded.
The prior [complete Preferences report](preferences-nano567-complete-2026-11-07.md#stores-and-registration-coverage)
details the ordinary and separate factories. In particular, Nano 6
[`0x0819ebfc`][factory6] creates the separate owner, while Nano 7
[`0x081e3e84`][factory7] and refresh [`0x081e3e9c`][factory75] obtain the ordinary
settings singleton. These are separate native paths, not inferred equality from
similar XML names. Missing captured fields must not be filled with the native
constructor defaults: a missing observation is not a saved preference.

## Deadline, lifecycle and end action

| Operation | Nano 6 | Nano 7 | Nano 7 refresh |
| --- | --- | --- | --- |
| Restore saved state | `0x0802be40` | `0x081eeb8c` | `0x081eeba4` |
| Start countdown | `0x080becc4` | `0x081eea1e` | `0x081eea36` |
| Deadline delivery | `0x080bed38` | `0x081eeab6` | `0x081eeace` |
| Cancel/reset | `0x082049b0` | `0x081eecea` | `0x081eed02` |
| Save state | `0x0819ed4c` | `0x083f283c` | `0x083f2854` |

Each address names its primary `.c` and `.asm.txt` exports under
`<workspace>/analysis/osos-corpus/functions/`. The new byte audit covers all
these functions. The important independently inspected paths are
[Nano 6 restore][restore6], [Nano 7 restore][restore7],
[refresh restore][restore75], [Nano 6 save][save6],
[Nano 7 save][save7] and [refresh save][save75].

The start functions calculate a deadline using the device's current calendar
coordinate plus the selected duration. Nano 6 multiplies hours by 3,600 and
minutes by 60. Nano 7 additionally carries seconds in its runtime object, which
allows a paused countdown to resume with seconds remaining. There is no captured
registered `Timer.Seconds` preference in these schemas. Nano 7 pause
`0x081ee9e4` obtains remaining components, unregisters the scheduled object,
changes runtime state to 2, and retains those components in memory. Do not
present the saved hour/minute preset as the current remaining duration.

All three writers emit a deadline only when object byte `+0x58` equals 1
(the active predicate). They format year, month, day, hour, minute and second as
`YYYYMMDDhhmmss`; inactive states produce empty text. This is a civil calendar
coordinate without an offset or timezone identifier. No Host timezone, UTC
instant or DST disambiguation follows from its spelling.

Restore loads the sound index and sleep flag independently. When the sleep flag
is true, it replaces the runtime sound selection with `-1`. It then parses a
nonempty deadline, compares it with the current device calendar and either
registers a future deadline or transitions to the expired state. Nano 6 uses
state 2 for expiration; Nano 7 uses state 3. Their save routines clear the saved
deadline when the object becomes inactive. The restored state is therefore a
persistence mechanism, not proof of a hot-reload command channel.

The end callbacks branch on the selected sound and sleep flag, call the audio or
sleep-related services, then leave the active state. Several additional runtime
guards can skip that delivery path. This pass does not give those untraced
guards UI names, guarantee audible delivery, or claim the full power-management
graph was executed. Likewise, `-1` is an internal sound sentinel, not an extra
qualified saved `SoundIndex` choice. The complete ordinal-to-alert mapping and
audio-route behavior remain unresolved.

The native component scanner does not check its conversion count in the traced
restore path. iOpenPod must validate independently and retain malformed input
without invoking timezone conversion or making Library loading depend on it.
Equal, past, reset-clock, DST-fold and reconnect scenarios still need physical
acceptance testing before any timer authoring workflow is qualified.

## iOpenPod implementation boundary

`iPodDB.alarms.timer.parse_countdown_timer` exposes an immutable
`CountdownTimerSnapshot`: saved hours/minutes, a parsed civil deadline and its
raw spelling, sleep choice, sound index and bounded interpretation issues.
It accepts an explicit firmware profile and separate captured stores. Nano 6
never imports running-state keys from the ordinary store; Nano 7 never imports
the Nano 6 sidecar. Unknown or missing values remain unknown, and an empty
deadline is distinguishable from an absent deadline.

The codec uses the existing bounded XML framing and registered numeric domains.
It rejects ambiguous sections, duplicate fields, structured scalars, invalid
calendar components and unrecognized scalar spellings without blocking other
valid observations. It has no writer and makes no claim that a timer is running.
Twenty-three focused cases cover the three profiles, store separation,
missing/empty state, DST-fold civil coordinates, unknown scalars and unsafe XML.

The Alarms page can therefore display saved timer observations and the relevant
on-device controls. Starting, stopping, pausing or canceling remains on the iPod.
No Host countdown should be substituted. Further authoring requires a concrete
adoption protocol, coupled state validation and live-device acceptance.

## Lab inventory limits and Nano 2 behavior

Inspection of all lab family directories and retained IPSWs found 17 firmware
workspaces: Mini 1/2; Video 13/20/25; Classic 24/33/35/38; and Nano 1/2/3/4/5/6/7
plus the 2015 refresh. They represent 20 updater package identities because
Mini 1 has families 3/6, Nano 1 has 14/17, and Nano 2 has 19/29. Duplicate
acquisition copies and the deliberately invalid Nano 1 test package add no
coverage. No early full-size iPod, Shuffle or iPod touch firmware workspace was
present. This task's firmware coverage must not imply those absent families or
every historical firmware revision was reverse engineered.

Nano 2 remains encrypted-only in its workspace. Its original Apple-authored
[Features Guide, page 38][manual2] nevertheless establishes native per-city
Clock Alarms: select a clock under Extras, open Alarm Clock, enable it, set the
time and select Beep or a Playlist. It also documents a Sleep Timer under that
clock. The current Apple legacy PDF URL redirects to the general document index;
the linked copy is an intact mirrored Apple manual, not a firmware format source.
This is evidence for capability/guidance only. It does not qualify a binary
record layout or permit borrowing another Nano's writer for updater 19/29.

[manual6]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma1551_ipod_nano_6thgen_user_guide.pdf
[manual7]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma1624_ipod_nano_2015_user_guide.pdf
[manual2]: https://i.smartphone.ua/docs/instr_pleer/instr_apple-ipod-nano-2g-2gb_eng.pdf
[inventory]: ../../../ipod-firmware-lab/artifacts/nano567-preferences-complete-20261107-final-inventory-v3/inventory.json
[factory6]: ../../../ipod-firmware-lab/Nano6FW/analysis/osos-corpus/functions/0819ebfc.c
[factory7]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/081e3e84.c
[factory75]: ../../../ipod-firmware-lab/Nano75FW/analysis/osos-corpus/functions/081e3e9c.c
[restore6]: ../../../ipod-firmware-lab/Nano6FW/analysis/osos-corpus/functions/0802be40.c
[restore7]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/081eeb8c.c
[restore75]: ../../../ipod-firmware-lab/Nano75FW/analysis/osos-corpus/functions/081eeba4.c
[save6]: ../../../ipod-firmware-lab/Nano6FW/analysis/osos-corpus/functions/0819ed4c.c
[save7]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/083f283c.c
[save75]: ../../../ipod-firmware-lab/Nano75FW/analysis/osos-corpus/functions/083f2854.c
