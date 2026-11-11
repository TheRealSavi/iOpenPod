# Calendar reload and delivery boundaries

Investigated offline against retained original firmware on 2026-11-09. This
extends the [Calendar coverage](calendar-firmware-coverage-2026-11-08.md).
Native execution below covers a reload wrapper with explicit service adapters;
static call tracing is identified separately. No device was accessed.

## Mini reload is collection replacement

Eight original-instruction cases execute the reload wrapper independently on
Mini 1 and Mini 2. The [harness](../../.scratch/probe_calendar_reload.py) pins
each original image hash and corpus manifest, validates initialized RAM blocks,
and records the wrapper span hash in its [receipt](../../.scratch/calendar-reload-20261109-v2.json).
Unicorn version is 2.1.4. Candidate signature matching is followed by actual
execution of the separately loaded original instructions.

| Target | Original OSOS SHA-256 | Reload wrapper | Per-file callback | Temporary-state global |
| --- | --- | --- | --- | --- |
| Mini 1 / 1.4.1 / updaters 3, 6 | `2f844307acf62702fc247b19a148f35d497ce59d6ef7790b242200b5d64b09df` | `0x000b50fc` | `0x000a95b0` | `0x10419e2c` |
| Mini 2 / 1.4.1 / updater 7 | `346504450c5201a632cafa38312093fc04b402b4ca37c79d7ca4a4167bb8f34d` | `0x000b5410` | `0x000a98e4` | `0x10419dfc` |

Each invocation performs the following original control flow:

1. Requests a new collection and places its pointer in temporary state `+4`.
2. Calls directory enumeration with the firmware's per-file parser callback.
3. Passes the new collection to the live model publication function.
4. Conditionally requests reminder refresh: the separate global gate must be
   nonzero and the mode query must return zero. Refresh receives the model and
   reset flag `1`.
5. Clears the temporary collection pointer and returns zero.

The cases cover all four gate/query-result combinations, using a different
synthetic collection pointer on each successive invocation. Enumeration checks
that temporary state holds the new collection; publication checks its exact
pointer. Original branching, pointer stores, cleanup and invocation order execute.
Collection construction, filesystem enumeration, publication, mode query and
refresh are explicit adapters. Consequently this qualifies **the wrapper's
orchestration**, not collection allocation safety, full stream import or physical
file adoption. No Host path or mounted-device mutation is performed.

The Mini 2 [worker instructions](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/0009302c.asm.txt)
place this wrapper inside a loop: wait on the object at global state `+0x0c`,
run pre-scan work, call reload, run post-scan work, then wait again. A nonzero
returned local selector additionally calls `0x0009a1ac`. This is static evidence
for queued reload orchestration. The producer of that queue and the meaning of
the selector were not qualified by the initial wrapper experiment; the producer
follow-up below resolves one queue path without claiming that each mounted Host
write automatically produces a reload event.

## Follow-up: executed queue producer

Six new original-instruction cases execute the request-enqueue helper on Mini 1
and Mini 2. The [new harness](../../.scratch/probe_calendar_reload_enqueue.py) and
[receipt](../../.scratch/calendar-reload-enqueue-20261109.json) independently pin
the same original image and initialized-memory manifest hashes as the table
above, with each helper's own instruction-span hash. Outputs are new artifacts;
the earlier eight wrapper cases and their receipts remain unchanged.

| Target | Enqueue helper | Worker-state global |
| --- | --- | --- |
| Mini 1 | `0x000b50d0` | `0x10419dac` |
| Mini 2 | `0x000b53e4` | `0x10419d7c` |

The original helper obtains a current execution-context object, reads its sender
handle at `+0x1c`, reads the recipient queue at worker-state `+0x0c`, and calls
the native enqueue adapter with arguments `(sender, recipient, 0, 0, 0)`.
The Mini 2 recipient is exactly the queue consumed by the previously traced
worker `0x0009302c`. Two different handle pairs and a zero-handle diagnostic
execute on each image. The helper performs no nonzero-handle validation. OS
context acquisition and enqueue are explicit adapters, so the zero case proves
argument formation only, not OS acceptance or safe execution with invalid handles.

