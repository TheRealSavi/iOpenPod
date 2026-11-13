# Touch Nano timer reload, retained saves and delivery

Investigated 2026-11-13. This follows
[the timer preset and adoption investigation](timer-controls-touch-2026-11-13.md).
The mounted XML files hold real native settings, but writing them does not
invoke the native timer's Start, Cancel or delivery methods. This investigation
identifies a concrete reason why disconnect alone is insufficient evidence of
adoption: the traced media-import completion paths save retained settings, while
the settings loader and Clock restore belong to separate initialization paths.

The result supports the existing saved-preset editor. It does not yet support
promising that changing a persisted deadline starts or stops a running timer.
No product source or physical device was changed for this investigation.

## Exact sources and reproducibility

All paths in this section are relative to the sibling `ipod-firmware-lab`.
Original runtime address `0x08000000` corresponds to file offset zero.

| Image | Version/build | Original `decrypted/osos.bin` SHA-256 |
| --- | --- | --- |
| `Nano6FW`, updater 36 | 1.2 / 36B10147 | `d529680b7e7662876543d70b6941ddfac123d96c8ed1923432e4909909e896d8` |
| `Nano7FW`, updater 37 | 1.0.4 / 37A40005 | `4a55fffbf58cfd04a393e9a40c0c1c42471dfb34d11847b676b85f02a8019999` |
| `Nano75FW`, updater 39 | 1.1.2 / 39A10023 | `ac4cf072d3c3f971b6acc03ed4f2ad1baa57d7bae20f89692bd6fb08d8a749e4` |

[The native probe script](../../../ipod-firmware-lab/scripts/probe_touch_timer_reload_delivery.py)
verifies each complete original image hash before mapping its main executable.
It executes original bounded
instructions using pinned Unicorn 2.1.4 and Capstone 5.0.7. The final receipt is
[the v5 native receipt](../../../ipod-firmware-lab/artifacts/timer-reload-delivery-20261113-v5/native.json).

- Script SHA-256: `22e275bfd143525a201b31403f3ab30e854a4739a3ff4515caadf771abf2459e`.
- Receipt SHA-256: `8cebb5a36992938b935a9a793f7605d6231f9a191c9a8141e5edd801409da8fc`.
- 167 original bounded executions: 129 delivery cases, 10 dirty-save cases,
  12 terminal savers, 12 observer/callback invocations, and four USB event
  emitter cases. The receipt records mapped-image and instruction-span hashes.
- Reproduce with `uv run scripts/probe_touch_timer_reload_delivery.py`
  followed by a new output JSON path. Existing receipts cannot be overwritten.

Service objects, filesystem operations, queues, settings setters and external
notifications are explicit synthetic boundaries. Delivery tests capture the
native call to the saver; the separate terminal-save tests execute that original
saver and its original empty-string accessor, then capture the setting writes.
They do not execute a physical disk write. The guard truth table deliberately
includes synthetic combinations that need not occur on hardware. In particular,
Nano 7/refresh interface-guard value 1 is unreachable through the exact
constant-zero implementation identified below.

Additional evidence is in the Nano 7 exports
[stage 1](../../../ipod-firmware-lab/artifacts/timer-reload-delivery-20261113-v1/nano7-stage1.txt),
[stage 2](../../../ipod-firmware-lab/artifacts/timer-reload-delivery-20261113-v1/nano7-stage2.txt),
[stage 3](../../../ipod-firmware-lab/artifacts/timer-reload-delivery-20261113-v1/nano7-stage3.txt),
[stage 4](../../../ipod-firmware-lab/artifacts/timer-reload-delivery-20261113-v1/nano7-stage4.txt) and
[stage 5](../../../ipod-firmware-lab/artifacts/timer-reload-delivery-20261113-v1/nano7-stage5.txt);
the [refresh export](../../../ipod-firmware-lab/artifacts/timer-reload-delivery-20261113-v1/nano75-stage1.txt);
and the Nano 6 exports
[stage 1](../../../ipod-firmware-lab/artifacts/timer-reload-delivery-20261113-v1/nano6-stage1.txt),
[stage 2](../../../ipod-firmware-lab/artifacts/timer-reload-delivery-20261113-v1/nano6-stage2.txt) and
[stage 3](../../../ipod-firmware-lab/artifacts/timer-reload-delivery-20261113-v1/nano6-stage3.txt).
The hash-guarded
[Ghidra exporter](../../../ipod-firmware-lab/scripts/ghidra/TouchTimerReloadExport.java)
generated these using
`-readOnly -noanalysis`; project changes were discarded. It recovered several
vtable-only functions missing from the automatic function corpus. The ordinary
`analysis/osos-corpus/functions/<address>.c` and `.asm.txt` files remain useful,
but their missing call edges and occasional shared-tail ownership errors are
not evidence of absent native paths.

