# ADR-0203: Validate artwork file references and allocations

- Status: Accepted
- Date: 2026-10-28
- Amends: ADR-0012, ADR-0133, ADR-0202

## Context

The Classic 120GB 2.0.1 importer reads the stored filename, byte offset and
primary MHNI size independently. It does not derive a shard name from the format
ID, consult MHIF for that read, or check the completed byte count. Only type-2
MHOD containers enter the thumbnail list. Reverse image lookup has no established
winner when several images share a Track identity. The
[evidence report](../research/classic201-artwork-semantics-2026-10-28.md) links the
firmware traces and distinguishes them from Host policy.

The previous Host read projection could invent a filename, flatten a nested path,
use allocation size as missing pixel length, and include non-thumbnail containers
in an artwork timeline. Output verification checked individual rasters without
independently rejecting new allocations inside a captured prefix or another new
image. The native u16 thumbnail count also bounds representations, independently
of the MHIT source-image count.

## Decision

Use one shared filename resolver for reading, preparation and resource capture.
Explicit leading-colon relative paths resolve below `iPod_Control/Artwork`;
preserve their nested components. Keep accepted qualified Artwork paths as Host
compatibility syntax. Never infer a filename, trim it or discard its directory
components. Unsupported tokens cannot authorize a read; another eligible
representation may still be selected. The Artwork namespace and `.ithmb` suffix
restriction remain Host policy, not a new claim about native filename syntax.

Known retained file references supplement the shallow inventory through validated
Storage operations, including nested references omitted by display projection.
Groups explicitly reused by timed edits or implicitly kept by ordinary cover
refresh are captured independently of their filename's format prefix. Unrelated
retained files need fingerprints rather than full pixel capture; directory
inventory does not become recursive discovery.

MHNI `image_size` is the pixel read length. `image_size_2` retains its existing
allocation interpretation and cannot substitute for a zero primary size. Only
recognized type-2 thumbnail containers supply display locations and times.
Other containers stay lossless, survive cover replacement, and retain their file
extent protection. Independent verification compares their complete record bytes
on retained rows and source-derived copies, allowing only relocation within the
database. Ambiguous reverse Track lookup remains unresolved and logged;
unique direct image-ID lookup still works. Duplicate image IDs retain the existing
projection failure rather than acquiring an arbitrary winner.

Preparation and independent verification reject generated thumbnail lists above
65,535 entries, invalid or reused generated identities, oversized output files,
allocations inside captured prefixes, and overlapping generated allocations.
Intentional per-Track clones of the same requested image, time and representation
may share the same exact range. Existing allocation, file-bound, fingerprint and
unchanged-prefix checks continue to protect retained content.

MHIF consistency remains authoring policy. Reading does not acquire a new MHIF
requirement, and unrelated serialization does not normalize retained records.
The F1061 55/56-row authoring policy stays in place. Factory recognition of other
formats, the cache scalar 2000 and NotesOnly do not justify adding codecs,
changing saved time keys or changing application cache scheduling.

## Validation and limits

Synthetic tests cover authoritative filenames, nested and Unicode paths, alternate
representations, exact source round trips, primary size versus allocation, reverse
identity ambiguity, non-thumbnail preservation, count and identity boundaries,
and fault-injected generated-range conflicts. F1061 vectors distinguish visible
pixels from spare samples and the extra stored row, and reject truncated stride
bytes. These checks establish Host behavior without a runtime dependency on the
firmware lab. Physical save/reload and display acceptance remain separate work.