The earlier wrapper's nonzero global gate is an application pointer. Its
mode-query target is the
[original byte getter](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00072b80.asm.txt)
for application `+0x18a2`; the
[application constructor](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000ec0d0.c)
initializes that byte to zero and `+0x18a1` to one. This identifies the field
behind the adapter without assigning it a USB or mount-mode meaning. The
constructor obtains the provider stored at `+0x1820` from a supplied factory;
the concrete provider trace follows below.

The Mini 2 [original entry path](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000992d8.asm.txt)
ends by entering this helper. Its other work constructs/assigns an object and
dispatches three property notifications. The
[surrounding state-transition path](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000428f8.asm.txt)
calls it after a virtual provider test succeeds and before setting byte
`application + 0x18a1` to one and `+0x18a2` to zero. That branch is skipped when
the first byte was already nonzero. These are static instruction observations;
the provider and flag meanings are not assigned USB, eject or Sync labels here.

Native [queue insertion](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/0009a6b8.c)
and [worker reception](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/0009aa8c.c)
provide supporting static linkage. The executed helper does not run the OS queue,
the provider, the entire state transition or a physical mount lifecycle. The
remaining question is therefore which real event enters this path, rather than
whether an explicit reload-request producer exists.

### Static concrete-provider trace

Mini 2's [outer constructor](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000eb19c.asm.txt)
loads literal `0x000eb310`, whose original word is factory address `0x0004927c`,
and supplies it to the application constructor. The original factory is a
three-instruction wrapper around provider constructor `0x000ebbe8`. The
[provider constructor](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000ebbe8.asm.txt)
installs vtable `0x00026020`; resolving its relative `+0x90` slot gives
`0x00069c84`, the gate invoked by the state-transition path.

Original instructions at `0x00069c84` obtain client object `0x00072238` and
tail-call [the synchronized check](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/0008d30c.c).
That check enters the manager's lock and calls
[the comparison](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00093b50.c),
which returns whether manager `+0x1c` equals the supplied client pointer. Thus
the gate is a concrete client/manager-state comparison, rather than a direct
Calendar-file change check. The
[client registration path](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000b4c50.c)
also registers this object with that manager. Assigning the manager a physical
USB, disk-ownership or eject contract requires tracing its state producers and
concrete notifications; those labels are not established by pointer equality.

This subsection is static raw-instruction and exported call/data-flow evidence
on the pinned Mini 2 image, not another native execution count. It narrows the
remaining reload question to the manager transition and its event producers.

## Static Mini 2 publication and reminder query

The [original wrapper](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000b5410.asm.txt)
calls publication at `0x00031104`. Its
[original implementation](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00031104.c)
resets cached selectors, releases the old collection when its pointer differs,
stores the new collection and dispatches model notifications. This is supporting
static call/data-flow evidence, not an executed old-object destructor experiment.

The conditional refresh enters `0x000a6a94`. Its
[original instructions](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000a6a94.asm.txt)
capture the live clock, refresh device offset/DST context, optionally reset the
query cursor at model `+0x1e8`, and construct an upper bound using the literal
`0x5a` days, or **90 days**. The
[civil arithmetic helper](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/0009b2e4.c)
adds the day/second components. The refresh routine queries the collection and
either advances its cursor or constructs pending reminder objects. These paths
are static observations here; they do not establish missed-reminder behavior,
notification ordering or sound selection.

## Alarm pool routing and delivery

### Follow-up: Calendar request to the native alarm pool

The new [request-construction harness](../../.scratch/probe_calendar_reminder_request.py)
and [receipt](../../.scratch/calendar-reminder-request-20261109.json) execute
**30 original-instruction cases** on independently pinned Mini 1/2 images and
maps. Native wrappers are Mini 1 `0x000bd0bc` and Mini 2 `0x000bd3bc`.
Only initial zero-fill and the downstream pool programmer are recording adapters;
native selector branches and every request-field store execute.

| Input selector | Pool slot | Request token at byte `+0x10` |
| --- | --- | --- |
| 0 | 2 | `0x89` |
| 1 | 3 | `0x8a` |
| 2 | 4 | `0x8b` |
| 3 or `0xffffffff` | No request | Return `0xffffffce` |

