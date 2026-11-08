# Mini 2 and Video date/time support audit

Investigated 2026-11-06. Scope: the application model and primary external source
evidence for Mini second generation, updater family 7 / 1.4.1, and Video updater
families 13, 20 and 25 / 1.3. This audit does not execute or modify device firmware.
The parallel native investigation owns instruction-level qualification. Its
confirmed Video result supports the narrow application correction below.
Application source citations refer to this working tree; external code citations
pin revisions.

## Findings and evidence boundaries

Mini 2's **2,876-byte Preferences is currently opaque**. This is a concrete support
gap, not an inference that Mini uses the fourth-generation layout. Independent
earlier firmware work gives Mini's format version as `0x16`; actual Mini 2 captures
also have this extent. Video's independently established extent/version is
**2,924 / `0x39`**. Before this investigation, iOpenPod interpreted its word at
`0xB22` using libgpod's timezone formula. That formula is a reference-library
convention. The parallel native investigation independently executed all three
Video images and disproved it: this is an **alarm word**, with minutes of day in
its low 12 bits and four preserved high bits. The app now rejects this exact
saved format as timezone evidence, preserving raw bytes and using its existing
date fallback. [Earlier firmware framing][eq], [Mini captures][mini-capture],
[definitions][definitions], [native report][video-report],
[native receipt][video-native], [native probe][video-probe]

Do not transfer Classic's city IDs, saved DST byte, software-correction offsets,
205-row annual rules, or PCF50635 register map to these targets. Rockbox selects
**PCF50605** for both Mini 2 and Video and implements a different RTC register bank.
That is useful hardware evidence, but it does not establish Apple firmware's UTC
or local-time policy. [Mini configuration][rockbox-mini],
[Video configuration][rockbox-video], [RTC implementation][rockbox-rtc]

The existing best-effort policy applies to both devices: missing or unusable
Preferences can use a valid database offset, then UTC when necessary. Calendar
uncertainty must not block Library loading, playback reconciliation or saving.
Neither fallback establishes historical DST or the location of an old event.
[ADR-0240][policy], [Device Time Context][device-time], [resolver][resolver]

## Application support and the Video correction

All Preferences offsets in this section are relative to the beginning of
`iPod_Control/Device/Preferences`, not a runtime owner object. Integers are
little-endian. The general codec selects exact known extents; its standard
profile does not validate a format-version word. Only the four Classic calendar
profiles have target-specific extent/version qualification. Mini and Video have
no corresponding positive clock profile. [Definitions][definitions],
[codec][codec], [application qualification][capture], [Classic targets][qualifier]

| Target or generic layout | Current interpretation | Limitation |
| --- | --- | --- |
| Mini 2, 2,876 bytes / `0x16` | Opaque retained document; no Preferences timezone | No supported definition has this extent |
| Generic fourth-generation, 2,892 bytes | Signed 16-bit code at `0xB10`; language byte at `0xAF8` | Not evidence for Mini's different extent |
| Generic Video, 2,924 bytes | Retained signed 16-bit legacy field at `0xB22`; language byte at `0xAF8` | Version `0x39` no longer produces a timezone; other versions retain the historical reference interpretation |
| Generic city layouts, 2,952/2,956/2,960 bytes | Signed 16-bit city ID at `0xB70` | No evidence that these are Mini 2 or Video 1.3 layouts |

The read-only `has_video13_framing` property observes the exact Video layout,
2,924-byte extent and little-endian version word `0x39`; it does not identify
the connected device. `timezone` returns `None` for that framing even if firmware
identity is absent. No-op serialization and language edits preserve the alarm
word and all other bytes. Editing the legacy `timezone_code` field now fails
the codec's existing invalid-timezone check. The app displays **Unknown** instead
of presenting alarm bits as a timezone code. This is a rejection of disproven
evidence, not a positive alarm-editing or clock-writing API.
[Document][models], [writer][codec], [inspection][capture], [resolver][resolver]

For the fourth-generation reference formula, accept raw `0..48`, subtract 25,
then compute `((adjusted >> 1) + (adjusted & 1)) * 3600`. For the historical Video
reference formula, compute `raw * 60 - 28800`, accepting only ±43,200 seconds
(raw `-240..1200`). The original tests prove these formulas and exact round trips
for authored bytes. They do not prove the fields' Apple-firmware meanings; the
exact Video `0x39` exclusion supersedes this formula for the latest targets.
[Projection][models], [codec tests][preference-tests], [libgpod][libgpod-zone]

