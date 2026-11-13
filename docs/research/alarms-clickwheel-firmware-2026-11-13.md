# Clock Alarms in Classic and Nano 3–5 firmware

Research date: 2026-11-13. This report covers every available latest Classic
updater-family image and the Nano 3, 4 and 5 images in the local firmware lab.
These seven independently checked inputs share the persisted Clock Alarm format.
They are not seven interchangeable complete firmware programs. Calendar Reminders
and Sleep Timer remain separate features.

The [recurrence and lifecycle follow-up](alarm-recurrence-lifecycle-2026-11-13.md)
adds independent recurrence, selection, snooze and dismissal executions across
all seven images, plus Nano 4/5 monthly file-owner load/refresh probes. It
supersedes the corresponding execution gaps in this initial report.

## Exact coverage and evidence strength

| Device / updater family | Release | Complete plaintext OSOS SHA-256 | Executed alarm evidence |
| --- | --- | --- | --- |
| Classic / 24 | 1.1.2 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` | Record, repeat, selection, constructor, toggle |
| Classic / 33 | 2.0.1 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` | Record, repeat, selection, constructor, toggle; additional UI tracing |
| Classic / 35 | 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | Record, repeat, selection, constructor, toggle |
| Classic / 38 | 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | Record, repeat, selection, constructor, toggle |
| Nano 3 / 26 | 1.1.3 | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` | Record, repeat, selection, constructor, toggle |
| Nano 4 / 31 | 1.0.4 | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` | Record, constructor, toggle; repeat menu table |
| Nano 5 / 34 | 1.0.2 | `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49` | Record, constructor, toggle; repeat menu table |

The [earlier Classic receipt][classic-native] contains 112 record/repeat/selection
cases and 72 individually hashed native function spans. This pass independently
matches all 18 function spans in Nano 3 and executes the same 28 cases. Matching
normalizes only ARM branch operands and PC-relative literal displacements and
requires a unique whole-function match; it does not assume an address delta.
[Nano 3 receipt][nano3-native]

Nano 4 and Nano 5 use Thumb implementations. Their file owners and serializers
were located separately, exported read-only, and executed for six record round
trips each. These include scheduled words zero, `1793496600` and `0xffffffff`,
and empty, ASCII and unaligned UTF-8 strings. A separate pass executes each of
the seven native constructors, six toggle cases and five label setter cases per
image, with the exact function hashes in its receipt. Thus the new pass contains
40 record/repeat/selection cases, seven constructors, 42 toggle cases and 35 label
cases, in addition to the
earlier Classic cases. [Nano 4/5 receipt][nano45-native], [authoring receipt][authoring-native]

Original firmware instructions perform scalar serialization, parsing, string
length calculation and toggle selection. Byte-stream I/O, string assignment,
selected-record access, notification and scheduler services are bounded memory
adapters. Constructor string initialization is adapted; constructor field stores
execute unchanged. No physical iPod, mounted device filesystem, audio playback,
RTC wake or power transition is exercised. Nano 4's known unreliable final eight
bytes are outside every studied span, and its native probes reject reads into
that tail. [Nano 4 provenance][nano4-map], [probe sources][authoring-probe]

From the firmware lab root, the retained authoring probe can be repeated with a
new output path:

```powershell
uv run scripts/probe_alarm_authoring_20261113.py --output artifacts/alarms-authoring-new.json
```

## Native file and record contract

All seven file owners reference `iPod_Control/Device/alarms`. Their outer token
container is `0x3a`; each independent Clock Alarm occupies a container with ID 5.
The native object is 0x38 bytes and its byte `+0x2c` distinguishes independent
Clock Alarms from Calendar-derived objects. Only independent records are emitted
by this writer. File save occurs when the owner is dirty; load constructs each
record and adds it to the collection. The writer emits no record count, index,
checksum or positional ID. [Classic owner][classic-owner], [Nano 4 owner][nano4-owner],
[Nano 5 owner][nano5-owner]

All framing words and scalar payloads are little-endian. Fields are not padded:

```text
container start = 0x40000000 | token
scalar field    = token, 4, u32_value, 0x80000000 | token
string field    = token, byte_length_including_NUL, bytes, 0x80000000 | token
container end   = 0xc0000000 | token
```

