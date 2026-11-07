# Non-blocking iPod dates: firmware evidence and Host policy

Research date: **2026-11-05**. This review supports the requested policy that
date/time uncertainty must not prevent loading or saving an iPod. It revisits
the retained Apple firmware instructions, reruns byte checks and bounded models,
and compares the Original iOpenPod implementation. It does not execute firmware,
access a physical iPod, or infer the exact timestamp in the issue reporter's
unavailable files.

## Finding

The inspected Classic firmware treats playback dates as stored calendar words.
Its Play Counts reader copies those words without resolving a timezone, rejecting
a repeated hour, or requiring increasing dates. Requiring a unique UTC instant
before importing those words is an iOpenPod Host policy, not a condition imposed
by that firmware. Preserve the native words and use a deterministic approximation
when the Host needs an instant. [Play Counts reader][counts-read],
[play event][play], [skip event][skip]

The evidence does not identify one universally correct UTC interpretation. The
format lacks the historical zone, manual clock corrections, and repeated-hour
identity needed to recover it. The requested availability policy can therefore
be implemented honestly as best effort without describing estimates as repaired
or recovered event times. [Event writer][play], [clock setter][setter],
[time-domain analysis][domains]

## Evidence identity and validation

| Item | Verified identity |
| --- | --- |
| Firmware | Classic 120GB, RetailOS 2.0.1, updater family 33 |
| Normalized OSOS | 10,513,984 bytes |
| OSOS SHA-256 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| Analysis baseline | osos-lab `d2c8e357d58591bdaa70bb6be9da191f489554a6` |
| Runtime map | `.dram` at `0x08000000`, image offset `0xb65c`; other regions follow the pinned profile |
| Profile SHA-256 | `b668b37155bea4ea1b4d4de545a01a5c047a4609d532b4421d34ced78ab5317c` |
| Original iOpenPod | `a20242428b93b672d14b37230772dbad75139c69`, local `origin/1.x` |

The [pinned profile][profile] supplies the exact input identity and runtime map.
All addresses below belong to this image; they are not portable addresses for
the reporter's Classic 160GB firmware. Function names beginning with `Research_`
are analyst names, not Apple source symbols.

Fresh read-only verification on this date passed:

- **29 playback/clock listings**, 13,144 unique instruction bytes, six literal
  guards, and 12 firmware-derived synthetic cases through
  `check_timestamp_discontinuities.verify()` and `.firmware_cases()`.
- **Seven DST function bodies**, 2,064 instruction bytes, ten literal guards,
  all 205 default rule rows, and the bounded transition checks through
  `check_dst_transition_rules.verify()` and `.checks()`.
- **30 settings function bodies** and the 205-city model through
  `check_timezone_settings.verify()` and `.models()`.

These groups overlap and must not be added into a distinct-function total.
The DST table SHA-256 is
`4d4bf7f9d0db2674e2905bcc53e0e9faefaba93b0024e6719fe01a611a05809e`.
Verification compares the exported instruction bytes to the original image;
the Python models then exercise reconstructed arithmetic. Neither step runs ARM
instructions or verifies physical scheduling. [Discontinuity checker][checker],
[DST checker][dst-checker], [settings checker][settings-checker]

The verification calls can be repeated from the firmware lab without producing
or overwriting an artifact:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))
import check_dst_transition_rules as dst
import check_timestamp_discontinuities as dates
import check_timezone_settings as settings

