# Dated Clock Alarm recurrence and lifecycle

Research date: 2026-11-13. This follow-up executes the original Classic and
Nano 3–5 firmware instructions for recurrence, selection, snooze and dismissal.
It closes the Nano 4/5 arithmetic gap in the
[initial click-wheel report](alarms-clickwheel-firmware-2026-11-13.md). It also
narrows the monthly reload question: the saved record does not carry the
original-day anchor, and the tested original Nano 4/5 file-owner and refresh
paths do not reconstruct it from the file. A bounded follow-up finds strong
evidence of an Apple firmware persistence/initialization oversight: four
distinct live monthly anchors produce identical saved records in every image,
and Nano 4's original allocation path does not clear the anchor before its
constructor leaves it untouched. The complete notification population and
physical lifecycle remain unverified; this is not a claim that a real iPod
necessarily hangs after a monthly alarm reload.

## Exact inputs and reproducibility

| Device / updater family | Release | Complete plaintext OSOS SHA-256 | Cases |
| --- | --- | --- | --- |
| Classic / 24 | 1.1.2 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` | 31 |
| Classic / 33 | 2.0.1 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` | 31 |
| Classic / 35 | 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | 31 |
| Classic / 38 | 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | 31 |
| Nano 3 / 26 | 1.1.3 | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` | 31 |
| Nano 4 / 31 | 1.0.4 | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` | 34 |
| Nano 5 / 34 | 1.0.2 | `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49` | 34 |

The [retained probe][probe] and [final receipt][receipt] contain 223 passing
cases: 15 recurrence vectors, three seeded record reload vectors, three snooze
and save/reload vectors, two dismissal vectors and eight earliest-selection
vectors for each image; Nano 4 and Nano 5 each add three file-owner load and
refresh vectors. The expected instruction-bound result is asserted for each
zero-anchor vector; “passing” does not mean that those native calls returned.

The receipt binds the source script, helper scripts, original firmware and
runtime maps, and records each distinct executed instruction's original bytes
and SHA-256. Each first execution is checked against the pinned source image.
Classic/Nano 3 function spans additionally match their earlier independent
receipts. Nano 4's unreliable final eight bytes are excluded from both reads
and execution. Nano 5 uses explicit raw-to-runtime regions in the probe.
[Probe][probe], [receipt][receipt], [Nano 4 provenance][nano4-map]

| Artifact | SHA-256 |
| --- | --- |
| `scripts/probe_alarm_recurrence_lifecycle.py` | `4c9e539f76b754d39bf75239a6d5684c433a8e809aa2284338774e0996b89c14` |
| `artifacts/alarm-recurrence-lifecycle-20261113-v8.json` | `43f79ba9fa31a6e0295cbe2f23330d18752fda04d3b1581629980a4d051e8eda` |

Run from the firmware lab, using a new output name:

```powershell
uv run scripts/probe_alarm_recurrence_lifecycle.py --output artifacts/alarm-recurrence-lifecycle-new.json
```

The recorded environment is Python 3.12.14, Unicorn 2.1.4 and Capstone 5.0.6.
Original instructions perform date conversion, recurrence, record field stores,
record framing, cloning, deadline comparison and handler control flow. Adapters
supply a current civil calendar, string ownership, byte streams, allocation,
pointer collections, notifications and hardware scheduling boundaries. The
file-owner probes also adapt external Calendar-event loading. No physical iPod,
mounted device file, RTC wake, power transition or sound output was exercised.
[Probe][probe], [receipt][receipt]

## Native entry points

Addresses below are even instruction addresses. Nano 4/5 entry calls set the
Thumb bit; the other five use ARM instructions. Classic/Nano 3's listed date
setter is the owner method that resolves the selected record. Nano 4/5's is the
record helper directly. [Receipt][receipt]