An empty collection is exactly `3a0000403a0000c0`. The UTF-8 string's native
length helper returns `strlen + 1`; a multibyte string can place subsequent
words at unaligned offsets. Do not use a fixed file offset for an alarm field.
[Native record vectors][nano45-native], [earlier framing analysis][classic-report]

| Token | Object offset | Meaning and authoring qualification |
| --- | --- | --- |
| `6` | `+0x08` | Scheduled civil scalar; reader also copies it to `+0x0c` |
| `7` | `+0x14` | Saved enable/sound gate: zero disables; native toggle chooses 8 or 4 when enabling |
| `0x3b` | `+0x18` | Repeat code 0–6; exact menu meanings below |
| `0x1f` | `+0x04` | Index into the firmware's 23 predefined alarm labels; constructor chooses index 3, “Alarm” |
| `8` | `+0x1c` | Library sound selection; `0xffffffff` means no selected library entry and chooses control 8 when enabled |
| `0x3c` | string at `+0x20` | Retained sound-name string; not a free-text Clock Alarm label |

The last two sound fields must remain preserved during date, repeat or enable
edits. Family 33's library browser supplies the indexed sound choices; a separate
sound collection supplies the retained string. The exact persistent identity of
a library choice across Library rewrites and the physical sound fallback remain
unqualified. They do not yet authorize a Playlist/tone editor. The existing codec
attribute named `label` is a legacy name for token `0x3c`, not an assertion of
its UI role. [Sound setter][sound-selector], [string setter][sound-name],
[native display dispatch][display-dispatch]

## Enabled state, creation and removal

The `ToggleAlarm` UI action resolves to the Alarm owner's toggle method. It reads
the selected object's `+0x14` and `+0x1c` fields and performs this exact update:

| Previous control | Sound selector | New control |
| --- | --- | --- |
| zero | `0xffffffff` | 8 |
| zero | any other word | 4 |
| nonzero | any word | zero |

All seven native implementations were executed for these branches. The application
limits edits to recognized existing control values 0, 4 and 8; an unknown nonzero
word is still observable as an enabled scheduling gate, but is preserved. This is
a saved-state edit, not a command to arm a running hardware timer.
[Classic toggle][classic-toggle], [Nano 4 toggle][nano4-toggle],
[Nano 5 toggle][nano5-toggle], [native cases][authoring-native]

All seven constructors establish the same persisted defaults: scheduled scalar 0,
control 8, repeat 0, predefined label index 3, sound selector `0xffffffff`, and
an empty sound-name string. The UI's New Alarm route constructs an object, assigns
a current-clock-derived date and adds it to the collection; iOpenPod instead
requires an explicit civil date from its editor. The native menu's default label
is “Alarm”. A new iOpenPod record can therefore use those constructor defaults
with the user's date/repeat/enabled choices, without borrowing another alarm's
unknown fields. [Constructors][authoring-native], [Classic creation route][new-alarm],
[label tables][menus]

Family 33's `HandleDeleteChosen` calls the owner removal operation with the selected
index. The collection writer then emits its remaining independent records.
Because the file has no count or cross-record IDs, the matching file edit removes
exactly one complete record span and leaves every other byte intact. Unknown
siblings do not require normalization. A malformed or ambiguous source is not a
template for adding or removing records. [Delete action][delete-action],
[owner removal][remove-record], [collection serialization][classic-owner]

No native maximum alarm count was established. iOpenPod retains its existing
16 MiB interpretation bound and checks it before insertion; this resource bound
is an application limit, not a claimed firmware capacity.

## Dates, repeats and postponement

The scheduled scalar uses seconds from a **1970 civil calendar coordinate**. It
does not use the 1904 media-date epoch and is not automatically an Instant in UTC.
Zero and `0xffffffff` survive native record read/write. The existing Classic and
new Nano 3 repeat probes compare unsigned scalar values, with native date
conversion and recurrence arithmetic. A repeated candidate advances until it is
strictly later than the supplied current scalar. [Earlier Classic study][classic-report],
[Nano 3 native cases][nano3-native]

| Code | Native menu | Executed Classic and Nano 3 behavior |
| --- | --- | --- |
| 0 | Once | No recurrence; equality is no longer active |
| 1 | Every Day | Add one civil-coordinate day |
| 2 | Weekdays | Advance to the next Monday–Friday occurrence |
| 3 | Weekends | Advance to the next Saturday/Sunday occurrence |
| 4 | Every Week | Add seven days |
| 5 | Every Month | Clamp the day in shorter months using an in-memory original-day anchor |
| 6 | Every Year | Native day-count advancement; tested February 29, 2024 becomes March 1, 2025 |