The old Video formula would reject raw 1260, interpreted by that formula as
UTC+13. This is a **conditional limitation**, not proof that Apple saves a UTC+13
zone here. Since `0xB22` is alarm data on the inspected latest releases, expanding
the range would deepen the wrong interpretation; native field ownership
supersedes this range hypothesis for these targets.
[Projection][models], [reference bounds][libgpod-zone]

The application falls back to generic parsing when it cannot qualify a Classic
target. Thus a foreign file whose size matches a city layout could acquire a city
interpretation even when supplied with Mini or Video identity. No such file is
established by this audit. The actual Mini observation is 2,876 bytes and opaque;
the actual Video framing is 2,924 bytes. A future positive profile should qualify
an observed firmware format, not infer one from a neighboring generation.
[Capture service][capture], [earlier framing][eq]

Settings inspection remains read-only. The inverse codec can overlay fields on
retained bytes, but that is not a physical settings writer or proof that Apple
firmware reloads an edited file. The app's 1.1.1-only Video/nano volume-limit
extension does not apply to latest Video 1.3. No Mini/Video saved DST state,
software correction or `Device/dst` annual table is positively decoded.
[Capture service][capture], [codec][codec], [DST profiles][dst]

## Device Time Context and native date fields

`resolve_device_time` gives usable fixed-offset Preferences priority over the
database header. A usable city selects the Host's historical IANA rules. The
captured database offset remains independent evidence; it is not added again to
the Preferences result. A fixed offset has no historical transition information.
Unresolved Preferences use the captured header when valid; invalid or missing
usable evidence estimates UTC. Native-date decoding never consults the Host's
current timezone or clock. [Resolver][resolver], [Device Time Context][device-time]

`iTunesDB` root `MHBD +0x6C` is modeled as signed 32-bit seconds east of UTC.
The field needs at least `0x70` header bytes. An absent field in a short retained
header receives the schema default, zero; that is not evidence that the device
selected UTC. The actual audited Mini captures have 244-byte roots and offset
−14,400, so this absence distinction does not describe those captures.
[MHBD definition][mhbd], [bounded structure reader][binary], [Mini capture][mini-capture]

The following is the **current application interpretation**, not a claim that all
Mini/Video native consumers have been independently proven. Offsets are relative
to each `MHIT` header; all listed native words are unsigned 32-bit values.
[MHIT definition][mhit], [Library projection][projection]

| Field | Offset | Minimum header extent | Current date interpretation |
| --- | --- | --- | --- |
| Modified | `0x20` | `0x24` | Device-local Mac calendar seconds |
| Last played | `0x58` | `0x5C` | Device-local Mac calendar seconds |
| Added | `0x68` | `0x6C` | Device-local Mac calendar seconds |
| Released | `0x8C` | `0x90` | UTC Mac seconds; Host policy from other evidence |
| Last skipped | `0xA0` | `0xA4` | Device-local Mac calendar seconds |
| Historical `date_added_to_itunes` / purchase observation | `0xDC` | `0xE0` | UTC Mac seconds; Host policy from other evidence |

Mac date conversion uses the 1904 calendar epoch and a Unix difference of
2,082,844,800 seconds. Native zero means a missing ordinary date; explicit new
values are bounded instead of wrapping outside the unsigned 32-bit range.
Unchanged native words survive semantic projection, including dates whose exact
instant is uncertain. Absolute Smart date operands can represent Unix zero
without treating it as missing. [Device-time conversions][device-time],
[date policy][policy], [Smart writing][smart]

Header authoring sizes are not firmware maximums. Current creation policy chooses
156, 328, 504 or 624 bytes from the requested database version, while retained
headers keep their actual extent. The audited Mini captures include both 624-byte
Apple and 328-byte iOpenPod records. A date outside an available layout retains
its prior value with a warning rather than blocking publication. Tests cover this
for ordinary edits and playback-sidecar dates.
[Header policy][header-policy], [Mini observations][mini-capture],
[date resolution][resolution], [short-header tests][header-tests],
[sidecar tests][sidecar-tests]

Binary Play Counts dates currently share the local-Mac interpretation. Present
zero and backward event words can update dates independently of counters; absent
fields and the specifically recognized Finder sentinel retain the prior date.
This is the application's cross-device policy, with stronger native proof on
Classics than presently established here for Mini/Video. Do not mistake tests of
the common workflow for generation-specific firmware acceptance.
[Sidecar projection][sidecars], [ADR-0240][policy]