## Initialization and disconnect are distinct dispatches

The previous report established original initialization order and the timer's
active-state early return. The additional trace resolves the important
post-import dispatch rather than treating all lifecycle methods as equivalent.

### Nano 7 and refresh

The native provider is `MP3Player_P68_Plugin`, vtable `0x087ac0e4` in Nano 7.
Its initialization slot `+0x70` calls `0x08254f38`, which registers callback
`0x08255074`. That callback emits subject events through `0x083a9f1a`:
input 8 calls `0x081ebf60` and emits `0xa0000003`; input 9 calls `0x081ebde4`
and emits `0xa0000004`. The original callback and emitter instructions execute
in the probe. Refresh uses callback `0x08255094`, emitters `0x081ebf78` /
`0x081ebdfc`, and notification boundary `0x083a9f3a`.

The following Nano 7 route is traced statically through the recovered dispatch:

1. Media event dispatcher `0x081b08c4` handles `0xa0000004` by invoking
   `0x081b0e64`. When its media-loading flag at `app+0x40d` is clear, this
   calls `0x081e15ec`, whose controller route sends `SwitchToDisconnected`,
   and starts the embedded timer at `app+0x6d8`.
2. Timer dispatcher `0x081b0b74` routes that timer to `0x081b0d94`. If an
   existing loading task remains, it restarts the timer. Otherwise it calls
   `0x081b1790`, the provider's `+0x8c` method, and a property notification.
3. `0x081b1790` checks the loading flag and provider `+0x98` eligibility.
   It queues system event 6, transitions the media state to `0x2f`, constructs
   `TMusicLoadingTask` through `0x0822bce8`, starts that task and the timer at
   `app+0x718`, then sets the loading flag.
4. The latter timer reaches `0x081b143c`. When the task finishes it calls
   `0x081b15bc`. This invokes `0x081b0fc0`, which calls `0x08242ab0`.
   **That dispatch is system application slot `+0x11c`, not initialization
   slot `+0x110`.** Its implementation `0x0824285c` advances the post-import
   application state and, conditionally, queues the `0x081df808` task.
   It does not invoke the settings loader or Clock restore.
5. Completion also calls `0x0810d35c`, which flushes media state and invokes
   `0x08454724` on the retained ordinary settings singleton. That is a
   dirty-gated synchronous save, detailed below.

The corresponding refresh functions were exported separately. The media
dispatch/completion functions above move by `+4`, while the system post-import
dispatcher is `0x08242ad0` and implementation is `0x0824287c`. The settings
save wrapper remains `0x08454724`. The refresh export verifies the same
post-import slot and retained-save behavior; this is not inferred merely from
the product's shared name.

There is a separate connected/disk-mode route: Nano 7 event `0xa0000003`
enters `0x081b16cc`, reaches the connected UI, and uses provider `+0x88`.
Its deferred unload route reaches `0x081b072c` and `0x081b13dc`; media teardown
at `0x0865d1ac` conditionally invokes the same `0x0810d35c` flush. These are
additional retained-save opportunities around media ownership changes.

### Nano 6

Nano 6 also has `MP3Player_P68_Plugin`, at vtable `0x086a8294`.
Initialization slot `+0x74`, `0x0803ba54`, registers callback `0x0804b260`.
Its Thumb switch uses an ARM switch helper, which the automatic decompiler did
not reconstruct completely. Raw instruction/table inspection resolves the
event-8 and event-9 routes to emitters `0x08057600` and `0x080574c4`; these
emitters were exported, but this older callback is not one of the four
executed USB probe cases.

The independently traced post-import path is:
`0x08045fd4` → `0x081b9ed2` → `0x080994a8` → `0x080bc0e4` →
`TMusicLoadingTask` constructor `0x080cfe7c`. The task sets `app+0x49d` and
starts timer `app+0x880`. Dispatcher `0x08038390` routes that timer to
`0x08046398`, whose completion calls `0x0805442c`.

Completion calls `0x08081a84` → `0x080a19a0`, dispatching system slot
`+0x194`, and `0x081bef28`, which invokes ordinary settings virtual `+0x80`.
This is again a retained save. It is distinct from the already-proven
`InitializeAll` dispatch at `0x08243060` and Clock initialization at
`0x08025754`. The exact Nano 6 event-9-to-media-handler edge remains less
complete than the Nano 7/refresh route; no assertion that every Nano 6 USB
event path has been exhausted follows from this trace.

