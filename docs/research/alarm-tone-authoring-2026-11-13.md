# Authoring melody tones for Classic and Nano 3–5

Research date: 2026-11-13. This extends the
[native sound investigation](alarm-sounds-clickwheel-2026-11-13.md) from reading
tone catalogs to authoring a short melody. The output is a monophonic sequence
of oscillator frequencies and durations, not a compressed excerpt of the Track.
All seven studied firmware inputs accept the same clean authored format.

## Scope and evidence

The exact targets are Classic updater families 24, 33, 35 and 38; Nano 3 family
26; Nano 4 family 31; and Nano 5 family 34. Their image hashes and runtime maps
are retained in the [new execution receipt][receipt] and the
[portable fixture](../../tests/fixtures/alarms/native_tone_authoring.json).
Nano 5 uses its previously verified three-region runtime map, explicitly
embedded in the reused parser harness. Nano 6/7 built-in Countdown Timer sounds
are a separate system and are outside custom tone authoring.

The new [probe][probe] uses Unicorn 2.1.4 and Capstone 5.0.6, pinned through UV
script dependencies. It executes original instructions against synthetic files,
allocated strings, captured queue calls and simulated timer-register memory:

- **49 parser cases:** seven authored files in each of seven firmware images.
  They include a seven-second melody with rests, Unicode, the 253-byte header
  boundary, unsigned 16-bit endpoints, 1000 notes and the default Beep sequence.
- **126 tone-dispatch cases:** six frequency/duration pairs with three native
  board identities in each image. These exercise the zero-frequency branch,
  separate pitch/duration timers and unchanged duration forwarding.
- **49 oscillator cases:** seven frequencies in each image, executing the native
  timer-period calculation and register stores, including native division.
- Within the parser cases, **35 additional playback-loop checks** in Classic
  and Nano 3 verify that every parsed pair is queued once, in source order.

All 224 primary cases and the 35 playback-loop checks pass. Hardware operations,
blocking queue waits and interrupt delivery are adapters; this is not physical
speaker or wake testing. Original parser, line-reader, decimal conversion,
dispatch branches and oscillator-register calculations execute unchanged.

The receipt SHA-256 is
`456365057847298bb8b1a6fe21245bb89ea414cbf701d09a34d04d1173a8c29b`.
The probe SHA-256 is
`20bed1bb969c1b0638ffd1586dddb367eaa782af814c5abd5641191e38494ef3`.
The reused parser harness SHA-256 is
`28b36d0c3bb58df3c2a08e10ca3265b0942db7bf723a3d857b3702bf8c856063`.
These bind the current receipts; later edits require a new run and receipt.

Repeat from the firmware lab, choosing a new output path:

```powershell
uv run scripts/probe_alarm_tone_authoring_20261113.py --output artifacts/alarm-tone-authoring-new.json
```

## Clean authoring contract

The following UTF-8 text is a complete valid tone:

```text
Morning melody
523 500
587 500
659 500
0 125
659 375
698 500
784 1000
0 250
784 500
698 500
659 500
587 500
523 1250
```

Its durations sum to exactly 7000 ms. The frequency-zero entries preserve
silence between phrases. All seven original parsers produce exactly these
13 pairs and the same name. The fixture contains this synthetic melody and
independent Unicode, length-boundary, numeric-boundary and Beep cases; it
contains no music recording. [Executed inputs and parsed outputs][receipt]

For new files, use one nonempty name line followed by one decimal pair per
line. Separate the two numbers by exactly one ASCII space and terminate each
line with LF. Do not emit signs, decimal fractions, NUL, CR/LF inside the name,
extra leading spaces, byte-order marks or trailing annotations. The native
parser accepts some unusual forms, but those are preservation cases rather
than useful authoring syntax. [Native parser rules][sound-report]

The maximum clean newline-terminated name is **253 UTF-8 bytes**, not 254
characters. A 254-byte name followed by CR/LF triggers the native line-reader
failure; its unusual accepted-at-EOF behavior is unsuitable for a file that
also needs notes. The new probe accepts both 253 ASCII bytes and 126 two-byte
characters plus one ASCII byte. [Header cases][receipt]

Each note stores frequency and duration as unsigned 16-bit integers, and the
object holds at most 1000 notes. A new writer should reject excess notes and
out-of-range values instead of silently reproducing native truncation. Positive
durations avoid zero-length notes. Require at least one pitched note for a
generated melody; inability to recover a melody should be an analysis result,
not a silent or fabricated tone. [Parser and queue bodies][sound-report]

## Rests, pitch and playback

The Classic 2.0.1 queue consumer was previously outside the exported function
inventory. Original bytes at `0x0837944c` reveal a serial note worker. It
dequeues from queue 2, reads frequency at message `+0x10` and duration at
`+0x14`, configures timers, waits for completion, disables its output and then
dequeues the next note. The [read-only export][driver-export] records the
recovered function and its timer-driver callees.

