# Mini 2 and Video: datetime differences from Classic

Investigated 2026-11-06. Scope is the latest retained Apple releases: Mini 2
family 7 / 1.4.1 and Video families 13, 20 and 25 / 1.3. This is a bounded
offline investigation of original firmware instructions, with synthetic hardware
responses for native probes. It is not a physical-device test or a complete
calendar implementation. Older releases are outside the qualification.

## Why these targets matter

These devices provide additional evidence rather than simply repeating the
Classic model. Mini 2 changes the hardware calendar when changing timezone, while
the latest Classics' traced adjusted-calendar paths use a software correction.
Video's retained Preferences offset inherited from libgpod is contradicted by
its native scheduling code. Treating all click-wheel models as one clock contract
would therefore lose information and can misinterpret unrelated settings.
[Mini native evidence][mini], [Video native evidence][video],
[Classic comparison][classic], [application audit][support]

| Target | Established difference | Application implication |
| --- | --- | --- |
| Mini 2 / 1.4.1 | Preferences is 2,876 bytes, format `0x16`; its timezone menu has 50 selections and reaches effective UTC+13. The traced selection path rebases the BCD hardware calendar. | Do not reuse the 2,892-byte fourth-generation decoder or the Classic correction fields. Current Mini Preferences remain opaque and date conversion uses the existing database-offset/UTC estimate. |
| Video 5 / 1.3 | Preferences is 2,924 bytes, format `0x39`. File `+0xb22` participates in saving a scheduled time with a Playlist selection. | The inherited `raw * 60 - 28800` timezone interpretation is not valid evidence for this format. Withhold it and use the existing nonblocking fallback. |
| Video 5.5 / 1.3 | The independently retained family 13/20 images match, and family 25 adds only a zero tail. The inspected calendar code is shared. | Share verified code findings across these exact inputs; do not infer that every model-dependent runtime path or clock initialization is identical. |

The Preferences lengths and versions also agree with the independent
[EQ support investigation][eq]. File offsets below refer to serialized payloads,
not owning objects in memory. The Mini/Video owners serialize from `owner + 8`;
the latest Classic layouts use a different owner/payload relationship.
[Mini evidence][mini], [Video evidence][video]

## Input identity