### What this proves about reload

The concrete post-import routes above do not call the native XML loader or
Clock restore. The known ordinary load methods are Nano 6 `0x0804e7a4` and
Nano 7/refresh `0x0845480c`, virtual `+0x7c`. Their original instructions
load the document and then invoke registered callbacks with argument 0.
The ordinary store load occurs during application creation; the separate
Clock initializer restores the countdown afterward. Native save notifications
use argument 1. These directions must not be conflated.

This is bounded negative evidence for the traced route, not proof that no
other callback, accessory path or system transition can reload settings.
Physical USB detach, host eject, firmware reset and cold initialization are
also different events. This investigation does not establish that any one
host action necessarily produces a fresh Clock initialization.

## Retained-state overwrite mechanisms

### Nano 7/refresh: observer, delayed task and synchronous flush

`TSettingsApp` constructor `0x081c36fc` creates an embedded timer at `app+0x40`,
sets its duration to 2,000 milliseconds, and subscribes its observer to the
ordinary settings singleton. Its observer dispatch reaches `0x081c34c8`:
event `0x190001` restarts that timer through `0x08424848`; neighboring event
IDs do not. The timer callback `0x081c36b4` dispatches settings virtual
`+0x80`, the asynchronous save wrapper `0x08454860`. Refresh uses constructor
`0x081c3700`, observer `0x081c34cc`, restart `0x0842484c` and callback
`0x081c36b8`. The observer and save callback are separately exercised.

`0x08454860` checks dirty byte `settings+0xac`. If clear it returns without
queueing. If set it updates the build-version field, locks the store, creates
`PodSettingsTask`, queues it, clears the dirty byte and unlocks. The dirty byte
is still 1 at the captured queue boundary, then becomes 0. The task's callback
`0x0845ac7a` calls `0x0845cdf0`, which invokes the ordinary XML saver and then
the store's save observers with argument 1.

The synchronous wrapper `0x08454724` also checks dirty, but invokes
`0x0845cdf0` before clearing it. The post-import/media flush invokes this
synchronous wrapper. The asynchronous task, once queued, is not a captured
snapshot of the changed timer fields: `0x081c3a28` obtains the retained
settings singleton when it runs and serializes the full registered store via
`0x08453c18`. Its source is current retained values, not a reread or merge of
the host-edited XML. Refresh uses XML saver `0x081c3a2c` with the same serializer.

Consequently, a pending task or a later native setting change can replace host
edits with retained values. A clean synchronous flush does nothing; it is
incorrect to claim every disconnect always overwrites the XML. The scheduler
and filesystem ownership guards determine physical timing, which was not
emulated here.

### Nano 6: named stores and immediate timer persistence

Nano 6's shared settings virtual `+0x80` is `0x08064fac`. It checks dirty byte
`+0xac`, updates the build version, locks, calls `0x081dae64` with that store's
name, invokes registered save callbacks with argument 1, clears dirty and
unlocks. The probe executes both dirty and clean paths. Its serializer
`0x08064cb0` emits the retained values for the selected named store.

The distinction between Nano 6's two files matters:

- `iPodSettings.xml` holds `Timer.Hours` and `Timer.Minutes`. The ordinary
  post-import save above can overwrite these retained duration values.
- `iPodTimerSettings.xml` holds `Timer.DateTime`, `Timer.SleepiPod` and
  `Timer.SoundIndex`. Timer saver `0x0819ed4c` writes those values and then
  explicitly invokes this named store's `+0x80` save. A later native timer
  save can therefore overwrite host changes to deadline/action/sound even
  without an ordinary settings flush.

The Nano 7 two-second observer arrangement is not asserted for Nano 6.
Its `TSettingsApp` constructor `0x0801c7dc` has a different shape, and its
timer saver provides its own immediate persistence path.

## Delivery guards and endpoints

Original delivery functions are Nano 6 `0x080bed38`, Nano 7 `0x081eeab6`,
and refresh `0x081eeace`. All first require state byte `timer+0x58 == 1`.
Inactive states return without sound, player, power or save calls.

When active, four conditions gate delivery:

| Guard | Nano 6 | Nano 7 / refresh |
| --- | --- | --- |
| System status virtual `+0x6c` | Factory `0x08189a50` | Factory `0x08423900` / `0x08423904`; accessor `0x084adb90`, byte `+0x71` |
| Remote UI flag | Factory `0x081aab42`, byte `+0x44` | Factory `0x08410f74` / `0x08410f78`, byte `+0x40` |
| Additional interface | `TPushUIApp`, factory `0x081d52b8`, virtual `+0x100` → `0x08166c44`, byte `+0x44` | Factory `0x084036cc`; vtable `0x08796e04` / `0x08796e74`; first method `0x081a1ff6` / `0x081a1ffa` returns constant 0 |
| Pending power transition | Root factory `0x0817df98`, byte `+0x1aa` | Root factory `0x0842ae80`, byte `+0x1fe` |

