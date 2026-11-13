# Touch Nano timer presets, sound catalog and adoption

Investigated 2026-11-13. Nano 6, Nano 7 and the 2015 refresh have authorable
saved timer presets: duration, alert sound and Sleep iPod. These are native
settings with bounded domains, not device-only choices. This follow-up qualifies
lossless edits to existing settings and traces their native adoption mechanism.
It supersedes the earlier read-only implementation limit in
[the initial touch alarm investigation](alarms-touch-firmware-2026-11-13.md).

The later [reload and delivery investigation](timer-reload-and-delivery-2026-11-13.md)
traces post-import retained saves, delayed dirty-save tasks and guarded expiration.
It narrows this report's USB/adoption unknowns without establishing a live
mounted-file Start/Cancel command or physical wake/audio reliability.

## Exact sources and reproducibility

The sources are the same independently hashed images in the initial report:
Nano 6 updater 36, version 1.2/build 36B10147; Nano 7 updater 37, version
1.0.4/build 37A40005; and refresh updater 39, version 1.1.2/build 39A10023.
Addresses are original runtime addresses with source offset zero at
`0x08000000`. Paths below are relative to the sibling `ipod-firmware-lab`.

`scripts/probe_touch_timer_controls.py` verifies each image hash, then executes
bounded original Thumb instructions under Unicorn. The receipt is
`artifacts/timer-controls-touch-20261113-v3/native.json`. For each image it covers
25 native tone label lookups, three duration writes, three mode selections,
four signed sound-domain cases, eight restore-state cases and two invocations
of the real settings-load wrapper: 135 executions across the three images.

Filesystem loading, settings access and external notifications are explicit
synthetic boundaries. The probe does not emulate a complete boot, audio device,
USB connection or physical scheduler. Its separate `initialization_audit`
captures 1,458 original instruction bytes, their SHA-256 hashes and disassembly,
plus the Clock initialization vtable binding. This includes vtable-only
functions absent from the automatic Ghidra function/call exports. An absent
export was not treated as evidence that a caller does not exist.

## Saved preset contract

| Field | Domain | Nano 6 store | Nano 7 and refresh store |
| --- | --- | --- | --- |
| `Timer.Hours` | integer 0–23 | `iPodSettings.xml` | `iPodSettings.xml` |
| `Timer.Minutes` | integer 0–59 | `iPodSettings.xml` | `iPodSettings.xml` |
| `Timer.SleepiPod` | boolean 0/1 | `iPodTimerSettings.xml` | `iPodSettings.xml` |
| `Timer.SoundIndex` | integer 0–24 | `iPodTimerSettings.xml` | `iPodSettings.xml` |
| `Timer.DateTime` | empty or civil `YYYYMMDDhhmmss` deadline | `iPodTimerSettings.xml` | `iPodSettings.xml` |

Both files reside in `iPod_Control/Device`, using the named settings XML format
documented in the initial report. Duration defaults are 0 hours and 15 minutes;
an absent captured value is still unknown to the host. There is no persistent
seconds field. A saved deadline is independent of the duration preset.

The native duration selector writes Hours and Minutes through the ordinary
settings integer setter. The native Sleep iPod selector sets the timer object's
sleep byte and runtime sound word to `0xffffffff`. The sound selector sets the
sound word and clears the sleep byte. Their UI callbacks invoke the timer saver.
The saver attempts to persist both fields, but the generic signed integer setter
rejects `-1` for SoundIndex's 0–24 domain. Consequently selecting Sleep iPod
retains the last valid saved sound; selecting a tone clears SleepiPod. The probe
starts the registered sound scalar at 7 and independently verifies rejection of
both -1 and 25, and acceptance of 0 and 24, in all three images.

| Native operation | Nano 6 | Nano 7 | Refresh |
| --- | --- | --- | --- |
| Duration constructor/read | `0x0803b548` | `0x08242db4` | `0x08242dd4` |
| Duration write | `0x080a19b8` | `0x08242b2c` | `0x08242b4c` |
| Select Sleep iPod | `0x080bed22` | `0x081eea80` | `0x081eea98` |
| Select sound | `0x080bed2e` | `0x081eeaa0` | `0x081eeab8` |
| Persist timer state | `0x0819ed4c` | `0x083f283c` | `0x083f2854` |
| Generic signed integer setter | `0x0816eaa8` | `0x08454020` | `0x08454020` |