For three distinct eight-byte packed input patterns per selector, the native
wrapper copies source bytes `0..3` to request `0..3`, byte `7` to request `6`,
bytes `4..6` to request `8..10`, sets byte `15` to one, and supplies the table's
token. These are byte-layout observations, not malformed-calendar acceptance
tests or permission to author new Clock Alarms.

The actual Calendar refresh route calls selector **0** on both models:
[Mini 1 refresh](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000a6760.c)
and [Mini 2 refresh](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000a6a94.asm.txt).
Together with the executed request wrapper, this ties those Calendar reminders
to native pool slot **2** and token **`0x89`**. Mini 2's
[pool programmer](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000c62e8.c)
copies the 20-byte request and marks the slot before reprogramming. That final
programmer was adapted in the new tests; physical hardware arming and delivery
are not established by these cases. The earlier native pool-selector/register
experiments remain separate evidence.

### Remaining cross-family delivery questions

The earlier exact-image [Video investigation](../../../ipod-firmware-lab/notes/video-calendar-alarm-2026-11-06.md)
traces directory shim `0x000e5afc`, per-file parser `0x000fc99c`, and generic
notification delivery loop `0x00285460`. The latter signals the selected slot's
handle and reprograms the alarm pool. Its physical interrupt source and complete
Calendar registration path remain unresolved. The
[Classic investigation](../../../ipod-firmware-lab/notes/classic-calendar-alarm-2026-11-06.md)
independently maps directory and per-file parser entry points on updaters
24/33/35/38. Those parser paths do not by themselves qualify the complete reload
lifecycle. Nano 1/3/4/5 reload/adoption has not received an equivalent wrapper
experiment in this pass.

Neither the new Mini wrapper experiment nor those earlier paths determine which
Host disconnect, synchronization, application-entry or filesystem event invokes
reload on each firmware. No file-watcher or immediate mounted-write adoption
contract is claimed. Likewise no physical wake, sound, missed-alarm policy or
notification delivery was tested. iOpenPod can report successful saved-file
publication; these findings still do not justify promising immediate activation.

## Executed Mini software delivery task

The [new task harness](../../.scratch/probe_calendar_mini_delivery_20261110.py)
and [receipt](../../.scratch/calendar-mini-delivery-20261110.json) execute ten
original-instruction cases, five each on Mini 1 and Mini 2. Original task entries
are `0x00150714` and `0x00150444`. Exact original image/manifest hashes, task
span hashes, record-array and selected-index globals are bound in the receipt.
Each run stops at its second wait call, bounding execution to one task iteration.

OS wait, lock/unlock, the provider query, wake request, signal and next-alarm
selection are explicit recording adapters. The provider query returns nonzero;
the separate hardware-status branch for a zero result is not qualified here.
Original selected-index guards, record reads, conditional calls, processed-flag
clear and loop control execute unchanged.

| Selected record state | Observed original task behavior |
| --- | --- |
| Slot 2, byte `+0x0e` set, byte `+0x0f` set, token `0x89` | Calls wake request with 1, clears `+0x0e`, signals `0x89`, requests reselection |
| Same, but `+0x0f` zero | Clears `+0x0e` and signals; no wake-request call |
| Same, but token zero | Calls wake request and clears `+0x0e`; no signal |
| `+0x0e` zero | No wake request or signal; still requests reselection |
| Selected index `0xffffffff` | Skips record processing and requests reselection |

Every case acquires/releases lock token `0x124`, and returns to waiting on
`0x88`. The reselection adapter returns zero; repeated processing of several due
slots is not established by this one-iteration experiment. Only byte `+0x0e`
is cleared by the tested path, not the complete record or every enable/control
field. The old static Mini 2 task description is now independently executed on
both Mini images at this bounded software boundary.

Combining the earlier Calendar request construction with this task identifies
the software route from Calendar pool slot 2/token `0x89` to a signal call.
The experiment does not generate a real hardware interrupt, run the OS signal
receiver, prove physical wake/audio, or establish missed-alarm policy. Those
claims still require the remaining consumer trace and physical acceptance work.
