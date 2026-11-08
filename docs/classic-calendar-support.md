# Latest Classic calendar support and remaining questions

Scope: Classic 6, 6.5, 7 and 7.5, using only each updater family's latest offered
firmware. Checked November 5, 2026, America/Detroit. The names 7 and 7.5 are this
task's labels for updater families 35 and 38; they are not separate Apple retail
model categories established by the current evidence.

The November 6 [Calendar and Alarm follow-up](research/calendar-alarm-firmware-2026-11-06.md)
independently exercises Calendar parser and Alarm record/repeat paths on all four
latest inputs. It adds the `Device/alarms` token format and a per-target research
matrix; whole-file Calendar acceptance, complete notification delivery and
physical wake remain distinct open questions.

## Supported targets

| Target | Updater family | Latest firmware | Preferences bytes / version | Saved clock inspection | Saved annual DST file |
| --- | ---: | --- | --- | --- | --- |
| Classic 6, 80/thick 160 GB | 24 | 1.1.2 | 2,952 / 0x3c | Qualified | Opaque; no qualified consumer in inspected paths |
| Classic 6.5, 120 GB | 33 | 2.0.1 | 2,956 / 0x3d | Qualified | Headerless 205 ordered rows; week 4 means last |
| Classic 7, thin 160 GB | 35 | 2.0.4 | 2,956 / 0x3e | Qualified | Two opaque prefix bytes, 205 rows; week 4 means fourth, 5 means last |
| Classic 7.5, later 160 GB branch | 38 | 2.0.5 | 2,960 / 0x3f | Qualified | Same qualified framing and week meanings as family 35 |

Apple's current catalog and all four retained IPSW manifests agree on these
separate latest branches. In particular, 2.0.5 does not supersede 2.0.4 for
updater family 35. See the [identity report](research/classic-latest-firmware-targets-2026-11-05.md).

The common application support is now:

- Full u32 saved city identity, raw Saved DST State and signed-day/raw-seconds
  clock correction, with format and extent qualified independently per target.
- Read-only settings inspection through Storage. Unknown bytes and unchanged
  native dates remain byte-exact; optional files never become save dependencies.
- Historical city rules, captured fixed-offset fallback, then UTC as best-effort
  interpretation. Saved bias and DST are not added to dates a second time.
- Non-blocking folds, gaps, missing/unsupported calendar evidence and out-of-range
  date metadata. Playback counters still apply, exact binary date words survive,
  and the original consumed sidecar is archived verbatim.
- Strongest-authority identity selection. Live metadata can supersede a stale
  cache; conflicting strongest observations remain unqualified. Families 35/38
  require explicit updater identity because MC293/MC297 and capacity do not
  distinguish them. Known Classic 6/6.5 model-plus-release fallback remains an
  application inference when no updater ID is available.
- A qualified target with an unexpected Preferences format stays opaque instead
  of allowing an unknown full city ID to alias a known low halfword.

The firmware checks bind instruction spans, operands and call targets to exact
image hashes. They establish static contracts and bounded reconstructions. The
DST-prefix follow-up additionally executes selected original ARM functions under
Unicorn with explicit service mocks; this is not whole-OS or physical acceptance
of a settings write. There is no device clock writer or firmware installation in
this work.

## What we understand at the same evidence level

All four latest images have independently inspected Preferences load/default/write
paths and city/DST/bias fields, adjusted-calendar paths, manual offset changes,
play/skip date routes, binary Play Counts copies and Smart date comparison paths.
The [Classic 6 report](research/classic6-latest-calendar-contract-2026-11-05.md),
[Classic 6.5 baseline](research/classic201-clock-semantics-2026-10-26.md),
[clock follow-up](research/clock-adjustments-and-date-comparisons-2026-11-06.md) and
[later Classic report](research/later-classic-latest-calendar-contracts-2026-11-05.md)
record their exact proof scope and limitations. ADR-0240 supersedes the baseline
report's former blocking conversion policy.

