# Firmware DST data and city identity

Research date: 2026-11-06. This continues the
[non-blocking date investigation](nonblocking-ipod-dates-2026-11-05.md).
Calendar uncertainty must not prevent loading or changing a Library. The useful
new result is that Apple changed both the custom DST file framing and its week
selectors between the inspected Classic 2.0.1 and 2.0.4/2.0.5 images. A parser
must select an explicit firmware profile; equal row counts cannot identify one.

## Evidence and reproduction

The evidence below is direct static inspection of preserved Apple firmware bytes,
checked against exact SHA-256 identities and startup-derived runtime maps. ARM
addresses are runtime addresses, not offsets into the source file. Capstone output
is an instruction decoder, not Apple source or evidence of execution. No physical
iPod was accessed, no firmware ran, and no device file was changed for this pass.

The new [verification script][script] checks seven images, both DST table hashes,
205 ordered rows, all 32 offset-code pairs, applicable city records, explicit
instruction words and bounded arithmetic consequences. It emits 20 disassembly
listings and a [machine-readable receipt][receipt]. The receipt also contains
source/map/script hashes, tool versions, table rows and differences. The retained
receipt was produced with Python 3.12 and Capstone 5.0.6. Reproduce from the lab
into a new directory; the script refuses to replace existing evidence:

```powershell
uv run scripts/check_dst_family_formats.py --output-dir artifacts/dst-family-formats-20261106-v5
```

| Image inspected | Bytes | SHA-256 |
| --- | ---: | --- |
| Classic 24 logical OSOS | 9,924,476 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` |
| Classic 33, 2.0.1 normalized OSOS | 10,513,984 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| Classic 35, 2.0.4 logical OSOS | 10,597,864 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` |
| Classic 38, 2.0.5 logical OSOS | 10,632,448 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |
| Nano 3 logical OSOS | 10,790,256 | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` |
| Nano 4 logical OSOS | 5,763,080 | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` |
| Nano 5 logical OSOS | 7,284,288 | `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49` |

The [Classic 35][package35] and [Classic 38][package38] extraction receipts identify
IPSW members `Firmware-35.9.0.4` and `Firmware-38.9.0.5`. Reading the original
IPSW `manifest.plist` files again confirmed `FamilyID=11`, updater IDs 35 and 38,
and visible builds `0x02048000` and `0x02058000` respectively. The manifests contain
no capacity, product SKU or board identity. Existing research identifies them as
the later Classic families; automatic qualification by a registry's Classic 7th
generation identity plus exact RetailOS release remains application policy, not
a hardware mapping proved by these manifests. Transport revision must not be
substituted for RetailOS release.

## Custom DST file framing differs

All four newly located loaders name `iPod_Control\Device\dst`. The earlier
Classic 2.0.1 loader was also rechecked against the normalized image.

| Consumer | Loader | Row data begins | Requested row bytes | Week selectors |
| --- | --- | ---: | ---: | --- |
| Classic 33 / 2.0.1 | `080dd958` | 0 | 3,280 | 1, 2, 3, last=4 |
| Classic 35 / 2.0.4 | `080f4a38` | 2 | 3,280 | 1, 2, 3, 4, last=5 |
| Classic 38 / 2.0.5 | `080f4af0` | 2 | 3,280 | 1, 2, 3, 4, last=5 |
| Nano 4, inspected image | `080ea6fc` Thumb | Separate two-byte read observed | 3,280 | Not qualified in this pass |
| Nano 5, inspected image | `080b2644` Thumb | Separate two-byte read observed | 3,280 | Not qualified in this pass |

The Classic 2.0.1 loader requests exactly `0xcd0` bytes into a replacement buffer,
then selects it when the read status is zero. Missing files or read failure use
the compiled table. It does not check the returned byte count or require end of
file. There is no header read, row-count field or sentinel check in that loader.
[Classic 33 loader][loader33], [earlier read-path investigation][baseline-dst].