All seven images independently contain the same seven menu meanings and code
values. The later [lifecycle probe](alarm-recurrence-lifecycle-2026-11-13.md)
independently executes recurrence in all seven, including Nano 4/5. It also
establishes that the original-day anchor is not saved and that tested native
load/refresh paths retain the supplied heap value. Complete physical reload
and notification behavior remains unverified. [Per-image menu receipt][menus]

The Classic/Nano 3 earliest-selector excludes zero control words and the current
owner-designated object. A nonzero postponement scalar at object `+0x28` overrides
the saved scheduled scalar; equal deadlines retain the first object. A deadline
of `0xffffffff` is not selected. The Classic postpone handler adds 540 seconds,
or nine minutes, to the sampled current value. The postponement override is not
serialized in this file. This is native scheduler evidence, not a complete test
of the physical Snooze workflow on every model. [Selection and postpone report][classic-report],
[Nano 3 matched spans][nano3-native]

## Predefined labels and compatibility

Each image's own resource bank and a unique 23-entry table give this index order:
Wake up, Work, Class, Alarm, Appointment, Phone Call, Breakfast, Lunch, Dinner,
Important, Prescription, Take Medicine, Return Call, Delivery, Pick-Up, Meeting,
Reminder, Date, Anniversary, Birthday, Holiday, Go Home, Party. Runtime display
uses the firmware's localized resource for the saved index. An unknown index is
not a new free-text label. [Independent tables][menus], [display dispatch][display-dispatch]

The label setter in every image accepts indices 0–22, stores the selected index
at object `+4`, and rejects indices 23 and `0xffffffff`. Native cases execute
the boundary and normal choices independently in all seven images. iOpenPod
allows an explicit choice from that same catalog and preserves an unknown
existing index until the user replaces it. [Native label cases][authoring-native]

The qualified iOpenPod operations are whole-record insertion/removal and patches
to existing date, repeat, recognized enable and predefined-label fields. Existing
unknown fields, container ordering, raw dates and sound choices remain intact.
The native-emitted fixtures are embedded in ordinary repository tests; running
iOpenPod or its tests does not require this sibling lab or proprietary firmware.
See [the codec tests](../../tests/iPodDB/test_alarm_authoring.py).

Mounted-file publication remains separate from firmware adoption. Firmware can
retain a loaded Alarm collection and later save it over a Host-authored file.
The studied writer does not establish a live reload request over a mounted
connection. Source fingerprints and Storage Transactions protect publication;
they do not prove reload timing, power-loss behavior, wake delivery or sound
output. No device mutation was performed for this investigation.

[classic-native]: ../../../ipod-firmware-lab/artifacts/classic-alarm-20261106-v1/native-v7.json
[classic-report]: ../../../ipod-firmware-lab/notes/classic-alarm-persistence-2026-11-06.md
[nano3-native]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-nano3-native.json
[nano45-native]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-nano45-native.json
[authoring-native]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-authoring-native-v4.json
[authoring-probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_authoring_20261113.py
[nano4-map]: ../../../ipod-firmware-lab/Nano4FW/evidence/runtime-map.json
[classic-owner]: ../../../ipod-firmware-lab/artifacts/classic-alarm-20261106-v1/export1/080e8920-FUN_080e8920.c
[nano4-owner]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-nano4-seeds/080f4620.c
[nano5-owner]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-nano5-code/08260ec8.c
[classic-toggle]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-classic-setters/080e7c20.asm.txt
[nano4-toggle]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-nano4-toggle-body/080f3e30.asm.txt
[nano5-toggle]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-nano5-toggle-body/08108c98.asm.txt
[sound-selector]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-classic-setters/080e867c.c
[sound-name]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-classic-setters/080e7e40.c
[display-dispatch]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-classic-sounds/080e81ac.c
[new-alarm]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-classic-ui/080e97a0.c
[delete-action]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-classic-ui/081d0714.c
[remove-record]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-classic-setters/080e7a54.c
[menus]: ../../../ipod-firmware-lab/artifacts/alarms-20261113-menu-tables.json
