# Native Genius similarity framing and Track removal

Issue [#319][issue] reports that an opaque similarity row prevents Track
removal. PR [#321][pr] proposes discarding every surviving opaque similarity
row during pruning. Native firmware and a retained Nano 7 Library establish
two compatible representations that can be pruned without discarding
unrelated relationships.

## Retained Nano 7 Library

The retained `orig_nano7` capture has 722 version-1 `genius_similarities`
rows in its SQLite Genius companion. All have a zero compression selector,
decode with the existing uncompressed layout, and serialize back to their
original bytes. The 20–6,116-byte rows contain 259,146 candidate references
and have no inner tail or outer suffix. The same companion has 722 version-1
metadata rows, each 32 bytes, and one version-2 configuration row of 151,212
bytes. The private Genius database SHA-256 is
`71d845750a7066e298e59a541375ba49bec941b4d89c81d714a13730d9053b33`.

Unmodified iOpenPod reproduced the exact #319 verification error when
preparing Track removal against the capture. Accepting and preserving
similarity version 1 let preparation go from 832 to 831 Tracks and 722 to
721 version-1 similarity rows. The one deleted owner row and 668 incoming
candidate references were removed. Every surviving row, metadata row, and
configuration value matched the independently filtered expectation. An
unchanged Genius document still serialized byte-for-byte. This was a
read-only Host check against a retained copy. The issue reporter's file
and physical firmware playback were outside the experiment.

The same Host check also passed when all source similarity rows were
synthetically re-encoded as version 1 with zlib level zero and selector
2. It pruned the same 668 references, preserved the version and selector
of all 721 surviving rows, and retained the exact original compressed
bytes of the 53 surviving rows whose candidate lists were unaffected.
The retained device capture itself uses uncompressed rows.

## Firmware reader

Both representations begin with two little-endian words:

| Offset | Field | Selector zero | Selector nonzero |
| --- | --- | --- | --- |
| 0 | `u32` selector | Read the payload directly | Inflate the payload |
| 4 | `u32` byte length | Length of the uncompressed payload | Length of the zlib stream |
| 8 | Payload | Candidate count and IDs | One zlib-wrapped stream |

In both cases the uncompressed payload begins with a `u32` count followed
by that many little-endian `u64` Genius IDs in candidate order. The native
reader branches on any nonzero selector and starts the zlib stream at
offset 8. The `1.2.3` string and size `0x38` (56 bytes) are arguments
passed to the firmware's zlib initializer for its own `z_stream` ABI.
Dotm5's [format note][format] describes them as a blob header, which
disagrees with the native call and the byte probe. The initializer selects
a 15-bit window with the zlib wrapper.

| Firmware | Similarity reader | Inflate wrapper | zlib initializer |
| --- | --- | --- | --- |
| Nano 6 1.2 | [`08151750`][n6-reader] | [`08155f4c`][n6-inflate] | [`0815c8e4`][n6-init] |
| Nano 7 1.0.4 | [`08479800`][n7-reader] | [`084e055c`][n7-inflate] | [`084e8c04`][n7-init] |
| Nano 7 refresh 1.1.2 | [`08479800`][n75-reader] | [`084e055c`][n75-inflate] | [`084e8c04`][n75-init] |

The firmware lab's [Nano 6][n6-map], [Nano 7][n7-map] and [Nano 7 refresh][n75-map]
corpus manifests bind these virtual addresses and the `OSOS.main` memory
blocks to these source SHA-256 values:

- Nano 6 1.2: `d529680b7e7662876543d70b6941ddfac123d96c8ed1923432e4909909e896d8`
- Nano 7 1.0.4: `4a55fffbf58cfd04a393e9a40c0c1c42471dfb34d11847b676b85f02a8019999`
- Nano 7 refresh 1.1.2: `ac4cf072d3c3f971b6acc03ed4f2ad1baa57d7bae20f89692bd6fb08d8a749e4`

Native instruction execution on all three images confirmed plaintext
selector zero and compressed selectors `1`, `2`, and `0xffffffff`.
Each case returned the same four ordered Genius IDs, including a
duplicate and the maximum unsigned ID. The probe executed both the
reader and bundled inflater, supplying synthetic data at the SQLite
callback boundary and stubbing allocation, release, byte swapping, and
the final consumer. Each compressed case called the inflater with
`(blob + 8, compressed_length, 3)`. The third argument controls the
initial output allocation. The [local probe][probe] and [receipt][receipt]
are kept in the ignored research workspace. These checks establish format
acceptance in the reader without booting RetailOS or testing physical
Genius playback.

The same three readers accepted iOpenPod's serialized output after
editing parsed version-1 and version-2 rows. The source fixtures used
zlib level zero and a compression selector of 2. The no-op serializer
returned identical source bytes. After the two occurrences of one ID
were removed, the native reader returned the two surviving IDs in
order. Each version was tested with and without synthetic inner,
zlib, and outer suffixes. The codec preserved all three suffixes
through the edit, and the native reader consumed only the candidate
list. This adds 12 codec-to-native cases to the 12 native format cases
in the [receipt][receipt].

## Classic and earlier Nano checks

Static analysis traces the same two-word framing and native inflate
call in every earlier Genius-capable firmware available in the lab.
These are relocated runtime addresses.

| Firmware | Similarity reader | Inflate wrapper |
| --- | --- | --- |
| Classic updater 33, 2.0.1 | `08241aa0` | [`082a2954`][c33-inflate] |
| Classic updater 35, 2.0.4 | `0825dda4` | [`082bfc3c`][c35-inflate] |
| Classic updater 38, 2.0.5 | `0825f608` | [`082c1548`][c38-inflate] |
| Nano 4 updater 31, 1.0.4 | `08220718` | [`08278400`][n4-inflate] |
| Nano 5 updater 34, 1.0.2 | `082b2938` | [`082b8e4c`][n5-inflate] |

The [Classic 2.0.1][c33-parser], [Classic 2.0.4][c35-parser],
[Classic 2.0.5][c38-parser], [Nano 4][n4-parser], and [Nano 5][n5-parser]
reader exports show the selector check followed by inflation at offset 8.
Classic 2.0.5 maps DRAM from raw offset `0xaf98` to `0x08000000`.
The Nano 5 reader uses the same DRAM base from raw offset `0x2e27c`.
The [Classic 2.0.5][c38-map] and [Nano 5][n5-map] records bind those maps.

The [Classic native probe][classic-probe] executes the reader and
inflater in Classic 2.0.1. Flags 0, 1 and 9 all returned the four test
IDs. Raw DEFLATE and gzip did not yield candidates. With bytes after the
declared stream, the firmware still passed only the declared extent to
the inflater. The prepared image SHA-256 was
`220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`.
Its DRAM map begins at `0x08000000` from file offset `0xb65c`.
The Classic reader also returned the three surviving IDs in order
when fed iOpenPod's edited version-1 selector-9 and version-2
selector-1 rows. Both started as level-zero streams and round-tripped
byte-exact before editing. The serializer preserved the selectors and
outer suffix.

The [firmware lab's release and input records][earlier-inputs] identify
the raw images used for static comparison. Classic 2.0.1, 2.0.4,
2.0.5 and Nano 4 1.0.4 query `genius_id,data` from the similarity
table. Nano 5 1.0.2 includes the version column, like the later
Nanos.

## Versions and metadata

The [Nano 6][n6-versions], [Nano 7][n7-versions] and
[Nano 7 refresh][n75-versions] firmware capability getters advertise
versions 1–20 for configuration, metadata, and similarities. This is
a capability range. The capture directly establishes on-disk support for
similarities and metadata version 1 alongside the already studied version
2. The native Classic 2.0.1 probe also executed the capability getter at
`082a2b48` and obtained the same 1–20 range for each table.

The Nano 7 and Nano 7 refresh SQLite similarity callbacks
([1.0.4][n7-sql] and [1.1.2][n75-sql]) copy column index 2
(`data`). They do not select a decoder based on column index 1
(`version`). The [Nano 7 metadata callback][n7-meta-sql] copies the same
column. The [Nano 6][n6-meta] and [Nano 7][n7-meta] metadata consumers
divide the byte length by eight and use that many 64-bit constraint
keys. The version-1 metadata rows in the capture therefore match the
existing four-key layout.

## Codec implications

For validated formats, remove rows belonging to the removed Genius IDs
and remove incoming references from surviving rows. Preserve SQLite row
versions and the nonzero selector value. An unchanged compressed payload
needs its captured stream because recompressing equivalent bytes can
produce a different stream. A changed compressed row can use a new
zlib stream after bounded decompression and framing validation. Treat
similarity and metadata versions other than 1 and 2 as opaque, with
their exact bytes retained. Invalid or truncated framing in either
supported version raises a format error, including an invalid zlib
stream or input or decoded payload beyond the size bound. Track
pruning preserves its existing refusal for unknown extension bytes.

[issue]: https://github.com/TheRealSavi/iOpenPod/issues/319
[pr]: https://github.com/TheRealSavi/iOpenPod/pull/321
[format]: https://github.com/dotm5/Genius-Mix-Research/blob/ebebb902dec559937d4b828ea9d7220eca650a35/docs/FORMAT.md
[c33-parser]: ../../.scratch/issue-319-firmware-crosscheck/classic33-parser/08241aa0.asm.txt
[c33-inflate]: ../../.scratch/issue-319-firmware-crosscheck/classic33-branch/082a2954.asm.txt
[c35-parser]: ../../.scratch/issue-319-firmware-crosscheck/classic35-parser/0825dda4.asm.txt
[c35-inflate]: ../../.scratch/issue-319-firmware-crosscheck/classic35-parser/082bfc3c.asm.txt
[c38-parser]: ../../.scratch/issue-319-firmware-crosscheck/Classic38FW-reader.asm.txt
[c38-inflate]: ../../.scratch/issue-319-firmware-crosscheck/Classic38FW-inflate.asm.txt
[c38-map]: ../../../ipod-firmware-lab/Classic38FW/evidence/runtime-map.json
[n4-parser]: ../../.scratch/issue-319-firmware-crosscheck/nano4-parser/08220718.asm.txt
[n4-inflate]: ../../.scratch/issue-319-firmware-crosscheck/nano4-parser/08278400.asm.txt
[n5-parser]: ../../.scratch/issue-319-firmware-crosscheck/Nano5FW-reader.asm.txt
[n5-inflate]: ../../.scratch/issue-319-firmware-crosscheck/Nano5FW-inflate.asm.txt
[n5-map]: ../../../ipod-firmware-lab/notes/games/nano5-final-device-keys.md
[classic-probe]: ../../.scratch/issue-319-firmware-crosscheck/native_classic_genuis_probe.py
[earlier-inputs]: ../../../ipod-firmware-lab/notes/games/ic-info-final-family-review.md
[n6-reader]: ../../../ipod-firmware-lab/Nano6FW/analysis/osos-corpus/functions/08151750.c
[n6-inflate]: ../../../ipod-firmware-lab/Nano6FW/analysis/osos-corpus/functions/08155f4c.c
[n6-init]: ../../../ipod-firmware-lab/Nano6FW/analysis/osos-corpus/functions/0815c8e4.c
[n6-map]: ../../../ipod-firmware-lab/Nano6FW/analysis/osos-corpus/manifest.json
[n6-meta]: ../../../ipod-firmware-lab/Nano6FW/analysis/osos-corpus/functions/082d431c.c
[n6-versions]: ../../../ipod-firmware-lab/Nano6FW/analysis/osos-corpus/functions/08050860.c
[n7-reader]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/08479800.c
[n7-inflate]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/084e055c.c
[n7-init]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/084e8c04.c
[n7-map]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/manifest.json
[n7-meta]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/08479310.c
[n7-meta-sql]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/081e1a3e.c
[n7-sql]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/081e1a98.c
[n7-versions]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/084e06b6.c
[n75-reader]: ../../../ipod-firmware-lab/Nano75FW/analysis/osos-corpus/functions/08479800.c
[n75-inflate]: ../../../ipod-firmware-lab/Nano75FW/analysis/osos-corpus/functions/084e055c.c
[n75-init]: ../../../ipod-firmware-lab/Nano75FW/analysis/osos-corpus/functions/084e8c04.c
[n75-map]: ../../../ipod-firmware-lab/Nano75FW/analysis/osos-corpus/manifest.json
[n75-sql]: ../../../ipod-firmware-lab/Nano75FW/analysis/osos-corpus/functions/081e1ab0.c
[n75-versions]: ../../../ipod-firmware-lab/Nano75FW/analysis/osos-corpus/functions/084e06b6.c
[probe]: ../../.scratch/issue-319-firmware-crosscheck/probe_nano_genius_similarities.py
[receipt]: ../../.scratch/issue-319-firmware-crosscheck/probe-nano-receipt.txt
