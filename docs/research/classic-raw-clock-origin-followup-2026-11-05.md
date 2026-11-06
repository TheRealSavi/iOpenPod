# Classic raw clock origin and Host calendar import

Research date: **2026-11-05, America/Detroit**. This follow-up verifies the
latest updater-family 24/33/35/38 images against preserved bytes. It adds a
reachable SCSI calendar command, an indirect calendar-setter entry, expanded
provider searches, and a bounded inspection of the preserved 2.0.1 loader.
It does not access a physical iPod or execute firmware. Latest-version identity
is established separately in the [target inventory][targets].

## Result and application boundary

All four images accept the same 12-byte civil-calendar command through SCSI
WRITE BUFFER. Valid input supplies a year, day-of-year, time, effective offset
in signed quarter-hours, and DST byte. The firmware converts the effective
offset to a base offset and changes **software clock correction plus live
metadata**. This route does not initialize the raw running RTC. Consequently,
it closes a Host-input contract gap without establishing whether the underlying
running calendar began in UTC, local time, or another convention.
[Command and setter evidence][receipt], [reproducible vectors][fixtures]

Keep selected city, saved DST, live offset/DST, correction, and historical Track
date words distinct. This evidence does not justify rebasing old dates when
settings change, deriving a historical IANA zone, adding a clock-writing workflow,
or shipping an unused command codec. The current best-effort, non-blocking date
policy remains appropriate. Existing application support is described in the
[Classic 6 report][classic6] and [later Classic report][later].

## Exact evidence

The verifier rejects any unexpected OSOS hash. Every address below is a runtime
address in that image's recorded map; PE addresses later in this report are
module-relative RVAs. Function labels are analyst descriptions.

| Family / latest version | OSOS SHA-256 |
| --- | --- |
| 24 / 1.1.2 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` |
| 33 / 2.0.1 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| 35 / 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` |
| 38 / 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |

Family 33 uses the pinned osos-lab profile; the others use their independently
recovered `Classic*FW/evidence/runtime-map.json` files. The [receipt][receipt]
includes map hashes, all initialized regions, exact span hashes, resolved
branches, and literal values. Analysis discovery annotations come from osos-lab
`d2c8e357d58591bdaa70bb6be9da191f489554a6`; instructions are read from the actual
images, not accepted from annotations alone.

## The command is reachable through SCSI

The dispatcher tests opcode `0x3b` and calls the WRITE BUFFER handler. That
handler extracts the low five mode bits from CDB byte 1 and requires mode 1.
The next check requires CDB byte 2, buffer ID, to be zero and CDB byte 3, the
high offset byte, to be **at least** `0x0c`. It is not an exact `0x0c0000` offset
comparison. The inspected checks do not constrain the remaining offset bytes.
[Dispatcher][dispatch], [mode handler][write-buffer], [CDB checks][write-check]

| Routine | 24 | 33 | 35 | 38 |
| --- | --- | --- | --- | --- |
| SCSI dispatch | `080d33b4` | `080d6cb0` | `080ed978` | `080eda30` |
| WRITE BUFFER | `080d58d4` | `080d91e8` | `080efed0` | `080eff88` |
| Calendar CDB checks | `080d792c` | `080db260` | `080f1fb0` | `080f2068` |
| Receive calendar | `080d56c8` | `080d8fdc` | `080efcc4` | `080efd7c` |
| Decode calendar | `080b0354` | `080b3690` | `080ca460` | `080ca504` |
| Calendar setter | `08044a74` | `08045c74` | `0805c5b4` | `0805c5f0` |
| Day-index conversion | `080b21c4` | `080b5500` | `080cc160` | `080cc204` |
| Adjusted setter | `0804c26c` | `0804d4f0` | `0806390c` | `080639a8` |