| Family | Repeat | Date setter | Record read/write | Snooze | Dismiss | Earliest selection |
| --- | --- | --- | --- | --- | --- | --- |
| 24 | `082350a4` | `080e3da8` | `08235360` | `080e2af4` | `080e2ba8` | `080e3ad0` |
| 33 | `08249738` | `080e7d98` | `082499f4` | `080e6ae4` | `080e6b98` | `080e7ac0` |
| 35 | `08266208` | `080feedc` | `082664c4` | `080fdc28` | `080fdcdc` | `080fec04` |
| 38 | `08267ad8` | `080fef94` | `08267d94` | `080fdce0` | `080fdd94` | `080fecbc` |
| 26 | `08266ea4` | `080f07bc` | `08267160` | `080ef508` | `080ef5bc` | `080f04e4` |
| 31 | `0822571c` | `082258e4` | `082258fc` | `080f3058` | `080f30d4` | `080f3cde` |
| 34 | `0824e018` | `082628e8` | `081c4b56` | `081c49dc` | `08076210` | `0828ade8` |

## Recurrence arithmetic

All seven images now independently execute the same 15 input vectors with the
same results. Scalars are unsigned seconds in the firmware's 1970 civil
calendar coordinate. The oracle uses naive calendar components; it does not
apply the Host timezone or reinterpret the scalar as an Instant. The actual
firmware calendar-to-scalar and scalar-to-calendar routines execute in these
tests. [Probe][probe], [receipt][receipt]

| Code | Meaning | Executed result |
| --- | --- | --- |
| 0 | Once | A future scheduled time remains active; equality is inactive. |
| 1 | Every Day | Equality advances one day; the candidate must be strictly later than now. |
| 2 | Weekdays | A passed Friday or Saturday occurrence advances to Monday. |
| 3 | Weekends | A passed Monday advances to Saturday; a passed Saturday advances to Sunday. |
| 4 | Every Week | A passed occurrence advances seven days. |
| 5 | Every Month | January 31 advances to February 28, 2026; with the same live anchor, a later March 1 query advances to March 31. |
| 6 | Every Year | An ordinary date advances a year; February 29, 2024 advances to March 1, 2025. |

The vectors also cross the signed 2038 boundary and exercise civil coordinates
`2026-03-08 02:30` and `2026-11-01 01:30`. Those coordinates remain arithmetic
calendar values in this bounded path; this does not establish physical behavior
at a nonexistent or repeated local hour. The test set does not qualify every
32-bit wraparound or invalid recurrence code. [Receipt][receipt]

## Monthly original-day anchor and persistence

The native object has separate scheduled, original and transient fields:

| Object offset | Observed role | Saved record behavior |
| --- | --- | --- |
| `+0x08` | Current scheduled civil scalar | Token 6 payload. |
| `+0x0c` | Companion original scalar used by other paths | Reader copies token 6 here too. |
| `+0x10` | Original day-of-month anchor | Neither emitted nor initialized by the tested constructor/reader. |
| `+0x18` | Repeat code | Token `0x3b` payload. |
| `+0x28` | Postponement override | Not emitted; constructor sets zero. |

Every tested date setter stores the converted scalar into `+8` and `+0x0c` and
the calendar's day byte into `+0x10`. The original constructors and readers
leave `+0x10` unchanged. This was verified by executing those instructions with
three different preexisting values, rather than inferring initialization from
an absent decompiler assignment. [Probe][probe], [receipt][receipt],
[Nano 4 setter][nano4-setter], [Nano 5 setter][nano5-setter]

The probe first creates January 31 at 08:00 through the native date setter, runs
monthly recurrence to February 28, and saves through the original serializer.
It then constructs and reads into memory with the following selected anchor
seeds. All seven images produce the same observations when recurrence is run
with current time March 1 at 09:00:

| Seed at `+0x10` before construction | Anchor after construction and read | Subsequent result |
| --- | --- | --- |
| 0 | 0 | Reaches the 30,000-instruction bound without returning or advancing the saved February 28 scalar. |
| 17 | 17 | Returns active with March 17 at 08:00. |
| 31 | 31 | Returns active with March 31 at 08:00. |

