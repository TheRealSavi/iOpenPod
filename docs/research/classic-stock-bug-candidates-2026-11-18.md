# Stock Classic 2.0.5 bug candidates

Research date: 2026-11-18. This is a candidate list, not an implementation plan.
No firmware or device changes were made. Public patch authors' tests are reported
evidence, not independent reproduction in iOpenPod. RepriseOS explicitly builds
against Apple **2.0.5** for its supported Classics, making its native-reader
patches relevant to our exact base; integration still needs preimage and runtime
qualification. [Project target](https://github.com/lgreitis/osos-lab#readme)

The local unmodified `Classic38FW/decrypted/osos.bin` has SHA-256
`d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224`.
An independent read of that binary found **`0xe1a01fc0` at all three overflow
sites** below, and **`0x081bd1cc` in seek slot `0x08994a68`**, matching the proposed
patch targets. This corroborates applicability to our exact input; it does not
execute or independently reproduce the audiobook failures.
[Local pinned input](../../../ipod-firmware-lab/Classic38FW/decrypted/osos.bin)

Follow-up: the user authorized candidates 1 and 2. Both are now implemented
in 0.7.0-dev with independent native tests and additional state/error handling.
See [implementation evidence and limits](classic-long-audio-fixes-2026-11-18.md).
The original candidate assessment below is retained as research history.

## Strongest candidates

### 1. Long MP4 audiobooks stop around 13.5 hours

The reporter describes M4B playback glitching and skipping to another track.
The patch author identifies three MP4 edit-list comparisons that sign-extend
the low word of a 64-bit sample time. At `2^31` timescale units it becomes
negative: approximately **13:31:36 at 44.1 kHz**, or **12:25:39 at 48 kHz**.
The proposed fix loads the real high word at `0x081bb5e8`, `0x081bc0f4` and
`0x081bc114`. It is three instruction replacements, with no new image cache or
large payload. The author reports original-HDD playback beyond 15 hours and a
successful seek to 13:51. [Report and physical-test discussion](https://github.com/lgreitis/osos-lab/issues/18),
[patch and code](https://github.com/lgreitis/osos-lab/pull/62)

**Assessment:** the best first repair: concrete arithmetic defect, narrow patch,
and reported hardware evidence. Test both sides of the overflow boundary and
multiple timescales before integrating. PR **62 remains open and unmerged**;
its public proposal is not a released upstream fix.
[Current PR](https://github.com/lgreitis/osos-lab/pull/62)

### 2. Seeking late in long audiobooks times out

This is separate from the arithmetic overflow. The native MP4 seek walks samples
from its current state, or from the beginning for backward/fresh seeks. The
proposed fix uses the time-to-sample and sample-to-chunk tables to jump near the
target, then lets the original walker finish within that chunk. It replaces the
reader's seek slot at `0x08994a68` and adds roughly 2 KiB of code. The author
reports more than nine seconds for an unpatched late seek on an original HDD,
causing playback to abandon the file, versus about one second when patched.
[Implementation and measurements](https://github.com/lgreitis/osos-lab/pull/63)

**Assessment:** strong second candidate, but larger validation surface. The author
compared ten forward/backward/repeated seeks through the original and modified
reader with identical resulting state. Tests covered a 16-hour book; flash/SD,
other sample rates, longer books and multi-edit/large-table fallback paths were
explicitly untested. PR **63 remains open and unmerged**. The two audiobook fixes
address independent defects, and long books can need both.
[Scope and limits](https://github.com/lgreitis/osos-lab/pull/63)

## Candidates requiring an end-to-end reproduction

### 3. Calendar conversion uses current DST rather than the event date

Our native experiments on the exact Classic 38 / 2.0.5 image executed converter
`0x08292170` with parsed STANDARD/DAYLIGHT recurrence and transition data. All
sixteen January/July/spring/fall vectors selected the offset from the **current
device DST flag**, not the supplied event date. This could yield an hour error
for events in the opposite season. However, the complete Calendar query and
physical reminder scheduler were not covered: this is a proven conversion-path
behavior and a suspected user-facing bug, not proof that every reminder is wrong.
[Local executed-firmware evidence](calendar-timezones-and-reminders-2026-11-09.md#same-day-follow-up-parsed-transition-data-on-video-classic-and-nano-13)

**Assessment:** technically actionable but more involved. Reproduce through a
real event query/display before choosing whether to patch selection, conversion
or scheduling; preserve ambiguous/nonexistent-time semantics deliberately.

### 4. Idle clock ignores the 24-hour setting

A reporter explicitly using **stock OS**, before installing custom firmware,
says the clock lockscreen stays in AM/PM despite the 24-hour preference. Their
exact firmware version is unstated, so this is **not yet confirmed on 2.0.5**.
[Firsthand report](https://github.com/lgreitis/osos-lab/issues/68)

**Assessment:** a promising small UI repair if reproduced on our target. Inspect
which preference the idle-clock formatter reads; do not treat the accompanying
requests for backgrounds/layout customization as bug evidence.

## Scope boundaries

- RepriseOS dark-mode, custom-EQ and added Album Artist behavior are not evidence
  of stock Apple defects. [Dark-mode report](https://github.com/lgreitis/osos-lab/issues/25),
  [custom-EQ report](https://github.com/lgreitis/osos-lab/issues/49)
- Large-library memory work is a separate optimization project. PR 61 reports
  emulator-only improvements, mixes native-cache changes with added Album Artist
  data, and still documents failures above 65,535 tracks and in a large play-all
  queue. It does not establish a safe universal track-limit patch.
  [Proposal and limitations](https://github.com/lgreitis/osos-lab/pull/61)
- Our repaired Now Playing hover preview was a custom binding to Apple's native
  image model. Its exposed drawing defect should not be presented as proof that
  unmodified Apple 2.0.5 has the identical user-visible menu failure.
  [Our capture and fix](classic-now-playing-render-mode-2026-11-18.md)

Recommendation: investigate the three-instruction audiobook overflow repair
first, then long-file seeking. The clock preference is the smaller alternative
if the next goal is a visible UI fix rather than audiobook support.