| Input | OSOS bytes | SHA-256 |
| --- | --- | --- |
| Mini 2, family 7 / 1.4.1 | 3,402,816 | `346504450c5201a632cafa38312093fc04b402b4ca37c79d7ca4a4167bb8f34d` |
| Video family 13 / 1.3 | 7,559,680 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| Video family 20 / 1.3 | 7,559,680 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| Video family 25 / 1.3 | 7,561,216 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` |

Family 25's extra 1,536 bytes are zero; it remains a separately hashed complete
input. Addresses in the lab reports use each image's established runtime map,
including startup copies and BSS. Hash equality of executable bytes does not
replace checking hardware/model branches. [Mini map][mini-map],
[independent Video acquisition and maps][video-inputs]

## Mini 2: local clock evidence, not a universal UTC RTC

The live calendar getter at `0x0008370c` separates an effective whole-hour offset
from a DST component. The 50-entry menu table at `0x00192270` contains 25
standard/DST pairs. The native selection path can change the hardware calendar
and reaches effective offsets from -12 through +13 hours. The bounded probes
observe writes to BCD calendar registers `0x0a..0x0c` and `0x0e..0x10` through
bus endpoint 8. This is Apple instruction evidence, beyond merely identifying
the PMU from another implementation. [Native trace and limits][mini]

Playback function `0x00047f0c` stores a 1904-epoch value at the runtime Track
object's `+0x98`, derived from the wall-calendar components without subtracting
the current offset. That runtime object offset is not an iTunesDB file offset.
It supports the local-Mac-date interpretation of this traced playback producer;
it does not establish every Track, Photo or Smart Playlist date consumer.
[Producer and conversion wrappers][mini]

The Mini importer links MHIT `+0x58` to that runtime last-played field. Its
Play Counts writer copies the same word to record `+4` in a 20-byte record,
after a 96-byte header; the reader copies it back. Thus the local-calendar
producer shares a runtime field with MHIT import and sidecar storage. Separately, a Smart
date context builds and caches the current wall day's `00:00:00..23:59:59`
bounds. That is calendar-day arithmetic, not a rolling 24-hour UTC interval.
Complete Smart comparison/refresh scheduling remains open. [File and Smart traces][mini]

The saved selection is a little-endian u32 at file `+0xb10` (owner `+0xb18`).
The selection reader consumes its signed low 16 bits only when the live offset
is invalid: values 1..50 select table entries, and zero selects the default
standard -8-hour entry. Valid live offset/DST metadata takes precedence over the
saved selection. The UI initialization path applies the saved fallback only
when the live offset is invalid. A valid-looking file selection therefore does
not establish the current live offset. [Selection fallback probes][mini]

Consequently, a timezone change can alter subsequently observed playback labels.
The saved menu selection is neither a complete live-clock observation nor the
historical settings for every event. It cannot reconstruct travel, manual corrections or the two
occurrences of a repeated hour. Do not apply current DST again to a date word
already produced from the adjusted wall calendar. [Native evidence][mini],
[best-effort date policy][policy]

The actual 2,876-byte Preferences file is currently preserved as Unknown Data by
iOpenPod. This is distinct from the generic fourth-generation code at the same
nominal offset in a differently sized file. A future Mini profile needs its own
version/extent qualification and an explicit policy for the saved-selection/live
metadata disagreement; decoding the table alone cannot resolve it.
Its UTC+13 case must not inherit a ±12-hour validation assumption.
[Support audit][support]

Invalid clock handling also needs field-specific interpretation. The Mini's
public getter can return **2002-01-01** while reporting a valid offset; date
validity and offset validity are different bits. An initializer's separate
**2000-01-04** RAM fallback does not prove that the hardware RTC is initialized
to that date. The `rtcV` handoff record preserves offset/DST metadata, but its
complete shutdown, reset and power-loss lifecycle is still unqualified.
[Invalid-read probes and handoff trace][mini]

## Video: reject an alarm-derived timezone

The inherited Video decoder reads a signed 16-bit value at file `+0xb22` and
calculates `raw * 60 - 28800`. Native getter `0x0009b00c` and setter
`0x000b2d7c` access the corresponding owner field at `+0xb2a`. The UI save
path at `0x001935ec` calls `0x0021e4a4`, which derives hour/minute scheduling
data and stores minutes in the low 12 bits; adjacent code saves a Playlist
selection. This contradicts interpreting that field as a fixed UTC offset.
[Instruction, serialization and scheduling evidence][video]

The correction is deliberately confined to the known 2,924-byte format with
version `0x39`. Its timezone projection is unresolved even without device
identity, so incomplete identity cannot fall through to the disproved formula.
Raw source bytes and language inspection remain available. Library conversion
uses a valid captured database offset, or an explicit UTC estimate; the absence
of valid timezone evidence cannot block loading or saving. Historical unrelated
formats do not acquire a new interpretation from this investigation.
[Support audit][support], [Preferences contract][preferences], [date policy][policy]

Video's real runtime clock metadata includes an offset expressed in quarter-hour
units and a separate DST byte. A runtime record is not automatically a saved
Preferences offset or proof of the RTC's initial timezone. The native report
separates those paths from the disproved alarm-derived interpretation. [Video evidence][video]

The provider selected by the three inspected images reads BCD calendar bytes at
`0x0a..0x10`; native probes capture the corresponding writer's register operations.
The statically traced timezone setter adjusts that calendar by the difference
between old and new quarter-hour offsets before calling the BCD writer when
calendar and zone metadata are valid. This also differs from the Classic
software-correction path. The Video calendar adapter shares the Mini's
**2002-01-01** invalid-date fallback, but the persistence and origin of its
separate clock-metadata buffer remain unidentified. [Provider and setter evidence][video]

Native probes also distinguish Video's calendar conversions: its current-calendar
to Mac-word path handles pre-1970 civil dates, while a separate calendar-to-Unix
conversion clamps them to zero. Repeated or skipped wall-clock labels are plain
civil arithmetic in the probed Mac path, not a request to apply modern IANA
validation. Which helper a field's producer calls matters more than the mere
presence of a Unix or Mac conversion function elsewhere in the firmware.
[Conversion probes][video]

The Video 2041 probe wraps in the native 32-bit Mac producer. iOpenPod retains
existing raw words but bounds newly authored out-of-range dates; it does not
copy this overflow into its authoring policy. The native date-bound cache also
constructs and reuses civil-day limits. Its invalidation and complete Smart
comparison behavior remain open. [Native probes][video], [date policy][policy]

## Calendar files and other useful next traces

Apple's Mini 2 manual describes clock setting, alarms and sleep timers, and
calendar documents copied into the `Calendars` folder as `.ics` or `.vcs` files.
This establishes user-visible uses of dates beyond the media database, but not
their binary parsing or timezone rules. [Apple Mini 2 manual, printed pages 35–41][mini-manual]

Both exact OSOS inputs also contain calendar grammar keywords. These are bounded
byte observations and search leads, not proof that every standard feature works:

| ASCII keyword | Mini 2 raw OSOS offset | Video raw OSOS offset |
| --- | --- | --- |
| `vcalendar` | `0x1c94e0` | `0x679153` |
| `dtstart` | `0x1c9548` | `0x67919d` |
| `dtend` | `0x1c9554` | `0x67906f` |
| `vtimezone` | `0x1c96a0` | `0x6790b2` |
| `tzid` | `0x1c96bc` | `0x67906a` |
| `daylight` | `0x1c96c8` | `0x67918d` |

The offset table was read directly from the hashed OSOS files above; Video's
three retained files share these byte spans. Following their parser references
could distinguish UTC-suffixed values, floating wall times, explicit timezone
identifiers, recurring events and alarm scheduling. A `daylight` token in a
calendar grammar does not establish a consumer for `iPod_Control/Device/dst`.
The Classic annual DST-file prefix and city-rule layout must not be assigned to
these models without a qualified file-reader path.

## Questions still open

| Target | Next evidence needed |
| --- | --- |
| Mini 2 / 1.4.1 | Cold boot and invalid-RTC initialization; Host clock import and notification ordering; complete saved-selection/reboot lifecycle; automatic DST and Smart comparison/reevaluation scheduling; 2040 native-word and BCD-century boundaries. |
| Video 5 / 1.3 | The saved source and persistence of the actual timezone/DST metadata; raw RTC initialization and UTC/local convention on each relevant branch; clock-setting notifications; playback/skip and Smart date producers; exact alarm flags and scheduling behavior at DST changes. |
| Video 5.5 / 1.3 | The same shared-code questions, plus whether model/hardware branches select different initialization or notification paths despite identical inspected code. |
| Both families | Calendar-file timezone/recurrence interpretation; any qualified external DST-file reader or writer; date-field-specific evidence for release/purchase, Photo and secondary database records. |

No native word can restore an event's missing historical timezone or distinguish
a repeated wall label by itself. Firmware investigation can establish how a
label was produced and retained; it cannot recreate information the device never
stored. Unchanged native bytes remain authoritative for preservation, while
displayed instants remain best-effort interpretations. [Date policy][policy]

## Validation

The Mini report binds 75 native cases, 38 guarded function bodies and 54 executed
instruction spans. The final Video report binds 87 native cases and 72 hashed
code spans across the three independently loaded inputs. These execute original
ARM against explicit synthetic transport/calendar inputs, not real devices.
[Mini receipt][mini-receipt], [Video receipt][video-receipt]

The application correction passed 650 targeted codec/service tests, including
four Video integration cases for the three updater families and missing release
identity. They verify a nonzero database-offset fallback, successful publication,
and unchanged native dates, database offset and Preferences bytes. Ruff, Mypy
and the changed Markdown checks pass. These application tests use virtual
Storage and authored bytes, not firmware execution or physical acceptance.
[Support audit and test entry points][support]

[mini]: ../../../ipod-firmware-lab/notes/mini2-datetime-2026-11-06.md
[video]: ../../../ipod-firmware-lab/notes/video-datetime-2026-11-06.md
[mini-receipt]: ../../../ipod-firmware-lab/artifacts/mini2-datetime-20261106-v2/receipt.json
[video-receipt]: ../../../ipod-firmware-lab/artifacts/video-datetime-20261106-v1/native-v3.json
[mini-map]: ../../../ipod-firmware-lab/notes/mini2-startup-map.md
[video-inputs]: ../../../ipod-firmware-lab/notes/games/video-family-independent-verification.md
[support]: mini-video-datetime-support-audit-2026-11-06.md
[classic]: classic201-clock-semantics-2026-10-26.md
[eq]: ipod-eq-evolution-and-device-support.md
[preferences]: ../ipod-preferences.md
[policy]: ../adr/0240-treat-calendar-dates-as-best-effort-metadata.md
[mini-manual]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma96_ipod_mini_2nd_gen_userguide.pdf