The wire bytes are identical across these seeds and are included in each
receipt case. The experiment establishes dependence on an unsaved runtime
field; the seeds are harness-controlled memory, not measured device heap
contents. [Receipt][receipt]

### Surrounding Nano 4/5 load and refresh paths

The follow-up executes the original file owners (`080f4620`, `08260ec8`), which
allocate 0x38 bytes, construct, read and append each independent record. The
original next-token readers and record readers execute. With synthetic
allocation retaining each seed, the owner leaves the same anchor untouched.
The original subsequent refresh routines (`080f317a`, `081d34d8`) then compare
the scheduled date with now and invoke recurrence for the past monthly record.
They reproduce the same zero/17/31 outcomes. Hardware rescheduling, notification
receivers and the external Calendar provider are adapters at this boundary.
[Receipt][receipt], [Nano 4 owner][nano4-owner], [Nano 5 owner][nano5-owner],
[Nano 4 refresh][nano4-refresh], [Nano 5 refresh][nano5-refresh]

Static caller tracing adds context without replacing that limitation:

- Nano 4 load entry `080f3154` runs cleanup, file load, then Calendar-event
  loading. Its Calendar loader constructs separate Calendar-derived records,
  sets their date and original-day fields, and marks them with byte `+0x2c = 0`.
  It does not walk the independent records to restore their anchors.
- Nano 5 load entry `0804b394` similarly runs cleanup, file load and its
  Calendar loader. The Calendar path calls the date setter for its new record
  and explicitly writes the original day afterward.
- The allocator wrappers request class/tag 2. The traced Nano 5 general-heap
  block finalizer writes allocation metadata without clearing the payload;
  other pool selection, complete heap state and notification recipients are
  not executed by this probe. A zero-filled allocation is not assumed.

[Nano 4 load entry][nano4-load], [Nano 4 Calendar loader][nano4-calendar],
[Nano 5 load entry][nano5-load], [Nano 5 Calendar loader][nano5-calendar],
[Nano 5 allocator][nano5-allocator], [Nano 5 block finalizer][nano5-block]

**Host implication, inferred from the saved fields:** after February clamping,
the file alone cannot distinguish an original day of 28, 29, 30 or 31. It cannot
provide an exact original-day anchor for a Host next-occurrence calculation.
This remains true even if an untraced device callback supplies some runtime
initialization. A full physical reload bug, actual allocator residue and all
notification-driven recovery paths remain unverified. Do not convert the
zero-seed experiment into a claim that all device reloads hang.

### Bounded oversight audit

The follow-up supports **a likely Apple firmware oversight**, with the saved
information loss directly demonstrated rather than merely inferred. A separate
[native probe][information-probe] creates January 28, 29, 30 and 31 through each
image's original date setter, advances each to February 28, and serializes it.
For every one of the seven images, all four saved records are byte-identical.
The four live objects still advance to different March dates, 28 through 31,
because they retain their distinct anchors. All 28 cases pass. No reader or
notification receiver can recover which of these four states produced the
record **from those bytes alone**. [Information-loss receipt][information-receipt]

The allocator audit also resolves a specific initialization concern for Nano 4.
Its original alarm allocation call follows `0826178a → 080d6bb8 → 08163944 →
08163484`. The wrapper explicitly supplies a clearing flag of zero, separately
from allocation class/tag 2. A new native probe executes this chain, the actual
free-list selection and the allocation metadata writer against a valid
synthetic free block. A payload containing `0xa5a5a5a5` at the anchor retains
that value after allocation and the alarm constructor. The same original
allocator, explicitly called with clearing flag one as a control, clears the
payload and yields anchor zero. Heap initialization, locking and current
allocation-owner/thread identity are adapted; free-list selection and the
clearing decision are original instructions. This is not evidence of the
particular bytes a real iPod's heap contains. [Allocator probe][allocator-probe],
[allocator receipt][allocator-receipt], [native allocator][nano4-allocator]