The receive routine allocates three words, requests 12 bytes through receiver
virtual slot `+0x0c`, and proceeds only when its returned count equals 12.
It reverses each of three words, decodes the result, calls the calendar setter,
then posts event `0x11`. For family 33 these decisive calls occur at
`0x080d9080`, `0x080d9088`, and `0x080d9090`; the event helper is
`0x08065d48`. A short or otherwise non-12 count skips the setter. The handler
does not inspect a setter result before posting the event.
[Receive ARM][receive], [all-four call guards][receipt]

Independent Host source corroborates the interpretation. The libgpod-derived
[Rockbox time-sync implementation][host-source] builds a packed 12-byte payload
from `localtime`, with big-endian year/day-of-year, `tm_gmtoff / 900`, time
fields, and a Boolean DST byte. It sends WRITE BUFFER mode 1, ID 0, offset
`0x0c0000`. This is an independent Host implementation, not an Apple/iTunes
capture. The pinned source snapshot is retained with its [hash manifest][source-manifest].

## Wire fields, signedness, and malformed input

These offsets describe wire bytes **before** the firmware's three word swaps.

| Wire offset | Width | Verified interpretation |
| --- | --- | --- |
| `0x00` | BE u16 | Calendar year |
| `0x02` | BE u16 | Zero-based day-of-year |
| `0x04` | signed i8 | Effective offset in quarter-hours |
| `0x05` | u8 | Hour |
| `0x06` | u8 | Minute |
| `0x07` | u8 | Second |
| `0x08` | u8 | Raw DST byte; any nonzero value takes the DST branch |
| `0x09..0x0b` | 3 bytes | Ignored by the inspected decoder |

The decoder sets the internal month byte to zero, marking day-index input,
copies the fields, and sets flags to three. `LDRSB` explicitly sign-extends the
offset. When DST is nonzero, it subtracts four quarter-hours and stores the
result with `STRB`; it does not change the civil time fields. Therefore the
stored byte is `(effective_quarters - (4 if dst_raw else 0)) & 0xff`.
It preserves the supplied DST byte rather than normalizing it to one.
[Decoder][decoder]

Examples in the [fixture pack][fixtures] include effective `-16` with DST 1
becoming base `-20`, DST `255` taking the same subtraction, and effective
`-128` with DST becoming stored byte `124` through eight-bit truncation. These
last cases expose machine behavior; they are not recommended Host inputs.

There is no explicit year/hour/minute/second range validation in this decode
chain. The day-index converter subtracts lengths from a twelve-byte month
table. It handles the February leap distinction, but has no explicit
month-index upper bound before the next table read. An excessive ordinal can
read beyond that table; this pass does not invent a safe result for such input.
The following adjusted setter converts fields to BCD and computes correction;
no date-repair fallback was identified in this import route. Provider status
handling is separate from validating incoming civil fields.
[Day-index ARM][ordinal], [adjusted setter][adjusted]

Only valid ordinal cases are reconstructed. Five cases cover leap day, leap
year end, and the non-leap February boundary, and are checked against Python's
Gregorian date arithmetic. Seven byte-decoding cases and eight transport cases
cover signedness, truncation, mode/ID/offset checks, and exact
receive count. These are bounded Host reconstructions, not ARM execution or
physical acceptance tests. [Fixtures][fixtures]

## What synchronization changes

The calendar setter passes selector zero to the adjusted setter. That branch
reads the raw running calendar and computes requested calendar minus raw
calendar into the software day/second correction. It does not call the raw-bank
writer. On successful provider status, the outer setter copies the decoded
offset, DST, and flags into shared live calendar metadata; it then persists live
metadata and reschedules the alarm. The saved bias is a separate Preferences
state with its own restoration path. [Calendar setter][setter],
[adjusted setter][adjusted], [metadata persistence][persist],
[saved-bias restoration][restore-bias]

The direct command chain contains no selected-city or saved-DST Preferences
store. That is a local statement, **not** proof that these settings are unchanged
after all notifications run: event `0x11` has dynamically registered consumers
that this pass does not close. Current city, saved DST, and imported live offset
must not be silently equated. The callback investigation has a separate scope.