The later Classic loaders first request two bytes into a separate global, then
seek to absolute file position two and request `0xcd0` row bytes. Their seek
helpers accept the offset in `r2:r3` and the origin on the stack; here those are
2:0 and origin zero. The helpers store the resulting file position at file-object
`+0x34`. The separate prefix is **opaque**: the loaders do not validate its value,
and this investigation does not establish its purpose. Calling it a version,
year, city count or timezone would overstate the evidence.
[Classic 35 loader][loader35], [seek][seek35],
[Classic 38 loader][loader38], [seek][seek38].

Only the final row-read status chooses the later custom table. The initial
two-byte read and seek statuses are ignored, as is the final returned byte count.
Both complete read wrappers reduce an oversized request to the positive number
of bytes remaining and can return success after that shorter read. Thus a short
file may leave part of the selected replacement buffer dependent on prior memory
state. Neither zero filling nor merging the remainder with compiled rules is
established behavior. A Host must retain the short file and diagnose incomplete
evidence, without blocking a Library workflow or claiming a complete firmware
table. Trailing bytes are not consumed by the row request but remain part of the
original file and must be preserved. [Read wrapper 35][read35],
[read wrapper 38][read38], [earlier 2.0.1 analysis][baseline-dst].

## Row structure, order and units

Each observed table contains 205 slots of 16 bytes. The compiled rows have city
IDs 1 through 205 in increasing order. Custom rows are searched in slot order;
the loader does not validate that IDs are unique, ordered or restricted to that
range. All multibyte row fields are little-endian unsigned halfwords.
[Receipt][receipt], [Classic 33 predicates][enabled33], [active predicate][active33],
[Classic 35 builder][builder35], [Classic 38 builder][builder38].

| Row offset | Type | Observed use |
| --- | --- | --- |
| `+0` | u16 | Numeric city ID used for equality comparisons |
| `+2` | u8 | Enabled; zero is false, every nonzero value is true |
| `+3` | u8 | Start weekday, Sunday=0 in the inspected calendar model |
| `+4` | u8 | End weekday |
| `+5` | u8 | Unused by the inspected consumers; preserve |
| `+6` | u16 | Unused by the inspected consumers; preserve |
| `+8` | u16 | Start month |
| `+10` | u16 | Start week selector, interpreted by firmware profile |
| `+12` | u16 | End month |
| `+14` | u16 | End week selector, interpreted by firmware profile |

These are annual calendar rules. The record contains no year range, UTC offset,
IANA name, transition-hour field or variable DST magnitude. The inspected Classic
builders supply 02:00 and their active predicates apply 3,600 seconds. The table
cannot describe historical jurisdiction changes, transitions at arbitrary hours,
or half-hour DST. No evidence here supports using it as a historical timezone
database for Track timestamps. [Builders][builder35], [Classic 38 builder][builder38],
[Classic 35 predicate][active35], [Classic 38 predicate][active38].

Ordered duplicates matter. The enabled helper returns the enabled byte from the
first matching city slot. The active predicate returns false on a matching
disabled row or a current value before that row's lower bound, and true inside
the inclusive lower/upper interval. After a value beyond the upper bound it
continues scanning later slots, potentially finding another row for the same
city. Therefore a dictionary, deduplication or a universal first-match-only
interpretation loses behavior. City ID zero is not a DST-row terminator; the
205-slot loops compare it as an ordinary unsigned halfword if supplied.
[Classic 33 enabled][enabled33], [active][active33],
[Classic 35 enabled][enabled35], [active][active35],
[Classic 38 enabled][enabled38], [active][active38].

## Later firmware changed calendar arithmetic

Classic 2.0.1 selectors 1, 2 and 3 start from days 7, 14 and 21; selector 4 starts
from the final-day seed. Unsupported selectors leave a zero seed. In both later
Classic builders selector 4 starts from day 28 and selector 5 uses the month-end
seed. The dispatches and both start/end branches were inspected independently:
Classic 35 `080f4634..080f4744`, Classic 38 `080f46ec..080f47fc`.
[Earlier reconstruction][baseline-dst], [builder 35][builder35],
[builder 38][builder38].