raw = Path("inputs/prepared-2.0.1/osos.bin").read_bytes()
rules, bodies, literals, table_hash = dst.verify(raw)
dst.checks(rules)
settings.verify(raw)
settings.models(raw)
dates.verify()
dates.firmware_cases()
```

Use the lab's UV environment with `uv run python -B` for this read-only script.
The earlier reports' comparisons against old iOpenPod working trees are historical
snapshots; they must not be read as a description of the implementation after the
new policy is adopted.

## What the Apple instructions do

### Playback dates remain raw during import and sidecar consumption

The Track importer copies MHIT `+0x58` to runtime Track `+0x98` and MHIT `+0xa0`
to runtime `+0xa8`. The sidecar reader at `0x080931a8` later replaces those same
runtime fields with Play Counts row `+0x04` and `+0x18`. Exact stores are at
`0x08093290` and `0x080932c8`. The surrounding code adds play/skip deltas, with
no date-specific branch between loading the date and storing it. Zero, a smaller
date, or an epoch-shaped word receives the same assignment. File framing and
read errors are separate conditions. [Track importer][track-import],
[Play Counts reader ARM][counts-read]

Writer `0x0809d024` copies the runtime date words back to those row positions
beside counter deltas. It does not resample the clock or re-encode the dates.
Thus a row with zero new plays can still carry a date, and date values do not
identify their origin as an event, imported MHIT field, or previously consumed
sidecar. [Play Counts writer][counts-write]

There is no special Finder/Core Data absent-date check in this Classic reader.
iOpenPod's exact binary-sidecar sentinel remains a separate inference from paired
Finder captures; the firmware review does not justify widening it to ordinary
Track dates or other sidecar formats. [Finder policy][finder],
[Play Counts reader][counts-read]

### Events store the adjusted calendar and tolerate clock setbacks

Play routine `0x082485f0` and skip routine `0x0824866c` obtain the adjusted compact
calendar through `0x0806d338` and call `0x08089380(calendar, 0)`. The zero argument
disables the wrapper's optional current-zone subtraction. They write the result
and increment counters without comparing the previous date. The wrapper adds
the verified epoch difference, 2,082,844,800 seconds. [Play ARM][play],
[skip ARM][skip], [time domains][domains]

The ordinary successful timezone/DST setter at `0x080ba8a0` computes this
32-bit relationship:

```text
new_calendar = old_calendar
             + 60 * (new_zone_minutes + new_dst_minutes
                     - old_zone_minutes - old_dst_minutes)
             modulo 2^32
