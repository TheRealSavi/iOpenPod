# Classic 2.0.1 clock evidence and product corrections

Research date: **2026-10-26**. This report distinguishes instruction evidence,
Host policy and open questions behind
[ADR-0196](../adr/0196-adopt-firmware-clock-and-date-evidence.md).

## Evidence identity

| Item | Identity |
| --- | --- |
| Device/firmware | Classic 120GB, RetailOS 2.0.1, updater family 33 |
| Normalized OSOS | 10,513,984 bytes |
| OSOS SHA-256 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| osos-lab baseline | `d2c8e357d58591bdaa70bb6be9da191f489554a6` |
| iOpenPod base | `f93446cd01c5b4bafef66108a0d3be89a68df599`, plus preceding documented field corrections in the working tree |

The latest seven local research batches verify 186 functions and 66,712 unique
instruction bytes against the original image. Eight analyst names and six reviewed
signatures were saved, including one recovered callback. All initialized firmware
regions remain unchanged. These are analyst names, not original Apple symbols;
static analysis and bounded Host models do not execute the firmware.

Detailed wiki reports cover [hardware provenance][hardware],
[callback propagation][callbacks], [timestamp discontinuities][discontinuities],
[timezone settings][settings] and [Smart time rules][smart]. Their earlier Host
reproduction is a source-bound snapshot. The changes below supersede its
description of newest-date binary reconciliation.

## Hardware clock versus adjusted calendar

`0x083531f0` reads seven packed bytes from PMU register `0x59` for bank zero and
`0x60` for bank one. Pinned Rockbox definitions, a related NXP manual and RetailOS's
own scheduler corroborate running-clock and alarm-bank roles. The shared register
map does not uniquely identify the exact silicon variant.

`0x08042ad4` normally adds a software day/seconds bias to the raw calendar; a short
post-set cache can supply the requested calendar instead. Bank-zero setter
`0x0804d4f0` stores requested-minus-raw as bias on its ordinary path. Bank-one
programming subtracts that bias from an adjusted alarm target. Manual clock
corrections can enter the same bias, so it is not just the selected zone offset.

Changing raw origin from `R` to `R+K` and bias from `B` to `B-K` preserves adjusted
calendar `R+B` and relative alarm delay. These upper paths cannot establish raw
UTC/local provenance. Rockbox's direct raw reads and QEMU's configured provider
do not establish Apple's policy either.

The ordinary successful zone/DST setter `0x080ba8a0` has the relationship:

```text
new_calendar = old_calendar
             + 60 * (new_zone_minutes + new_dst_minutes
                     - old_zone_minutes - old_dst_minutes)
```

The calendar word is 32-bit. Valid inputs and successful lower operations are
assumed; intermediate notifications and ignored failure statuses prevent an
atomic-success claim. Play/skip writers `0x082485f0`/`0x0824866c` call
`0x08089380` with current-zone subtraction disabled, then store calendar-shaped
1904-epoch words. A one-hour setback can make the next event's date 3,600 seconds
smaller while counters increase. Saved DST/bias must not be added again.

Callbacks force clock-model sampling and mark deferred collection work. Their
observer/member virtual calls are incompletely resolved. No direct Track date
rebase loop appeared in the enumerated bodies; this is not a whole-program proof
that existing dates never change.

## Binary playback dates follow the supplied event state

Writer `0x0809d024` copies retained event words into Play Counts. Reader
`0x080931a8` stores row `+0x04` into native Track `+0x98` (last played) and row
`+0x18` into native Track `+0xa8` (last skipped), without a newest-date comparison
or new timezone conversion. These are runtime offsets; disk MHIT dates are at
`+0x58` and `+0xa0` respectively.

iOpenPod now replaces present binary dates after Device Time Context conversion,
including older values and zero. It still adds counter deltas and retains the
exact Finder missing-date exception from ADR-0150. A short row lacking the complete
skipped-date word preserves it: `PlaybackEntry.last_skipped=None` means absent,
while zero is an explicit missing-date word. Stats/plist keep their former policy.