The matching READ BUFFER mode-1 route returns the adjusted calendar. Its encoder
adds four quarter-hours to the signed base offset for any nonzero DST byte,
then stores the low byte. It is not a raw RTC readback. Incoming padding is
ignored; the final values of outgoing padding are not established here.
[READ BUFFER][read-buffer], [response][response], [encoder][encoder]

| Routine | 24 | 33 | 35 | 38 |
| --- | --- | --- | --- | --- |
| READ BUFFER | `080d5370` | `080d8c84` | `080ef96c` | `080efa24` |
| Calendar response | `080d6e7c` | `080da7b0` | `080f1500` | `080f15b8` |
| Encode calendar | `080b03ac` | `080b36e8` | `080ca4b8` | `080ca55c` |
| Restore saved bias | `08019fac` | `0801ad54` | `0803175c` | `0803175c` |
| Restore live metadata | `080a62d0` | `080a9644` | `080c040c` | `080c04b0` |

Live-metadata restoration checks retained metadata, copies its offset/DST when
valid, and sets validity bits. Its invalid path initializes the shared record
to year 2000, day-index 3, zero time, and zero offset/DST, then derives month/day.
It does not write that fallback into the raw RTC. A valid metadata signature or
a plausible shared calendar therefore does not prove the RTC's original basis.
[Restoration ARM][restore-live]

## Indirect entry and raw-bank search

An exact vtable pointer reaches a separate compact-calendar setter in each
image. It obtains current fields, replaces year/month/day/hour/minute/second
when that getter succeeds, and calls the field setter with mask `0x7f` while
retaining metadata. The downstream field/adjusted path still changes correction.
This adds real indirect-call evidence beyond the earlier direct-branch search.
Its object owner and originating transport are not resolved; do not label this
entry iAP or USB based only on its neighboring code. [Indirect setter][indirect],
[pointer and field-setter guards][receipt]

| Evidence | 24 | 33 | 35 | 38 |
| --- | --- | --- | --- | --- |
| Indirect setter | `082223d8` | `08234884` | `082507d8` | `0825203c` |
| Exact pointer slot | `088f0b6c` | `0897df20` | `089a7fdc` | `089afee0` |
| Raw writer wrapper | `08295590` | `082be3c8` | `082dad14` | `082dc620` |
| Raw bank writer | `0832762c` | `083532ec` | `083628bc` | `083641c8` |
| Generic PMU writer | `083273cc` | `0835307c` | `0836264c` | `08363f58` |

The new search covers aligned ARM B/BL encodings and aligned exact pointer words
to the function or function-plus-one across **all mapped initialized OSOS
regions** in each image. Each raw wrapper has one direct call, from adjusted
setter `+0x94`; the preceding instruction passes selector one, the alarm bank.
Each bank writer has one direct caller, its wrapper. Neither raw writer has an
aligned exact pointer reference. The indirect calendar setter has no direct
branch hit and exactly the pointer slot shown above. [Search results][receipt]

Each generic PMU writer has 21 direct branch hits, with surrounding instruction
windows retained in the receipt and individual disassemblies. Some register
addresses are computed from arguments. These windows do not close the range of
every computed register or all indirect interface callers. The search also does
not prove absence of arbitrary Thumb calls, computed function addresses,
alternative peripheral access, other modules, or BootROM code. It narrows a
specific search surface; it is not proof that Apple never writes the running RTC.

## Preserved bootloader boundary

The 2.0.1 profile pins the preserved plaintext loader to SHA-256
`8d028296d20d7162eb109d062239ba510fe842510e006178040caacbabead1b8`,
129,024 bytes. Offline `reprise firmware extract-efi` produced 41 modules in a
new artifact directory; the receipt records their sizes and hashes, the exact
command, and the extractor executable hash. No extracted code was executed.
[Loader extraction manifest][modules], [verification receipt][receipt]