The Nano 7 status flag is specifically set on entry to state 9 by
`0x0821a7bc` → `0x0845b140(...,1)` and cleared on exit by `0x0821a768`.
It should not be relabeled a USB flag. Root byte `+0x1fe` is set by the
power-transition path `0x0821a978` and the user power-button sequence
`0x08240e4c`, and cleared by the cancellation/accessory branch in `0x0824159c`.
These are native state identities; no claim about physical power rails follows.

If any guard is nonzero, sound and sleep actions are skipped, but the timer
still enters its terminal state and saves. The 129 delivery cases establish
this branch behavior, including every synthetic four-guard combination.

With all guards clear:

- A sound index other than `-1` invokes the sound manager and a native
  notification helper. Nano 7 uses `0x081bd8ce` and `0x081eeb4c`; refresh uses
  `0x081bd8d2` and `0x081eeb64`; Nano 6 uses `0x081f6168` and `0x0809ca18`.
  The sound manager resolves `Resources/Sounds/` using the 25-entry table
  documented previously. Sound decoding/output success is outside the probe.
- If Sleep iPod is false after the sound path, Nano 7 queues system event 6
  through `0x083fe058`; refresh uses `0x083fe070`. The index `-1` with sleep
  false produces neither sound nor a sleep request.
- If Sleep iPod is true, a second predicate is checked before the player/power
  action. Nano 7 `0x081c4cda` reaches `ISL::TSportsActiveWorkout` virtual
  `+0x58`, selected through the `Trainer.Sensor` setting. The implementation
  `0x084af5e0` delegates to the installed workout object at `+0x48`, virtual
  `+0x24`, or returns 0 when absent. This is a workout-subsystem predicate,
  not a generic audio-ready test. The final installed workout implementation's
  full state semantics remain unqualified.
- With that predicate zero, the timer calls `TPodSystemMediaPlayer`'s secondary
  interface virtual `+0x38`, whose Nano 7 thunk `0x084b6876` dispatches main
  virtual `+0x98` with argument 0. It then queues system event 10 through
  `0x083fbe3e` / refresh `0x083fbe56`. Nano 6 uses the corresponding player
  interface and `0x08227698`. The probe proves invocation order and gating,
  not completion of playback shutdown or physical sleep.

Finally Nano 6 sets state 2 and invokes saver `0x0819ed4c`; Nano 7/refresh
set state 3 through `0x083afe14` / `0x083afe34`, then invoke saver
`0x083f283c` / `0x083f2854`. The 12 separate original terminal-save executions
prove writes of empty `Timer.DateTime` plus the retained sleep flag and sound
index. Nano 6 additionally requests the immediate named-store save. Suppressed
delivery is therefore consumed, not retried with the same persisted deadline.

## Requirements for a dependable persisted-deadline workflow

A future workflow that promises to start or clear a timer through XML needs
more than valid date syntax and a successful mounted-file replacement:

1. Establish a lifecycle in which the edited document survives pending/native
   retained saves and is actually loaded. The traced disconnect/import route
   does not supply that proof. Startup initialization does load it, but the
   host action that reliably reaches fresh initialization remains unverified.
2. Establish the native timer is not already active when restore runs. The
   proven active-state early return precedes settings reads. Editing an empty
   deadline cannot itself invoke Cancel on an already-active timer.
3. Account for both native caches: the ordinary duration preset and the runtime
   timer's deadline/action/sound. Nano 6 splits their persisted stores; Nano 7
   combines the XML but still has separate in-memory objects.
4. Confirm the native time basis and future-deadline adoption, then observe the
   scheduler and delivery guard behavior. The existing restore probes establish
   branch decisions, not RTC wake or hardware delivery reliability.
5. Verify the adopted state after that lifecycle. A reread of a host-mounted
   file proves persisted bytes only; it does not establish the running timer's
   state or that an alert will survive the guards above.

Saved duration/action/sound editing can remain explicit about being saved
settings, preserve `DateTime`, and avoid reporting a running state. The concrete
remaining blockers for stronger promises are the physical filesystem handoff
and queued-save timing, a verified transition into fresh initialization, full
Nano 6 event routing, installed workout-state semantics, and end-to-end
scheduler/player/power delivery. None is resolved by treating a valid XML
deadline as an immediate command.