Strict conversion still rejects a fold, gap or unresolved zone for the complete
playback input. Valid preceding rows cannot leak partial counts. Two semantic-zero
collisions also block consumption: a nonzero incoming word representing Unix zero,
and an explicit zero clear over a nonzero retained date already projected as
unavailable. The semantic-only writer cannot encode those intentions faithfully;
the sidecar stays pending instead of silently losing or retaining the wrong date.

Raw dates carry no timezone ID, fold bit or travel history. IANA rules for the
currently selected city cannot recover an event's old city or correct a wrongly
set device clock. Successful reconciliation archives the original sidecar verbatim.

## Smart date endpoints and Host policy

Firmware wrappers `0x080342ac` and `0x08034294` select lower and upper operand
triples; `0x080432c8` computes each endpoint. Sentinel-based ranges can have an
upper displacement as well as a lower one. The Host duration model represents a
lower lookback without that second displacement. Dropping it could replace saved
membership during automatic refresh.

Such rules now remain unsupported and read-only. A zero upper displacement remains
representable regardless of its inactive unit word. Existing Host matching remains
a rolling duration policy; the inspected firmware instead uses inclusive day-based
bounds. A context's captured day and a newly initialized context are distinct, and
unresolved callbacks do not prove immediate recomputation of all Smart contexts.

## Qualified Classic Preferences

The payload begins four bytes after the native Preferences context base:

| Payload offset | Context offset | Interpretation |
| --- | --- | --- |
| `0x0000` | `+0x0004` | Observed format version `0x3d` |
| `0x0b6c` | `+0x0b70` | Raw saved DST state byte |
| `0x0b70` | `+0x0b74` | Full u32 city ID |
| `0x0b78` | `+0x0b7c` | Software clock-bias day word |
| `0x0b7c` | `+0x0b80` | Software clock-bias seconds word |

`0x0803336c`/`0x08046308` access the whole city word; lookup compares the full
argument with its table key. `0x00010029` must not resolve as city `0x29` by dropping
the high half. The dedicated profile fixes this without changing unqualified
city-layout files' inherited two-byte interpretation.

Saved DST has callers using 0/1 and 0/60. It is not the nano 3 field at `0x6bc`
or a complete transition rule. The bias is an observation, not a second database
timezone adjustment. The new profile reads city/clock fields without allowing
edits, permits language changes, and requires 2,956 bytes with version `0x3d`.
Automatic use also requires the exact Classic 6.5th Gen 120GB Device Profile and
unconflicted RetailOS 2.0.1 evidence. Other releases are not inferred from file size.

## Validation and limits

Authored fixtures cover replacement, zero/absence, Finder sentinels, multi-row
failure, Smart endpoint preservation and qualified Preferences. Virtual Storage
tests check native date words, publication, verbatim archives and reselect
idempotence. Binary date policy generalization is explicit; flat Preferences
qualification is narrower because other versions' layout/lifecycle is unverified.

Unchanged documents and unrelated Unknown Data remain byte-exact. This adds no
firmware binary, runtime research dependency, physical clock synchronization or
historical migration to the application.

[hardware]: https://ipod-firmware-reference.lightrhea20.chatgpt.site/#/reports/hardware-clock-provenance
[callbacks]: https://ipod-firmware-reference.lightrhea20.chatgpt.site/#/reports/timezone-change-propagation
[discontinuities]: https://ipod-firmware-reference.lightrhea20.chatgpt.site/#/reports/timestamp-discontinuities
[settings]: https://ipod-firmware-reference.lightrhea20.chatgpt.site/#/reports/timezone-and-dst-settings
[smart]: https://ipod-firmware-reference.lightrhea20.chatgpt.site/#/reports/smart-time-rules