Static notification tracing does not reveal a fixed anchor-restoration step.
The post-load notification wrappers construct an event containing `VMax`
(`0x564d6178`) and property `0x9c08` on Nano 4 or `0xa408` on Nano 5. Their
generic dispatchers enumerate registered runtime listeners and invoke listener
slots `+0x30` or `+0x3c`, with cross-thread forwarding when needed. Neither the
event payload nor the wrapper/dispatcher carries the missing original day.
The complete runtime subscriber population was not reconstructed, so this is
not an exhaustive assertion about every receiver's side effects.
[Nano 4 notification][nano4-notification], [Nano 4 dispatcher][nano4-dispatcher],
[Nano 5 notification][nano5-notification], [Nano 5 dispatcher][nano5-dispatcher]

The distinction is therefore:

- **Demonstrated:** all seven images omit information that their live monthly
  recurrence uses; Nano 4's actual allocation/constructor path does not establish
  a valid anchor by clearing or assigning it.
- **Strongly supported interpretation:** the persistence and initialization
  omission is an Apple firmware oversight. No deliberate replacement rule or
  recovery mechanism was found in the bounded paths inspected.
- **Unverified:** Apple's intent, the exact physical symptom after a particular
  device lifecycle, and whether some runtime receiver supplies additional state
  in some circumstances. The zero-seed execution bound is not a universal
  device-hang prediction.

This is a firmware finding. No iOpenPod repair, workaround or replacement
monthly scheduling behavior is introduced. The bounded audit ends here.

| Additional artifact | SHA-256 |
| --- | --- |
| `scripts/probe_monthly_alarm_information_loss.py` | `bb72e42c54aea4cd70c1d13ff0a9a8f5edd1134b7c5cff9047c9b0d46768f73c` |
| `artifacts/monthly-alarm-information-loss-20261113-v1.json` | `46124cd27d8cd5a776c036dcf2f78f2b3c1c7d2b9ee979f58ca7547fd0d61fe7` |
| `scripts/probe_alarm_monthly_anchor_audit.py` | `eda6c3c77a907465dc7d424f97c86d0ec892e9f9cbf36ab0f946296f20925311` |
| `artifacts/alarm-monthly-anchor-audit-20261113-v2.json` | `e8ac1f0e750755cd0503be993e5f4ec5da56602b02d8d34a6285eda9505a474a` |

The allocator receipt records its script hash, the pinned lifecycle helper hash,
exact firmware identity and executed instruction bytes. Repeat the bounded
allocator probe from the lab with a new output path:

```powershell
uv run scripts/probe_alarm_monthly_anchor_audit.py --output artifacts/alarm-monthly-anchor-audit-new.json
```

## Snooze, dismissal and selection

All seven original snooze handlers clone the selected alarm, remove the
selected pending entry and set the clone's `+0x28` to sampled current civil
seconds plus `0x21c`, exactly **540 seconds / nine minutes**. This replaces an
existing postponement value. The scheduled scalar, original-day anchor and
other scalar fields remain unchanged. The executed vectors include ordinary
time, December 31 crossing midnight and February 28 crossing into leap day.
[Receipt][receipt], [Classic handler][classic-snooze],
[Nano 4 handler][nano4-snooze], [Nano 5 handler][nano5-snooze]

Saving this clone and constructing/reading the saved record restores `+0x28`
to zero in every image. Thus a postponed runtime deadline is not persisted in
`iPod_Control/Device/alarms`. This is a record persistence result, not proof of
when the complete application saves or reloads that file. [Receipt][receipt]

For the two executed dismissal cases, a passed Once alarm is removed and its
clone destroyed; a passed Daily alarm advances to the next morning, clears the
postponement override and is appended again. Nano 5 additionally compares the
old and advanced dates before re-adding an active clone, so do not generalize
the tested past-alarm cases into a claim that every generation has identical
handler control flow for future synthetic records. [Receipt][receipt],
[Nano 4 dismissal][nano4-dismiss], [Nano 5 dismissal][nano5-dismiss]