Two additional defects of the inspected 2.0.1 reconstruction are corrected in
these later builders. For a weekday earlier than the requested weekday they
subtract `7 - (target - current)` instead of the earlier fixed six. For a
February month-end seed they subtract one from 29 only when the leap helper
returns zero, giving 28 for a non-leap year and 29 for a leap year. The later
helpers implement the usual divisible-by-four, century and 400-year checks;
the month-seed bytes are independently checked by the script.
[Builder 35][builder35], [leap helper 35][leap35],
[builder 38][builder38], [leap helper 38][leap38].

A bounded arithmetic example in the receipt starts at day 31 on Sunday and asks
for Saturday: the earlier fixed-six path produces day 25, while the later path
produces day 30. This is a consequence of the inspected instruction sequences,
not a physical-device test. It supports keeping firmware models versioned and
avoiding a blanket statement that every iPod shares the same date defects.
[Verification script][script], [receipt][receipt].

## Compiled tables across available images

| Image | DST table file offset | Enabled rows | Table SHA-256 |
| --- | --- | ---: | --- |
| Classic 33 normalized | `0x9ac3f0` | 108 | `4d4bf7f9d0db2674e2905bcc53e0e9faefaba93b0024e6719fe01a611a05809e` |
| Classic 35 | `0x9d6330` | 106 | `e6612cee6c77079bfca273e9737f11d5a63fd3c5acfcc230f24e6f3b31c29a28` |
| Classic 38 | `0x9dea48` | 106 | Same as Classic 35 |
| Nano 4 | `0x464e54` | 106 | Same as Classic 35 |
| Nano 5 | `0x580bfc` | 106 | Same as Classic 35 |

The later four tables are byte-for-byte identical. Against Classic 33, 65 rows
differ: 61 end-week fields, 56 start-week fields, six end-month fields, four
enabled fields, three start-weekday fields, two end-weekday fields and one
start-month field. The enabled changes are city `0x3b` offâ†’on and `0x68`, `0x95`,
`0x96` onâ†’off. Numerous last-week selectors change from 4 to 5, consistent with
the two independently inspected later Classic builders. No unused row bytes
change. The receipt retains every difference by numeric ID; geographic labels
are not required to establish this result. [Receipt][receipt].

Neither full-table signature nor the exact DST path string was found in the
Classic 24 or Nano 3 image. This is a negative signature search only: it does not
prove those devices lack DST, custom files, another representation or equivalent
code. Similarly, Nano 4/5 table equality and loader resemblance do not establish
their complete selector, clock, Preferences or historical-conversion contracts.
They remain research candidates, not automatically qualified profiles.
[Script and search assertions][script], [receipt][receipt].

## City IDs, resource IDs and fixed offsets are different concepts

The 32-row offset-code table is byte-identical in Classic 33/35/38 and Nano 3/4/5.
Each row is a signed minute halfword followed by an unsigned code halfword. Code
26 maps to -300 minutes, code 25 to -270, and code 115 to +390. These values prove
that codes are neither ordinal hours nor signed quarter-hour units. The fixed
offset table does not itself establish the historical standard offset of a place.
[Receipt][receipt], [Classic 35 lookup `080f4c54`][city35],
[earlier Classic 33 lookup analysis][baseline-city].

For Classic 33/35/38 and Nano 3, the following 205 records validate the existing
20-byte city layout: two 32-bit resource IDs; selection group at `+8`; numeric
city ID at `+10`; two retained halfwords at `+12/+14`; offset code at `+16`; and
a retained halfword at `+18`. All 205 records' fields after the resource IDs are
identical across those four images, in the same slot order. Resource IDs change
between builds, and thus are not interchangeable with numeric city IDs. The
adjacent-table assumption does not validate this layout in Nano 4/5; no city
identity inference is made for those images. [Script][script], [receipt][receipt],
[resource and numeric lookup consumers][city35].