`iPod_Control/iTunes/iTunesPrefs` has no typed calendar field in the current
236-byte-prefix schema. The parser recognizes `frpd` and preserves later data.
Mini captures have 1,232-byte files, but their later Host-history tail is not an
established timestamp schema. This says **no date field is currently qualified**,
not that no date-like data can exist anywhere in the artifact.
[iTunesPrefs definition][itunes-definitions], [reader][itunes-codec],
[Mini observations][mini-capture], [earlier evidence][old-research]

## Primary external evidence and what it cannot prove

### libgpod

Pinned revision `7982c5554f78dde47fd006afbeff659201d6db3d` selects Preferences
interpretations by file length, reads signed little-endian 16-bit values, and
labels 2,924 bytes as observed on Video. It has no 2,876-byte Mini case. On unknown
formats it retains the Host's current timezone offset; iOpenPod deliberately
does not use that fallback. Its city conversion evaluates timezone rules at the
current time rather than each stored event. These are the library's choices,
not proof of stock firmware internals. [Timezone implementation][libgpod-zone]

The same revision converts released dates through its device-local conversion
function, unlike iOpenPod's UTC-Mac release-date policy. That disagreement is a
reason to preserve evidence and qualify actual target consumers, not to import
all libgpod date semantics as authoritative Apple behavior.
[libgpod Track import/write][libgpod-itunes], [iOpenPod projection][projection]

Its optional clock-sync tool sends a 12-byte calendar packet with big-endian
year and day-of-year, a quarter-hour timezone byte, hour/minute/second, a DST byte,
and padding. The default source is Host `localtime`; the transport is a SCSI
WRITE BUFFER command. No target/release-specific acceptance or Apple receiver
semantics are proven merely by this tool's presence. This audit does not run it.
[libgpod packet and transport][libgpod-scsi]

### Rockbox

Pinned revision `6256979302a57d6aaf2bf48555666fbb0fd8521f` selects
`RTC_PCF50605` in both target configuration files. Its RTC reader and writer use
seven bytes at `0x0A..0x10`: seconds, minutes, hours, weekday, day, month and year.
They convert BCD and interpret year as 2000 plus the stored year. The reader
recalculates weekday/year-day. Alarm paths use `0x11..0x17`; `rtc_init` checks
alarm-start state rather than seeding a documented UTC epoch.
[Mini config][rockbox-mini], [Video config][rockbox-video], [RTC driver][rockbox-rtc]

These are PMU hardware registers, **not files or Preferences offsets**. The driver
does not establish stock Apple timezone selection, saved software correction,
automatic DST, or historical date domains. Nor do its observations about bootloader
alarm handling prove every Apple boot image follows one initialization path.
The different chip/bank prevents carrying Classic's PCF50635 `0x59` analysis over
without new evidence. [RTC driver][rockbox-rtc], [Classic clock boundary][classic-clock]

Apple's official product-document pages identify distinct Mini and original/late
2006 Video documentation targets. UI instructions can establish visible controls;
they cannot by themselves establish a file offset, PMU register convention, or
transport packet. Detailed manual interpretation belongs with the parallel native
report, not this application-source audit.
[Mini documentation][apple-mini], [Video documentation][apple-video],
[Apple model descriptions][apple-models]

## Narrow corrective direction and remaining work

1. Qualify Mini 2's actual `2876/0x16` saved clock fields, timezone selection and
   DST before adding a decoder. Until then, preserve the file and use diagnosed
   database-offset/UTC estimates. Never force the 2,892-byte formula onto it.
2. Completed: independently loaded Video 13/20/25 native execution identifies
   `0xB22` as alarm data. The exact `2924/0x39` exclusion suppresses its timezone
   interpretation even without model identity, preserves the document/public
   field API, and rejects new purported timezone edits. No replacement
   Preferences timezone field has been established in this audit.
3. A future positive Video profile can expose independently established fields
   such as language. It must not imply that an alarm record is a geographical
   timezone, and it must distinguish saved bytes from live firmware state.
4. Verify Mini/Video playback and import date domains, clock-setting correction,
   manual/automatic DST behavior, Smart date comparisons, and boot/RTC provenance
   independently. General conversion tests and alternate firmware cannot close
   those Apple-native questions.
