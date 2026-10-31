# ArtworkDB MHFD +0x10: values 2 and 6

Research date: 2026-10-31. Question: does MHFD `+0x10` represent a version,
bitmask, or another property, and does changing 2 to 6 alter firmware behavior?

## Conclusion and naming

**Its precise meaning remains unresolved.** The strongest firmware-backed
statement is that it is an opaque, byte-swapped 32-bit header scalar whose low
16 bits can be returned alongside the low 16 bits of MHFD `+0x0c`. The inspected
native Video writer emits the pair `(0, 2)`. A format-revision or major/minor pair
is a plausible interpretation, but neither that interpretation nor a bitmask
interpretation is established by a consumer that distinguishes 2 from 6.

Keep iOpenPod's existing offset-based identity (`unk_mhfd_0x10`) and document its
observed values. If a descriptive placeholder is needed, `header_word_10` is
accurate. Do not rename it to `flags`, `minor_version`, `artwork_enabled` or
another asserted semantic name on this evidence alone. Historical labels and
variable names in research code are not recovered Apple symbols.

For the traced ArtworkDB import paths, **2 and 6 have the same observed behavior**.
The importers neither compare them nor retain them in their image-library objects,
and every discovered caller discards the optional outputs. This is narrower than
claiming that every Apple tool or every unexamined firmware ignores the field.

## Exact firmware and function identities

| Image | SHA-256 | Root importer | Artwork loader | Other image-library loader |
| --- | --- | --- | --- | --- |
| Classic updater 35, RetailOS 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | `08058fc4` | `0804d358` | `0804d81c` |
| Classic updater 38, RetailOS 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | `08059000` | `0804d384` | `0804d848` |
| Classic updater 33, RetailOS 2.0.1, normalized input | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` | `080427e4` | `08036518` | `080369d4` |
| Video updater 20, RetailOS 1.3 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` | `000afd5c` | `000a1ff0` | `000a2458` |

