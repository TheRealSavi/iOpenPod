# Classic 2.0.1 artwork evidence adopted by iOpenPod

Research date: 2026-10-28. Firmware: Classic 120GB RetailOS 2.0.1, normalized OSOS
SHA-256 `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`.
Evidence is byte-checked static ARM analysis plus explicitly bounded Host models.
It is not a device playback experiment. Function names are analyst proposals.

## Identity and capability evidence

`0802ecf0` selects numeric image-ID lookup through `0802ebbc` whenever MHIT
`+0x160` is nonzero. Reverse lookup through `080b5074` is the zero-reference route;
failure of a nonzero lookup does not select that fallback. This differs from the
former Host display recovery rule. Valid image IDs may be shared by multiple
Tracks; callback `08213658` also compares resolved image identity across Tracks.

`080e3a40` maps internal selector 15 to F1055 and selector 16 to F1029.
`081fae18` registers both representations as dense slots 0 and 1. The descriptors
are 128 by 128 with 256-byte rows and 200 by 200 with 400-byte rows. This supports
the existing Classic chapter format set independently of third-party producers.
See [format selectors](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/artwork-format-selectors).

## Chapter flags and named index

`080a42c0` loads flags from the first `hedr` atom's second payload word, serialized
at `hedr +0x18`. `08023050` gates named-Chapter queries on mask 1.
`08074980` uses mask 2 to set native Track artwork masks `0x840`.
`08157bac` requires a named-Chapter count and the native chapter-artwork flag for
the chapter provider. These conditions explain why a valid image timeline and
working Chapter navigation can still omit that provider.

`080c19f0` retains name-bearing Chapters in atom order. `0827b2b8` normalizes raw
start 1 to zero; `0827b3f0` scans until the first future start, selecting the last
eligible equal start. The Host Player sorts/deduplicates for its own navigation;
that policy is not silently replaced. The new Native Chapter Index describes
firmware interpretation beside the original editable metadata.

Flags 3 satisfy the two traced gates when valid named Chapters exist. They do not
prove complete image delivery. Earlier physical observations involved ALAC Music
Tracks with working navigation and unchanged artwork; the new flag combination
has not been validated on that device. See
[album and chapter artwork](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/album-and-chapter-artwork).

## Raw time keys and asynchronous delivery

MHNI `+0x24` becomes the native thumbnail's raw time key. `08185544` caches ordinary
selected keys as raw plus one, preserving raw `0xffffffff` specially.
`081853d0` adds one to its input position, while `081853f8` returns an already
transformed key and `0818542c` consumes a key without another increment.
These are distinct interfaces, not a reason to adjust serialized timestamps.

The provider's ordinal getter feeds transformed keys into its cache window;
completion uses equality against those keys to recover an index. Duplicate keys
can therefore lose the original ordinal. The callback compares the resulting
artwork index with the named Chapter index; it does not join their timestamps.
This supports an alignment diagnostic for explicit authoring, not rewriting
retained sequences. See [cursor boundaries](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/artwork-cursor-edge-cases)
and [timing data flow](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/artwork-timing-key-pipeline).

Artwork event `0x8000d` announces changes independently of position event
`0x80008` and its 1000-position-unit threshold. Request issuance, cache completion
and visible presentation are distinct. Exact physical update timing and all
normal/expanded media-view bindings remain open.

## F1061 geometry: three separate values

The F1061 descriptor supplies an intrinsic 55-by-55 bitmap with 112-byte rows.
`080dc304` nevertheless reads the MHNI-declared byte count rather than deriving
it from those dimensions. Its rectangle accessors use the stored signed bounds;
`080dc2b8` reports right minus left and bottom minus top. Descriptor dimensions,
stored payload extent and visible rectangle are therefore separate values.

Both 6160 bytes (55 rows) and 6272 bytes (56 rows) remain distinct retained
allocations. Tight 55-by-55 RGB565 would be 6050 bytes and would ignore the observed
112-byte stride. The inspected accessors do not clamp a 56-pixel rectangle to the
descriptor's 55 pixels. Subsequent tracing establishes that the generic Draw
widget obtains its source dimensions from the bitmap wrapper and copies 55 by 55
pixels. Its aligned RGB565 copier reads the two spare bytes per row but masks
them out; a 56th stored row contributes no pixels on this path. Other resource
bindings, rendering paths and physical display behavior remain unverified. See
[renderer clipping](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/artwork-renderer-clipping).

Keep the existing 56-row authoring default and evidenced retained-layout handling
from ADR-0111/0131. A descriptor alone does not justify replacing all saved
dimensions or payloads. See [F1061 geometry](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/artwork-f1061-geometry).

## Further importer, format and cache evidence

The subsequent [import contract](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/artwork-import-and-file-contract)
establishes root length/required-zero gates, MHSD type-3 skipping, zero-ID
allocation, filename-base selection and unchecked short reads in the ordinary
bitmap loader. Host range validation and MHIF consistency policy remain useful;
the firmware reader's permissiveness does not replace those checks.

The [raster catalog](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/artwork-raster-format-catalog)
enumerates 31 concrete descriptors but distinguishes recognition from advertised
Classic formats and reachable providers. Descriptor rotation is now named;
unsupported cases do not guarantee a zero descriptor. These findings do not add
31 formats to a Device Profile.

The [cache-policy trace](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/artwork-cache-scheduling)
shows that the player's 2000 scalar yields allocation weight 56 and an ordinal
boundary distance of 2. Its physical unit remains unproven. The separate
[NotesOnly trace](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/artwork-player-view-state)
identifies the formerly unnamed mode in artwork navigation as a global Notes
preference rather than a media-kind flag. Neither finding changes saved timestamps.

## Reproducibility and limits

The next product adoption is recorded in
[ADR-0203](../adr/0203-validate-artwork-file-references-and-allocations.md).
It separates primary pixel length from allocation, makes filenames authoritative,
rejects ambiguous reverse ownership, excludes non-thumbnail containers from
timelines while retaining them, and strengthens independent generated-allocation
and thumbnail-count validation. Explicit source capture no longer depends on
the filename spelling its format ID. Regression fixtures remain synthetic;
successful preparation is not a physical display result.

Private raw firmware, exports and scripts remain in the sibling firmware lab.
The wiki reports cite the function addresses and independent byte/model audits.
Product regressions use synthetic bytes and public interfaces, with no runtime
dependency on that lab. Original iOpenPod remains the behavioral baseline;
firmware evidence supersedes its producer assumptions only where traced.

Do not generalize this pass to every firmware or codec. MHIT artwork-count semantics,
all completion scheduling, alternate rendering paths and actual display transitions
need separate evidence. [ADR-0202](../adr/0202-adopt-native-artwork-and-chapter-semantics.md)
records the exact adopted behavior and preservation policy.