Nano 6 timer persistence invokes the store's save method immediately. Nano 7's
timer saver updates the shared settings owner; that owner's save method
`0x08454860` schedules `PodSettingsTask` when dirty. This is native persistence
behavior, not a host acknowledgement protocol. The native saver may also
rewrite DateTime to reflect its runtime state; the host preset writer instead
preserves the captured DateTime bytes because it does not own that runtime.

## Actual alert sound catalog

Every native label getter indexes an eight-byte pair: string-resource ID followed
by a filename pointer. The native playback path uses the same indexed filename
under `Resources/Sounds`. This binds display names to audio resources; the names
were not inferred from a shared iPhone ringtone list.

| Image | Pair table | Label getter | First–last English resource ID |
| --- | --- | --- | --- |
| Nano 6 | `0x08846f1c` | `0x081cb45c` | `0x0dad0b30`–`0x0dad0b48` |
| Nano 7 | `0x08908a90` | `0x081bd8d8` | `0x0dad0a62`–`0x0dad0a7a` |
| Refresh | `0x08908e60` | `0x081bd8dc` | `0x0dad0b19`–`0x0dad0b31` |

The probe executes all 25 getters against each image, reads that image's English
string bank and joins the matching filename pointer. All three agree:

| SoundIndex | Display label | Native filename |
| --- | --- | --- |
| 0 | Marimba | `marimba.m4a` |
| 1 | Alarm | `Alarm.m4a` |
| 2 | Ascending | `Ascending.m4a` |
| 3 | Bark | `Bark.m4a` |
| 4 | Bell Tower | `Bell Tower.m4a` |
| 5 | Blues | `Blues.m4a` |
| 6 | Boing | `Boing.m4a` |
| 7 | Crickets | `Crickets.m4a` |
| 8 | Digital | `Digital.m4a` |
| 9 | Doorbell | `Doorbell.m4a` |
| 10 | Duck | `Duck.m4a` |
| 11 | Harp | `Harp.m4a` |
| 12 | Motorcycle | `Motorcycle.m4a` |
| 13 | Old Car Horn | `Old Car Horn.m4a` |
| 14 | Old Phone | `Old Phone.m4a` |
| 15 | Piano Riff | `Piano Riff.m4a` |
| 16 | Pinball | `Pinball.m4a` |
| 17 | Robot | `Robot.m4a` |
| 18 | Sci-Fi | `Sci-Fi.m4a` |
| 19 | Sonar | `Sonar.m4a` |
| 20 | Strum | `Strum.m4a` |
| 21 | Timba | `Timba.m4a` |
| 22 | Time Passing | `Time Passing.m4a` |
| 23 | Trill | `Trill.m4a` |
| 24 | Xylophone | `Xylophone.m4a` |

The count getters return 25 (`0x081cb468`, `0x081bd8ca`, `0x081bd8ce`).
Nano 6 playback `0x081e67fc` indexes the filename member from the global table
base plus `0x20 + index * 8`; Nano 7/refresh use the corresponding member at
global base plus `0x28 + index * 8`. Sleep iPod is a separate action, not sound
index 25 or a serialized `0xffffffff` sound.

## Concrete adoption mechanism

The proven load point is native system-application initialization. It is not a
new settings read on every visit to the timer screen.

For Nano 7, system initialization `0x08242668` invokes the system application's
create, initialize, post-initialize and finish phases through vtable slots
`0x10c`–`0x11c`. Creation `0x08242754` constructs the registered applications,
then calls the ordinary settings singleton `0x0841cfa8` and its load method
at slot `0x7c` (`0x082427c8`–`0x082427d0`). Initialization
`0x08242974`, identified by its `InitializeAllApplications` trace string,
iterates the applications and invokes each slot `0x74`.