The extracted `DxePcf50635` PE is 4,288 bytes, SHA-256
`e461487380c597e15e2dbe49be81dd27f4850e39d16515d0cd71cfce0eb07899`.
Its inspected entry spans, RVAs `0x5de..0x637` and `0x668..0x695`, locate and
install protocol interfaces. Generic register helpers at RVAs `0x220` and
`0x24c` perform transport operations; the latter rejects payload lengths above
eight. This bounded module inspection does not establish an RTC seed date or
timezone convention. Other boot modules and callers of the generic interface
are not fully traced. [Entry disassembly][boot-entry], [entry tail][boot-tail],
[generic write helper][boot-write]

No separately qualified loader inspection was completed for families 24, 35,
or 38. Their OSOS command and provider evidence is independent, but the 33
loader findings must not be generalized to those hardware targets.

## Remaining questions and reproducibility

For **each** of 24/1.1.2, 33/2.0.1, 35/2.0.4, and 38/2.0.5, the original raw
running-calendar basis and first writer remain unidentified. The same applies
to the compact-setter object's originating transport and complete downstream
effects of the imported-calendar event. Family 33 additionally has a bounded
loader inspection; the other three still need independently qualified loader
analysis before boot-path parity can be claimed.

Even a known Host command cannot solve the origin mathematically: adding a
constant to raw time and subtracting it from correction preserves the adjusted
calendar. Three fixture vectors demonstrate that underidentification. No new
claim is made about Apple/iTunes payload captures, power-loss initialization,
RTC persistence on physical hardware, or automatic DST behavior outside the
separate DST investigation. [Ambiguity vectors][fixtures]

Run the [verifier][verifier] from the firmware lab, choosing a **new** output
directory:

```powershell
uv run scripts/check_classic_raw_clock_origin_followup.py --output-dir artifacts/classic-raw-clock-origin-20261105-v3
```

The completed [v2 receipt][receipt] covers 176 recorded OSOS spans: 88 routine
comparisons, four dispatchers, and 84 PMU callsite windows. It checks 144
explicit call/word/pointer/table guards and hashes 41 extracted modules. Two
saved-bias restoration routines have an explicitly checked context-field
displacement change (`+0xce8` to `+0xf00`); it is not hidden by relocation
masking. The fixture pack contains 23 cases. All checks passed. This verification
does not modify application code, preserved inputs, devices, or Ghidra projects.

[targets]: classic-latest-firmware-targets-2026-11-05.md
[classic6]: classic6-latest-calendar-contract-2026-11-05.md
[later]: later-classic-latest-calendar-contracts-2026-11-05.md
[verifier]: ../../../ipod-firmware-lab/scripts/check_classic_raw_clock_origin_followup.py
[receipt]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/receipt.json
[fixtures]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/fixtures.json
[dispatch]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-scsi_dispatch.asm
[write-buffer]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-write_buffer.asm
[write-check]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-write_check.asm
[receive]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-receive_calendar.asm
[decoder]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-decode_calendar.asm
[ordinal]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-ordinal_to_month_day.asm
[adjusted]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-adjusted_set.asm
[setter]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-calendar_set.asm
[persist]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-persist_metadata.asm
[restore-bias]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-restore_saved_bias.asm
[restore-live]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-restore_live_metadata.asm
[read-buffer]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-read_buffer.asm
[response]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-send_calendar.asm
[encoder]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-encode_calendar.asm
[indirect]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-indirect_calendar_set.asm
[modules]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-bootloader-20261105-v1/modules.json
[boot-entry]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-loader-pmu-entry_first.asm
[boot-tail]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-loader-pmu-entry_tail.asm
[boot-write]: ../../../ipod-firmware-lab/artifacts/classic-raw-clock-origin-20261105-v2/33-loader-pmu-register_write.asm
[host-source]: https://github.com/Rockbox/rockbox/blob/2476968a206e5cdf80fde7887c48cd41512c3276/utils/time-sync/ipod-scsi.c
[source-manifest]: ../../../ipod-firmware-lab/artifacts/classic-time-host-source-20261105-v1/manifest.json
