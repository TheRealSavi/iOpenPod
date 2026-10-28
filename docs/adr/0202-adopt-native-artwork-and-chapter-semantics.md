# ADR-0202: Adopt native artwork and Chapter semantics

- Status: Accepted
- Date: 2026-10-28
- Extends: ADR-0019, ADR-0138, ADR-0139, ADR-0195

## Context

Static Classic 120GB RetailOS 2.0.1 analysis resolves artwork identity precedence,
two independent Chapter-header flags, player format selection, and the distinction
between a raw artwork time key and a transformed runtime key. Current iPodDB falls
back to reverse artwork ownership after a broken direct reference and authors
Chapter navigation flags without coordinating explicitly authored timed artwork.
See the [evidence report](../research/classic201-artwork-semantics-2026-10-28.md).

Original iOpenPod and current iOpenPod provide historical authoring and recovery
behavior, but neither overrides directly observed firmware lookup rules. Static
evidence does not establish complete display behavior or universal model support.

## Decision

A nonzero stored MHIT artwork reference selects direct image-ID lookup exclusively.
If the image is absent, the projected artwork is unresolved, a source diagnostic
explains the missing reference, and the raw value remains retained. Only a zero
reference selects reverse lookup by persistent Track identity. This replaces the
previous implicit display fallback, not the explicit repair or replacement
workflow. Shared valid image IDs remain supported.

Name MHNI `+0x24` `image_time_key` in the single shared Chunk Definition and its
consumers. Its u32 little-endian layout and raw values are unchanged. In particular,
no runtime `+1` transform is written to ArtworkDB, and retained `0xffffffff`
remains governed by the existing special-group preservation policy.

Expose typed flags for Chapter `hedr +0x18`: mask 1 enables named-Chapter queries;
mask 2 enables Chapter artwork during Track import. Keep the raw storage field
compatible and preserve every other bit. A read-only Native Chapter Index lives
in optional iPod Track Details. It follows stored order, includes present name
atoms, normalizes raw Chapter start 1 to zero for its view, and reports disabled,
missing, duplicate-header, unordered, duplicate-start and unnamed cases. The
parser exposes the last duplicate header while firmware reads the first, so this
view leaves duplicate-header interpretation unavailable. Editable metadata and
the Host Player's existing navigation policy remain separate.

During an explicit `TimedArtworkAsset` preparation, a target with chapter formats
can enable both known flags when the Track has recognized named Chapter data.
An ordinary navigation-only Chapter header remains 1. Explicit timeline authoring
retains unknown bits and all Chapter atoms/positions; missing, extended or duplicate
headers are preserved with a diagnostic rather than broadly repaired. A different
number or ordering of normalized Chapter starts and authored image times warns
that their indices may not correspond. It never shifts, sorts or deletes retained
Chapter data to force a match. An absent Chapter container is not synthesized.

Unrelated metadata changes and ordinary cover replacement preserve existing
Chapter flags. This extends ADR-0139 only for deliberate timeline authoring;
media classification, podcast presentation flags, artwork counts and F1061
pixel-writing policy are unchanged. The Classic F1055/F1029 chapter format set
now has native firmware evidence. Other models retain explicitly inferred family
policy rather than a claim of new hardware verification.

## Consequences and validation

The product gains a closer native interpretation without turning its editable
Library or Host Player into an emulator. Source and preparation diagnostics use
the established review flow. No firmware image, Ghidra export or research-lab
dependency enters the application, and all persistence remains in Storage.

Tests cover direct-link success/failure/reload, shared images, retained references,
literal-offset key reads/writes, 0/1/2/3 flags and unknown bits, named/unnamed Chapter
atoms, duplicate headers and starts, explicit authoring, target capability gates,
opaque-header retention, ordinary-cover preservation and unchanged database bytes.
Physical acceptance of new Chapter artwork flags remains open. Subsequent static
analysis establishes 55-by-55 copying for F1061 through the generic Draw widget;
other rendering paths and a physical comparison remain unverified. This evidence
update does not change this ADR's pixel-writing policy. A successful save alone
does not prove image delivery on the iPod.