Shared fields do not mean identical firmware behavior. Classic 6's inspected
routes retain/manual-toggle DST; its clock poll lacks the later automatic
predicate calls. Families 33/35/38 have the automatic edge-driven refresh route.
The later builders also correct earlier weekday/February arithmetic and change
week selectors. City-table offset codes themselves differ: the same geographic
selection cannot be decoded by applying another generation's numeric code table.
Current firmware offsets are not historical IANA rules.

Smart date comparison remains an explicit application-policy boundary. Inspected
firmware uses native calendar-day bounds and signed 64-bit arithmetic; the current
Host preview uses rolling durations. This can differ around midnight, DST or
future dates after a clock setback. Current support preserves unsupported rules
and saved membership; no unannounced preview-policy change follows from finding
more matching firmware consumers.

## Clock and prefix follow-up

The [raw-clock investigation](research/classic-raw-clock-origin-followup-2026-11-05.md)
traces the same Host calendar import chain in all four images: SCSI `WRITE BUFFER`
mode one receives a 12-byte calendar payload and applies the requested calendar
through software correction. Its timezone byte is signed quarter-hours, with
the supplied effective offset reduced by one hour when DST is nonzero. The
setter updates live clock metadata. The
[notification trace](research/classic-clock-notification-effects-2026-11-05.md)
now follows the queued application handler that mirrors this correction,
reconciles the city, normalizes Saved DST State to 0/1 and marks Preferences dirty.
Classic 6 matches base offset; later targets also compare current-date DST.
No match can yield city zero, which remains an unresolved zone in iOpenPod.
Queue delivery and disk persistence are separate boundaries.
The matching read command returns the adjusted calendar, not a raw RTC
measurement. This explains a Host-set calendar without establishing how the Raw
Hardware Clock was originally initialized. The known command is not a reason to
add the saved correction to old Track dates or expose a device-clock writer.

The [observer investigation](research/classic-clock-change-observers-2026-11-05.md)
resolves the deferred collection's concrete members and vtable targets in all
four latest images. They are MediaItem objects whose selected method refreshes a
protected-media timing cache. That method does not directly rebase ordinary Track
date fields or refresh Smart day contexts. The inspected Smart membership loops
initialize a fresh context, then reuse its lazily sampled day bounds for that
evaluation. Which notifications schedule a later evaluation is still a separate
question; identifying this callback does not close every indirect side effect.

The [prefix investigation](research/classic-dst-prefix-consumers-2026-11-05.md)
accounts for the identified literal references and state users in both later
images. The loader retains two bytes, but the checked rule consumers use a fixed
205-row bound without reading them. All 24 bounded native probes passed, including
six prefix values, an extra row, short reads and reload fallback. A retained
prefix can outlive selection of the custom rows. Its producer and wider meaning
remain unknown; the application preserves the bytes without interpreting a
version, row count, byte order or active-table state.

## Boot and Disk Mode follow-up

The supplied Classic 6.5 successfully decrypted the three previously missing
latest AUPD images using temporary RAM execution. The
[acquisition record](research/classic-aupd-hardware-acquisition-2026-11-05.md)
preserves exact hashes and cleanup results. The device returned to its normal
menu; no firmware was installed. Firmware remains local research input, not an
application dependency.

The [early boot trace](research/classic-early-boot-rtc-2026-11-05.md) and
[later boot trace](research/classic-later-boot-rtc-2026-11-05.md) now qualify all
four latest loaders independently. Their reachable early PMU initialization has
21 writes, including `0x58=0`; no identified written span addresses the RTC
calendar/alarm/retained-metadata range `0x59..0x6e`. Classic 6 differs in two
initialization payload bytes. The exact hardware effect of register `0x58`
remains unknown, so this does not prove that boot leaves the Raw Hardware Clock
unchanged or that it uses UTC. The extracted EFI PMU interface and its identified
Ata consumer also do not establish a civil-calendar seed.

The separate updater traces on all four targets distinguish embedded image bytes
from each updater's executable map. Independently inspected Disk Mode images on
all four targets have their own adjusted-calendar and Host-import paths. Their
identified raw write selects the alarm bank; their year-2000 fallback initializes software
metadata. Those paths do not establish the original running RTC date. Each report
keeps its exact target, image map, emulator mocks and unresolved call boundaries
explicit.