City `0x26` is a useful unresolved case. Across all four verified city tables it
has group 6, retained halfwords 94 and 97, and offset code 26 (-300 minutes).
The independent [libgpod mapping][libgpod] calls that city Manchester and maps it
to `Europe/London`. Firmware evidence contradicts that offset mapping but does
not establish which geographic Manchester Apple intended. Localized resource
strings have not been traced for these particular records. Preserve the numeric
identity and profile-qualified offset evidence; do not invent an IANA identity
from the name or offset. The conflict is not unique to Classic 2.0.1.
[Receipt][receipt], [libgpod source][libgpod].

This supports three separate application concepts: a firmware-qualified numeric
city identity, a firmware fixed offset, and a Host geographical timezone policy.
Current DST metadata is a fourth observation; it cannot supply historical DST
for every Track date. No new IANA correction is justified by this pass alone.

## Safe application model opportunities

1. Use separate explicit Classic 2.0.1, 2.0.4 and 2.0.5 DST document profiles.
   Unknown profiles preserve opaque bytes. The two later profiles share the
   observed framing and selector meanings; that does not merge their entire
   Preferences or clock models.
2. Retain the full source bytes, optional opaque prefix, ordered rows, every
   unused field, incomplete suffix and trailing data. Completeness is 3,280 row
   bytes for 2.0.1 and a two-byte prefix plus 3,280 row bytes for later Classics.
   Parsing available complete rows for inspection must not imply a fully known
   device table.
3. Report malformed calendar fields, duplicates and unsupported selectors as
   diagnostics. Never throw a workflow-blocking error for uncertain dates or
   DST metadata; preserve the raw values and use the application's deterministic
   approximation where a date is needed.
4. Keep optional DST capture read-only and tied to explicit device/release
   qualification. Firmware uncertainty, unsupported families, missing files and
   unreadable files must leave Library operations available.
5. Keep annual device rules out of historical UTC conversion. Do not write a
   synthesized DST file, silently repair Apple tables, claim synchronization
   transport behavior or infer an IANA zone from a fixed offset.

These are application recommendations from the observed contracts. They are not
claims that malformed custom files behave safely in Apple firmware. Physical
validation, prefix meaning, Nano consumers, localized city resources and exact
SKU-to-updater mapping remain open research boundaries.

[script]: ../../../ipod-firmware-lab/scripts/check_dst_family_formats.py
[receipt]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/report.json
[package35]: ../../../ipod-firmware-lab/Classic35FW/evidence/extraction.json
[package38]: ../../../ipod-firmware-lab/Classic38FW/evidence/extraction.json
[baseline-dst]: ../../../ipod-firmware-lab/notes/itunesdb/dst-transition-rules.md
[baseline-city]: ../../../ipod-firmware-lab/notes/itunesdb/timezone-and-dst-settings.md
[loader33]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic33-080dd958-loader.asm.txt
[enabled33]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic33-080dd91c-enabled.asm.txt
[active33]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic33-080ddebc-active.asm.txt
[loader35]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic35-080f4a38-loader.asm.txt
[seek35]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic35-0826d8e0-seek.asm.txt
[read35]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic35-0826d5e0-read.asm.txt
[builder35]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic35-080f460c-builder.asm.txt
[enabled35]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic35-080f49fc-enabled.asm.txt
[active35]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic35-080f4fc8-active.asm.txt
[city35]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic35-080f4b28-city_and_offset_span.asm.txt
[leap35]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic35-0809fcd4-leap.asm.txt
[loader38]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic38-080f4af0-loader.asm.txt
[seek38]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic38-0826f1b0-seek.asm.txt
[read38]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic38-0826eeb0-read.asm.txt
[builder38]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic38-080f46c4-builder.asm.txt
[enabled38]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic38-080f4ab4-enabled.asm.txt
[active38]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic38-080f5080-active.asm.txt
[leap38]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic38-0809fd80-leap.asm.txt
[libgpod]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_tzinfo_data.h