Clock's vtable at `0x087e9008` binds that slot to `0x084a047c`. That callback
registers observers, loads the city clocks, obtains the timer owner and directly
calls timer restore `0x081eeb8c` at `0x084a04cc`. The refresh independently has
system initialization `0x08242688`, creation `0x08242774`, initialization
`0x08242994`, Clock vtable `0x087e9078` and the same callback address; its
branch at `0x084a04cc` reaches its own restore `0x081eeba4`.

Nano 6 has the corresponding creation/loading phase at `0x08242c38`:
`0x08242cba`–`0x08242cc2` invokes the ordinary settings load method.
`InitializeAllApplications` at `0x08243060` dispatches application slot `0xbc`.
Clock's vtable at `0x086eb1e4` binds that slot to `0x08025754`, which obtains
the timer and calls restore `0x0802be40`. Its timer restore loads the separate
timer store, in addition to the earlier ordinary store load.

Duration models are cached singletons (`0x081ac754`, `0x08242b10`,
`0x08242b30`). Their constructors read the loaded Hours and Minutes fields.
Nano 7's finish phase `0x081d42a8` constructs the duration model after the
earlier settings load. Re-entering the screen retrieves the singleton; it does
not itself rerun the duration constructor. This is why a successful host save
must not be reported as a change to the currently displayed native duration.

The settings load wrappers are real reloads: Nano 6 `0x0804e7a4` calls XML
loader `0x08083488`; Nano 7/refresh `0x0845480c` call `0x081c37f0` /
`0x081c37f4`. They lock the owner, load from the filesystem and notify registered
observers. There is no once-only load guard. The native probe invokes each
wrapper twice and observes two loader calls. However, that says what happens
when the wrapper is called; it does not create a host-triggerable invocation.

## Restoring a deadline is different from editing a preset

All three restore routines first test the timer's runtime state byte at offset
`0x58`. If it equals 1, they return **before loading any file or reading any
setting**. Eight native cases per image exercise state values 0, 1, 2 and 3
with both saved SleepiPod values and confirm that boundary.

For an inactive timer, restore loads its store, then reads SoundIndex, SleepiPod
and DateTime. It applies the selected action; SleepiPod maps to runtime sound
`0xffffffff`. A nonempty future DateTime is parsed as civil time and registered
with the alarm scheduler, with runtime state changed to 1. A past deadline
takes the expired-state path (2 on Nano 6, 3 on Nano 7). Thus persisted DateTime
can participate in arming a timer when the native restore path actually runs.
An empty DateTime skips that registration; it is not a cancel command delivered
to an already active timer, whose restore returns before reading it.

The initialization graph provides a concrete explanation of adoption during
native application initialization, including a fresh startup. This pass did not
establish a USB-eject event dispatching that graph, an ordinary screen-entry
reload, or a mounted-file runtime command. The inspected Clock event handler
on Nano 7, `0x084a0510`, handles clock/date notifications rather than restoring
the timer. The full hardware boot/eject graph was not executed. These are
specific integration limits, not evidence that saved preset authoring is
unsupported or that a future persisted-deadline workflow is impossible.

## iOpenPod implementation contract

The pure `iPodDB.alarms` interface exports `CountdownTimerChanges`,
`CountdownTimerFiles`, `patch_countdown_timer` and the indexed
`COUNTDOWN_TIMER_SOUNDS` catalog. The parsed snapshot reports independent
`can_edit_duration`, `can_edit_sleep` and `can_edit_sound` availability, so the
application does not duplicate XML interpretation.

Only the three exact qualified profiles may use this writer. It patches
existing unique plain scalars, changes no absent field, preserves Unknown Data
and retains untouched bytes, including DateTime. Selecting a sound also clears
SleepiPod; selecting Sleep iPod retains the saved sound. Ambiguous fields,
missing coupled fields and invalid requested values are rejected. Native
defaults do not authorize creating an absent captured document.

The application must bind edits to captured sources and publish through Storage.
Nano 6 can change two independent files in one preset operation. The successful
result is a saved preset; it does not assert that the device adopted it, report
a running status, or issue Start, Pause or Cancel. The current writer deliberately
has no DateTime edit API. The evidence for duration, end-action and tone editing
is sufficient independently of those remaining runtime integration questions.