The zero-frequency branch explicitly skips oscillator configuration and start
while still starting the duration timer. Thus **frequency 0 is a timed rest**.
This branch independently executes in all four Classic images and Nano 3.
Nano 4's equivalent start helper at `0x080de974` and Nano 5's at `0x08002c8c`
independently pass the same rest and nonzero-frequency tests. Their worker
call sites are `0x08314112` and `0x08010d46` respectively. [Dispatch cases][receipt]

The native oscillator routines accept 131, 262, 440, 523, 1047, 2093 and 4186
without clipping or rejection. Each produces period register
`floor(3000000 / frequency)` with a zero additional prescaler in these tested
cases. Their timer control words differ by processor generation; the authored
file does not encode those hardware details. A conversion range such as MIDI
48–96 (approximately 131–2093 Hz) is a sensible application musical choice,
not a claim that the device is limited to that range. [Native register cases][receipt]

The player traverses the sequence once and queues its pairs in order. There is
no repeat count, waveform selection, sample data, volume or instrument field
in this format. The seven-second length describes the authored phrase. The
larger Alarm scheduling, snooze and dismissal lifecycle is separate; the Host
should not duplicate notes to invent a repeat policy. [Playback loop][tone-play]

A Host preview can synthesize the same pitches, rests and durations. It remains
an approximation of the iPod's physical speaker: this pass does not establish
its acoustic response, loudness or chassis-dependent timbre.

## Names, catalog capacity and deletion

The firmware scans regular files in `iPod_Control/Tones`. It skips leading-dot
names and the exact reserved `Beep.tone` filename, but has no extension filter.
The default occupies the first of 20 collection slots, leaving at most
**19 custom tones**. Excess membership depends on directory enumeration order.
For a newly authored tone, use an opaque unique filename ending in `.tone` and
put the user-visible name inside the file. [Directory scan][tone-scan]

Alarms store the exact decoded tone name, with case-sensitive lookup. Duplicate
names select the first matching collection item. Qualification therefore needs
a captured complete catalog, unique nonempty names and exclusion of the current
localized default name and literal `Beep`. An unreadable candidate cannot be
silently ignored when deciding capacity or uniqueness. Existing source bytes
must remain intact unless the user explicitly replaces or removes that file.
[Name lookup and catalog rules][sound-report]

Removing a custom tone does not require rewriting Alarm records. On the next
lookup, a nonempty saved name that no longer resolves falls back to the native
default object. This is the device's behavior, rather than a Host remapping
operation. Leave existing Alarm names unchanged. [Native fallback][tone-fallback]

The built-in row is special. Firmware tries the saved `Beep.tone`; when valid,
it uses those notes but replaces the file's header with the localized default
name. If the file is absent or invalid, it synthesizes
`[(540, 200), (676, 400)]` four times. That is 2400 ms. A Host preview can use the
captured valid file or that known fallback. Tone creation need not create,
replace or remove `Beep.tone`. [Default constructor][tone-default],
[Nano 5 constructor][nano5-default]

## Implementation recommendations

Keep encoding in iPodDB, with an explicit name and a typed sequence of
`AlarmToneNote`. Canonical authoring should validate name bytes, note count,
integer operands and duration bounds, then return bytes without filesystem I/O.
Keep the existing retained-byte parser for observed files; a new writer must
not normalize unrelated existing files.

The application should capture the selected Track through Storage, analyze its
audio on the Host, produce approximately seven seconds of pitch/rest pairs,
and preview the actual generated note sequence. Name editing and an explicit
save produce one source-checked Storage Transaction. Recheck Active iPod,
Filesystem Session, target support, tone inventory, language and relevant file
fingerprints before publication. Device mutation remains in Storage; no
Library save or Alarm edit is part of tone conversion.

No native format question blocks this implementation. Remaining acceptance is
the musical quality of melody extraction and physical playback quality, rather
than uncertainty about whether clean tone files, rests or the proposed pitch
range are consumed by these seven saved firmware versions.

[probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_tone_authoring_20261113.py
[receipt]: ../../../ipod-firmware-lab/artifacts/alarm-tone-authoring-20261113-v3.json
[sound-report]: alarm-sounds-clickwheel-2026-11-13.md
[driver-export]: ../../../ipod-firmware-lab/artifacts/tone-output-driver-20261113.txt
[tone-play]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-tone-init/08245034.c
[tone-scan]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-identity/0817f34c.c
[tone-fallback]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-core/0817f2b8.c
[tone-default]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-core/0817f12c.c
[nano5-default]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-nano5deep/08271f90.c