## Remaining questions by target

| Target | Questions still requiring evidence |
| --- | --- |
| Classic 6 / 1.1.2 | Is there any automatic-DST or custom-rule consumer outside the inspected manual/retained-state routes? Do physical restart and Host synchronization observations match the traced persistence paths on both 80 GB and thick 160 GB devices? Do physical vendor captures corroborate updater/release qualification on both capacities? |
| Classic 6.5 / 2.0.1 | How does manual DST interact with a later automatic predicate edge, suspend and restart on real hardware? Do the reconstructed weekday and February edge cases manifest when those selectors are exercised? Do MB562 and additional MB565 units report consistent updater/release evidence? |
| Classic 7 / 2.0.4 | Which producer supplies the opaque DST prefix, and does anything outside the checked consumers interpret it? What physical board/retail/serial evidence identifies updater family 35 independently of its reported firmware? Do physical transitions and short-file behavior match the bounded models and native probes? |
| Classic 7.5 / 2.0.5 | What establishes the hardware boundary between updater 38 and 35, and which identity fields reliably report it? Which producer supplies the prefix, and does any untraced consumer use it? Do physical transitions, persisted state and custom-file behavior match the independently inspected later paths and native probes? |

These questions apply to **every** target as well:

1. What initializes the Raw Hardware Clock on factory setup, complete power loss
   and boot, and which other setters can reach it? The inspected SCSI calendar
   command updates software correction; it does not establish the running RTC's
   UTC/local basis. All four latest loaders now have qualified early PMU traces,
   but the exact effect of register `0x58`, BootROM/factory initialization,
   diagnostic-image clock paths and complete power-loss behavior remain
   unresolved. Epoch-like constants and saved correction alone do not prove a
   calendar origin.
2. What do the remaining notification recipients and indirect query callees do,
   and what schedules Smart membership evaluation after a clock change? The
   deferred MediaItem collection, fresh per-evaluation Smart context, queued Host
   handler and Settings DST persistence are now identified, including the
   thread-identity delivery gate. Actual queue acceptance, delivery timing,
   downstream UI notifications and Smart refresh scheduling still require
   separate evidence; dirty Preferences do not prove a disk flush.
3. Which geographical city does numeric ID 0x26 actually identify? Each inspected
   firmware assigns -300 minutes, conflicting with the inherited London mapping.
   Its localized Apple resource identity remains unresolved.
4. Do physical devices match the bounded static models at folds/gaps, clock
   setbacks, restart, alarm boundaries and native date-range limits? These are
   acceptance questions, not reasons to block ordinary Library work.

Some information is absent from the format, rather than merely unresearched:
an old calendar word has no historical city selection, fold occurrence or record
of a wrongly set clock. More firmware research cannot uniquely reconstruct those
facts from that word. Dates therefore remain estimates, and counts/native evidence
remain usable regardless.

## Implementation and checks

[ADR-0242](adr/0242-qualify-the-latest-classic-calendar-targets.md) records target
qualification and [the Preferences contract](ipod-preferences.md) documents the
byte APIs. Authored tests cover every latest profile, full-width city IDs, clock
field protection, exact preservation, unknown framing and unresolved identity.
Virtual devices cover all four targets, live-versus-cached authority, optional DST
files, fold/gap playback reconciliation and saves after clock evidence changes.
The follow-up adds all-four reload/save cases proving six native date fields
survive changed city, Saved DST State and Saved Clock Correction observations,
plus prefix-invariance cases matching the six native-probe values on both later
profiles. A changed city can change displayed instants without rewriting history.
Reload/save cases also cover firmware-selected city zero, unresolved city `0x26`
and an unknown full-width city ID; the resulting uncertainty stays warning-only.
The ordinary test suite requires no firmware binaries or connected iPod.

Validation for this increment: **11,445 passed, 47 skipped** in the normal full
suite. The sole warning is the existing deliberately large Photo fixture.
UV lock validation, Ruff formatting/lint, Mypy and Markdown checks passed.