```

A one-hour setback can therefore make a later accepted event's date smaller
while its count increases. The current saved DST byte and software bias are
already reflected in the calendar and must not be added to its dates again.
They do not describe every earlier event's settings. The setter has intermediate
callbacks; this arithmetic assumes successful application, not an atomic firmware
transaction. [Setter ARM][setter], [clock-provider analysis][provider]

### DST rules are firmware data, not a historical timezone database

The default table at `0x089a0d94` contains 205 16-byte rows. Loader `0x080dd958`
can replace it with `iPod_Control/Device/dst`. The examined rules have month,
weekday and week selectors, hard-coded 02:00 transitions, and a one-hour adjustment;
they do not contain per-year historical law. The predicate uses current saved DST
state in its arithmetic. This prevents claiming that modern IANA rules exactly
reconstruct the device's historical clock. [DST loader][dst-loader],
[DST predicate][dst-predicate], [table analysis][dst-analysis]

The bounded reconstruction also preserves nonstandard branches: a negative
weekday difference subtracts six days, and the February last-week seed differs
from the expected general rule. No enabled built-in row uses February. These are
specific instruction findings, not evidence that every firmware date is wrong.
[Transition builder][dst-builder], [DST checks][dst-checker]

### Invalid clocks and range limits do not establish one Host fallback

`0x08034848` substitutes **2002-01-01 00:00:00** when the lower clock-valid bit
is clear; literal `0x7d2` supplies the year. That calendar then reaches ordinary
consumers. This is a clock-provider fallback, not an instruction to replace
unfamiliar database timestamps with 2002. [Clock field bridge][clock-fields],
[clock-validity analysis][smart-time]

Calendar-word arithmetic has actual u32 wrap boundaries. The Smart day-bound
model obtains reversed/wrapped endpoints for native zero and `0xffffffff`;
comparators do not repair the interval. This does not justify reproducing wrapping
when the Host authors an out-of-range date. An explicit clamp or missing-date
fallback is an availability policy, not firmware parity. Valid native words
should remain intact regardless of how unusual their displayed date looks.
[Calendar boundary analysis][smart-time]

## Original iOpenPod comparison

At the pinned Original commit, `DeviceTimeContext.mac_to_unix` attaches the selected
timezone directly to the local calendar and calls `timestamp()`. It does not
perform the two-fold uniqueness test. This implicitly uses the default fold
interpretation and accepts gap labels. Its UTC default also permits operation
without a known device zone. The writer still raises on u32 overflow and collapses
nonpositive Unix dates to missing, so it is not a complete model for the requested
policy. [Original conversion][original-time]

Original Play Counts merging used the newer interpreted date and ignored zero
dates. The inspected Classic firmware instead replaces the raw words, including
backward dates and zero. Retain the newer firmware-backed replacement semantics;
only use the Original's non-blocking ambiguity behavior as a compatibility
baseline. [Original sidecar merge][original-counts],
[Classic sidecar reader][counts-read]

## Recommended Host policy and its limits

These are product recommendations under the user's instruction, not claims that
Apple selected the same UTC instants:

1. Preserve unchanged native date bytes. During binary Play Counts consumption,
   carry present raw played/skipped words into the database, including zero and
   words whose semantic projection collides with Unix zero. Keep absent optional
   fields and the exact Finder sentinel distinct from explicit zero.
2. Keep recognized historical city rules for ordinary dates. For a fold or gap,
   choose a stable, documented interpretation and mark it as estimated. Default
   fold-zero behavior matches the Original; a matching captured offset may be a
   deterministic preference, but neither proves the event's actual occurrence.
3. Use a valid captured fixed offset when geographical evidence is unavailable.
   If no usable offset exists, a deterministic zero-offset estimate is preferable
   to consulting the Host timezone or stopping the operation. Preserve the source
   timezone/header evidence rather than rewriting it to endorse the estimate.
4. Bound newly authored values to their destination representation, or retain an
   existing native value when the new date cannot be interpreted. Preserve the
   missing-date meaning of native zero. Explicit normalization must be used by
   preparation and verification alike, so a permitted approximation does not
   become a later verification failure.
5. Regenerate SQLite dates from the same best-effort semantic interpretation.
   An unresolved native date must not become a blanket SQLite-publication gate.
   Keep release/purchase UTC encoding and Core Data epoch conversion distinct
   from local-calendar fields; the paired captures support that distinction.
   [Paired capture evidence][paired]
6. Apply the same non-blocking treatment to date-only defects in plist sidecars,
   Photo dates, Smart absolute dates, imported metadata and display formatting.
   Invalid identities, counters, record extents and unsafe storage remain separate
   validation matters. A timestamp defect should not discard valid playback
   counters or require deleting a sidecar.

Raw preservation is especially important for a gap: interpreting its label as an
instant and encoding that instant back can produce a different local label.
Similarly, a nonzero native word can project to semantic Unix zero. Suppressing
the conversion exception alone is insufficient; the publication contract must
retain the original native intent in those cases.

No reviewed bytes can identify the reporter's offending Track, city or event
without their `Play Counts`, Preferences and corresponding database. The primary
firmware evidence here is Classic 120GB 2.0.1, not every Classic/nano/Shuffle
release. No live transition, filesystem write, firmware callback sequence, or
physical acceptance test was performed for this report.

[profile]: ../../../ipod-firmware-lab/vendor/osos-lab/ghidra/profiles/classic6g-reva-2.0.1.json
[checker]: ../../../ipod-firmware-lab/scripts/check_timestamp_discontinuities.py
[dst-checker]: ../../../ipod-firmware-lab/scripts/check_dst_transition_rules.py
[settings-checker]: ../../../ipod-firmware-lab/scripts/check_timezone_settings.py
[counts-read]: ../../../ipod-firmware-lab/artifacts/itunesdb201-pass1/080931a8-FUN_080931a8.asm.txt
[counts-write]: ../../../ipod-firmware-lab/artifacts/itunesdb201-semantics-pass1/0809d024-Research_PlayCounts_WritePositionalDeltas.c
[track-import]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-preferences-copy/08073bb8-ITunesDB_ImportTrackDataset.asm.txt
[play]: ../../../ipod-firmware-lab/artifacts/itunesdb201-time-location-unitsets/082485f0-Research_MediaItem_RecordPlay.asm.txt
[skip]: ../../../ipod-firmware-lab/artifacts/itunesdb201-time-location-unitsets/0824866c-Research_MediaItem_RecordSkip.asm.txt
[setter]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-settings/080ba8a0-FUN_080ba8a0.asm.txt
[provider]: ../../../ipod-firmware-lab/notes/itunesdb/clock-provider-and-adjustment.md
[domains]: ../../../ipod-firmware-lab/notes/itunesdb/database-time-domains.md
[dst-loader]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-dst-transitions/080dd958-FUN_080dd958.asm.txt
[dst-predicate]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-dst-transitions/080ddebc-FUN_080ddebc.asm.txt
[dst-builder]: ../../../ipod-firmware-lab/artifacts/itunesdb201-clock-dst-transitions/080dd59c-FUN_080dd59c.asm.txt
[dst-analysis]: ../../../ipod-firmware-lab/notes/itunesdb/dst-transition-rules.md
[clock-fields]: ../../../ipod-firmware-lab/artifacts/itunesdb201-time-location-unitsets/08034848-FUN_08034848.asm.txt
[smart-time]: ../../../ipod-firmware-lab/notes/itunesdb/smart-time-rules.md
[finder]: ../adr/0150-retain-firmware-sqlite-metadata-and-dual-signatures.md
[paired]: ipod-time-reconciliation.md
[original-time]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/device_time.py
[original-counts]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_parser/playcounts.py