Classic runtime addresses use DRAM at `08000000` and the preserved per-image
startup maps; Video code uses logical base zero and its native startup mapping.
The prior [Classic 7G investigation](classic7-artwork-firmware-178.md#exact-inputs-and-reproducibility)
records byte verification of all initialized Classic 35/38 Ghidra regions.
The new Video export independently compares its entire code image with the
hash-verified source before exporting the importer, writer and callers.
[Video export receipt](../../../ipod-firmware-lab/artifacts/mhfd-0x10/video20-verified/receipt.json).

## Import data flow and downstream callers

In both latest Classic builds, the root reader loads a 132-byte MHFD prefix.
Its optional output arguments are a pair: argument 5 receives the low halfword
of `+0x0c`, and argument 6 receives the low halfword of `+0x10`. The earlier
Video function has the same pair as arguments 4 and 5. These are two separately
serialized 32-bit words, not two halfwords sharing one word.
[35 importer ARM](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/08058fc4.asm),
[38 importer ARM](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/08059000.asm),
[Video importer](../../../ipod-firmware-lab/artifacts/mhfd-0x10/video20-verified/000afd5c.c).

The byte-swapping routines (`080b3a08` / `080b3aac`) swap all four bytes at
`+0x10`, just as they do the full word at `+0x0c`. This establishes scalar byte
order, not a semantic version name. After swapping, the root checks the whole
`+0x0c` word equals zero; it does not test `+0x10`. No bit of `+0x10` controls
image parsing, filename interpretation, pixel geometry, or lookup in these traced
routines.
[35 swapper and other loader](../../../ipod-firmware-lab/artifacts/mhfd-0x10/35-first.c),
[38 swapper and other loader](../../../ipod-firmware-lab/artifacts/mhfd-0x10/38-first.c).

Ghidra finds two direct root-import calls in each inspected image. The dedicated
Artwork loader and the other image-library loader both pass null for both optional
outputs. The same holds in Classic 2.0.1 and Video 1.3. Thus the optional pair has
no discovered downstream consumer on these paths, and the imported image-library
object does not retain it for later artwork drawing. The query is bounded by the
analyzed code and references; it is not proof against an unknown indirect caller.
[35 call references](../../../ipod-firmware-lab/artifacts/issue178-classic7/35.c),
[38 call references](../../../ipod-firmware-lab/artifacts/issue178-classic7/38.c),
[Classic 33 root references](../../../ipod-firmware-lab/artifacts/mhfd-0x10/33-root.c),
[Classic 33 callers](../../../ipod-firmware-lab/artifacts/mhfd-0x10/33-callers.c),
[Video references](../../../ipod-firmware-lab/artifacts/mhfd-0x10/video20-marker.c),
[Video callers](../../../ipod-firmware-lab/artifacts/mhfd-0x10/video20-callers.c).

A literal survey found one `mhfd`/`dfhm` pair in each latest Classic raw image,
at its root importer. Video has an additional `mhfd` literal, which led to the
native writer below. Literal absence is not proof of no other constructed marker
or consumer; the survey was a route to primary code, not a universal exclusion.

## Native root scalar tests

The probe executes the unmodified Classic 35 and 38 root functions, including
native MHFD and MHSD byte swappers. Its minimal database contains a valid MHFD
and one empty type-3 MHSD. File services and bookkeeping are adapted. Both optional
output pointers are non-null so their actual values can be observed.

For each firmware, in both byte orders, these `+0x10` values all pass:

```text
0, 1, 2, 3, 4, 6, 7, 0xffff, 0x10002, 0x12345678, 0x80000006, 0xffffffff
```

The output is always the value's low 16 bits. In particular, `0x10002` returns 2,
`0x12345678` returns `0x5678`, and `0x80000006` returns 6. Negative controls with
`+0x0c=1` or `+0x0c=0x10000` return `-208`, even though the latter's optional
halfword output is zero. That confirms the acceptance gate uses the complete
`+0x0c` word rather than its returned halfword.

**56 cases passed: 48 accepted scalar values and 8 negative controls.** These
are root parsing and optional-output tests, not complete image/album import or
physical-device display tests. They establish no accepted-value restriction for
the tested `+0x10` values; they cannot assign meanings to individual values.
[Probe source](../../../ipod-firmware-lab/artifacts/mhfd-0x10/native_scalar_pair.py),
[complete results](../../../ipod-firmware-lab/artifacts/mhfd-0x10/native-scalar-pair.json).

## Native Video writer

Video 1.3 function `000bc368` constructs an MHFD and unconditionally writes
`+0x0c=0`, `+0x10=2`. Its caller `000bc114` stages an image database through
`Image DB Temp` before replacement. This is native image-database serialization
code, not an inferred behavior of a third-party writer.
[Writer ARM](../../../ipod-firmware-lab/artifacts/mhfd-0x10/video20-verified/000bc368.asm),
[staging wrapper](../../../ipod-firmware-lab/artifacts/mhfd-0x10/video20-verified/000bc114.c).

The serializer's separate option argument uses bit 0 for output byte order and
bit 1 for a reader/writer-state selector. Neither changes the MHFD scalar from 2.
A bounded native execution with option values `0,1,2,3,4,6,7` captured the initial
and final MHFD headers: all seven cases emitted the pair `(0,2)`, with the expected
normal or swapped marker and byte order. Native zeroing and byte swapping execute;
dataset writers and file output are adapters. This does not test a complete
published database.
[Writer probe](../../../ipod-firmware-lab/artifacts/mhfd-0x10/video_native_writer.py),
[seven writer cases](../../../ipod-firmware-lab/artifacts/mhfd-0x10/video-native-writer.json).

The native constant 2 supports the hypothesis that the field identifies a writer's
format revision or compatibility level. It supplies no evidence that 6 is a
bitwise combination, and no native branch here defines what distinguishes 6.

## Independent producer context and remaining gap

Pinned libgpod calls the word `unknown2`. Its historical comment associates value
1 with older iTunes, 2 with iTunes 4.9 onward, and reports that iTunes 7 removes
value-1 databases. Its artwork writer emits 2 for photo and music image databases.
These are useful producer observations, not a recovered semantic definition.
[libgpod header](https://github.com/fadingred/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-itunes-parser.h),
[libgpod writer](https://github.com/fadingred/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-artwork-writer.c).

The independently maintained foo_dop reader retains `unk2`, while its writer also
emits 2. It offers no stronger field name or explanation of value 6.
[foo_dop reader/writer](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp).

The missing evidence is a consumer or producer that distinguishes 2 from 6:
for example, controlled desktop-iTunes import/rewrite comparisons, or a traced
Apple writer that chooses the value based on an identified condition. Until then,
preserve retained values and keep any fresh-file value an explicit producer
policy. Do not describe changing 2 to 6 as a firmware-backed artwork repair.

## Reproduction

From the iOpenPod repository:

```text
uv run ../ipod-firmware-lab/artifacts/mhfd-0x10/native_scalar_pair.py
uv run ../ipod-firmware-lab/artifacts/mhfd-0x10/video_native_writer.py
```

Both probes pin Unicorn 2.1.4, verify their source-image identities and use only
Host memory. No physical device, firmware image or saved Ghidra project was
modified. New exports and receipts remain separate from the earlier artwork work.