All seven earliest-selection routines independently pass eight vectors. They
skip disabled records and the owner's excluded object, use nonzero `+0x28`
instead of `+8`, choose the smallest unsigned effective deadline, and retain
the first record for a tie. Scalar zero can be selected; `0xffffffff` cannot
beat the initial sentinel. An empty collection yields no selection.
[Receipt][receipt], [Nano 4 selector][nano4-select], [Nano 5 selector][nano5-select]

## Application consequences and remaining scope

The date/repeat editor can document the shared native recurrence meanings for
all seven qualified images. These findings do not require a new persisted
field, a Host snooze writer, or a speculative anchor-repair token. Preserve
existing saved values and Unknown Data; an exact next-occurrence display for
an already advanced monthly record would need additional qualified state.

The scalar arithmetic, file format and handler execution are now independently
qualified across the seven images for the recorded vectors. Physical wake and
sound delivery, firmware adoption of Host edits, complete reload ordering,
arbitrary corrupted runtime fields and all date-overflow cases remain outside
this report. No product source or device files were changed in this follow-up.

[probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_recurrence_lifecycle.py
[receipt]: ../../../ipod-firmware-lab/artifacts/alarm-recurrence-lifecycle-20261113-v8.json
[nano4-map]: ../../../ipod-firmware-lab/Nano4FW/evidence/runtime-map.json
[nano4-setter]: ../../../ipod-firmware-lab/artifacts/alarm-recurrence-20261113-nano4/082258e4.c
[nano5-setter]: ../../../ipod-firmware-lab/artifacts/alarm-recurrence-20261113-nano5/082628e8.c
[nano4-owner]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano4-direct/080f4620.c
[nano5-owner]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano5/08260ec8.c
[nano4-refresh]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano4-direct/080f317a.c
[nano5-refresh]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano5-direct2/081d34d8.c
[nano4-load]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano4-direct/080f3154.c
[nano4-calendar]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano4-direct/080f3960.c
[nano5-load]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano5-direct2/0804b394.c
[nano5-calendar]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano5-direct2/082508fc.c
[nano5-allocator]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano5-direct2/08020df4.c
[nano5-block]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano5-direct2/081a8204.c
[classic-snooze]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-classic-ui/080e6ae4.c
[nano4-snooze]: ../../../ipod-firmware-lab/artifacts/alarm-recurrence-20261113-nano4/080f3058.c
[nano5-snooze]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano5-direct2/081c49dc.c
[nano4-dismiss]: ../../../ipod-firmware-lab/artifacts/alarm-recurrence-20261113-nano4/080f30d4.c
[nano5-dismiss]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano5-direct2/08076210.c
[nano4-select]: ../../../ipod-firmware-lab/artifacts/alarm-lifecycle-20261113-nano4-direct/080f3cde.c
[nano5-select]: ../../../ipod-firmware-lab/artifacts/alarm-recurrence-20261113-nano5/0828ade8.c
[information-probe]: ../../../ipod-firmware-lab/scripts/probe_monthly_alarm_information_loss.py
[information-receipt]: ../../../ipod-firmware-lab/artifacts/monthly-alarm-information-loss-20261113-v1.json
[allocator-probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_monthly_anchor_audit.py
[allocator-receipt]: ../../../ipod-firmware-lab/artifacts/alarm-monthly-anchor-audit-20261113-v2.json
[nano4-allocator]: ../../../ipod-firmware-lab/artifacts/alarm-anchor-audit-20261113-nano4/08163484.c
[nano4-notification]: ../../../ipod-firmware-lab/artifacts/alarm-anchor-audit-20261113-nano4/08226910.c
[nano4-dispatcher]: ../../../ipod-firmware-lab/artifacts/alarm-anchor-notify-20261113-nano4/0810af18.c
[nano5-notification]: ../../../ipod-firmware-lab/artifacts/alarm-anchor-audit-20261113-nano5/08136c96.c
[nano5-dispatcher]: ../../../ipod-firmware-lab/artifacts/alarm-anchor-notify-20261113-nano5-direct/082761d8.c