5. Keep regression coverage for header fallback, nonblocking save, unchanged
   native dates and Preferences bytes, short headers, invalid offsets, and exact
   firmware gates. No physical clock-setting or Preferences writer follows from
   this audit. [Policy][policy], [existing tests][time-tests]

## Validation of the correction

The codec regressions use native alarm vectors `0x0000`, `0x01E0`, `0xA2F2`
and `0xF59F` and verify no-op/language byte preservation, suppressed timezone
interpretation, and rejection of new false timezone edits. Adjacent and high-bit
version words do not accidentally trigger the exclusion. Virtual integration
covers all three updater identities plus missing firmware identity, a nonzero
header offset, literal native date preservation, the unknown-zone Settings row,
diagnosed fallback and successful publication without changing Preferences.
The focused codec/inspection/integration run passed 650 tests; Ruff and full
Mypy passed. These are application checks; the native receipt separately records
87 bounded original-instruction cases and 72 hashed spans across the three
Video images.
[Codec tests][preference-tests], [integration tests][time-tests],
[native receipt][video-native]

[eq]: ipod-eq-evolution-and-device-support.md
[mini-capture]: mini2-finder-comparison-2026-10-22.md
[definitions]: ../../src/iPodDB/preferences/definitions.py
[models]: ../../src/iPodDB/preferences/models.py
[codec]: ../../src/iPodDB/preferences/codec.py
[capture]: ../../src/iOpenPod/app/services/ipod_preferences.py
[qualifier]: ../../src/iOpenPod/app/services/classic_calendar.py
[resolver]: ../../src/iOpenPod/app/services/device_time.py
[device-time]: ../../src/iPodDB/device_time.py
[dst]: ../../src/iPodDB/preferences/dst.py
[mhbd]: ../../src/iPodDB/iTunesDB/shared/chunk_defs/mhbd.py
[mhit]: ../../src/iPodDB/iTunesDB/shared/chunk_defs/mhit.py
[binary]: ../../src/iPodDB/shared/binary_struct.py
[projection]: ../../src/iPodDB/library/_projection.py
[resolution]: ../../src/iPodDB/library/_date_resolution.py
[smart]: ../../src/iPodDB/library/_smart_writing.py
[sidecars]: ../../src/iPodDB/library/_sidecar_projection.py
[header-policy]: ../../src/iPodDB/library/_track_header_expansion.py
[itunes-definitions]: ../../src/iPodDB/preferences/itunes_definitions.py
[itunes-codec]: ../../src/iPodDB/preferences/itunes.py
[preference-tests]: ../../tests/iPodDB/test_preferences.py
[time-tests]: ../../tests/iOpenPod/app/services/test_device_time_integration.py
[header-tests]: ../../tests/iPodDB/library/test_device_header_layouts.py
[sidecar-tests]: ../../tests/iPodDB/library/test_sidecar_projection.py
[policy]: ../adr/0240-treat-calendar-dates-as-best-effort-metadata.md
[old-research]: ipod-preferences.md
[classic-clock]: classic-later-boot-rtc-2026-11-05.md
[video-report]: ../../../ipod-firmware-lab/notes/video-datetime-2026-11-06.md
[video-native]: ../../../ipod-firmware-lab/artifacts/video-datetime-20261106-v1/native-v3.json
[video-probe]: ../../../ipod-firmware-lab/scripts/probe_video_datetime.py
[libgpod-zone]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_tzinfo.c#L117
[libgpod-itunes]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L2503
[libgpod-scsi]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/tools/ipod-scsi.c#L104
[rockbox-mini]: https://github.com/Rockbox/rockbox/blob/6256979302a57d6aaf2bf48555666fbb0fd8521f/firmware/export/config/ipodmini2g.h
[rockbox-video]: https://github.com/Rockbox/rockbox/blob/6256979302a57d6aaf2bf48555666fbb0fd8521f/firmware/export/config/ipodvideo.h
[rockbox-rtc]: https://github.com/Rockbox/rockbox/blob/6256979302a57d6aaf2bf48555666fbb0fd8521f/firmware/drivers/rtc/rtc_pcf50605.c
[apple-mini]: https://support.apple.com/en-us/docs/ipod/122741
[apple-video]: https://support.apple.com/en-us/docs/ipod/130710
[apple-models]: https://support.apple.com/en-us/103823
