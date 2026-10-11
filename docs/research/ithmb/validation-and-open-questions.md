# iTHMB validation and open questions

Research date: 2026-10-11. This document proposes the next evidence to collect.
It does not report that these experiments have been performed or approve device
mutations. The [issue ledger](issue-evidence.md) records what participants actually
reported; the [format notes](pixel-formats.md) describe inspected implementations.

## What can presently be concluded

| Question | Current conclusion | Remaining limit |
| --- | --- | --- |
| Is raw iTHMB self-describing? | The inspected classic iPod implementations store pixels externally indexed by database ranges. | The extension alone cannot classify later Apple cache families. |
| Is a numeric format ID globally unique in meaning? | No safe global assumption: device-specific overrides already exist in source, including Nano 7. | The complete model/firmware/writer matrix is not known. |
| Does the newest report establish 6,160-byte F1061? | It reports that allocation for three sampled devices. | No attached raw records, hashes, script, or firmware matrix independently reproduces it. |
| Is 6,272-byte F1061 invalid? | Not established. Historical code writes it, and issue 111 reports working art in a library with mixed sizes. | The exact mixed representations were not individually verified on firmware. |
| Is 1068 mandatory for every Track? | Not established; recent iTunes inventories report zero or one occurrence while iOpenPod generates it per artwork entry. | Role, association rules, live references, and content triggers remain unknown. |
| Is 500 MiB a universal maximum? | No. It is a reported iTunes boundary and a foo_dop policy; libgpod uses another policy. | Firmware limits, performance effects, and rollover conditions need controlled tests. |
| Are decoded pixels enough to validate a write? | No. A Host decoder can accept a layout the firmware does not select or cannot address. | Database association, counts, auxiliary fields, allocation, and physical display must also be checked. |

Sources and qualifications for these conclusions are collected in
[container and index](container-and-index.md), [Device Profiles](device-profiles.md),
and [issue evidence](issue-evidence.md). “Not established” is deliberately different
from “false.”

## F1061: preserve competing explanations

The latest [#178 comment](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-6106769456)
reports 6,160-byte slots with 112-byte rows and usually 55-by-55 visible content,
with some smaller visible bounds. The
[libgpod table](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c)
uses 56 by 56 and contains an explicit uncertainty comment. The
[issue 111 report](https://github.com/TheRealSavi/iOpenPod/issues/111#issuecomment-4634808159)
and [ADR-0124](../../adr/0124-accept-validated-mixed-f1061-layouts.md) show why the
56-row alternative cannot simply be erased.

| Hypothesis | Evidence that would discriminate it |
| --- | --- |
| One 55-row format, with optional allocation padding to 56 rows | MHNI data length 6,160, allocation 6,272, neighboring offsets respecting 6,272, and coherent 55-row pixels on the same sample. |
| Both 55-row and 56-row encodings accepted by one firmware | Same-unit, same-firmware display of independently authored 55-row and 56-row records with all other relevant fields controlled. |
| Different layouts on different firmware of one model | Untouched reference libraries, exact hardware/firmware identifiers, and consistent per-firmware differences with writer held constant. |
| Different layouts on different models sharing ID 1061 | Equivalent reference procedure across identified models, with enough same-model repetitions to distinguish writer variation. |
| Mixed writer history, stale fields, or malformed records | Chronological captures and a change history showing which writer introduced each size or metadata mismatch. |
| Data are renderable but firmware uses another representation | Track-to-image-to-format tracing plus tests of the exact screen/representation, rather than only Cover Flow success. |

None of these hypotheses is mutually exclusive across all devices. A 6,272-byte
range could be one extra row, an allocation tail, or a bad descriptor; the number
alone does not decide. A 6,050-byte range could reflect tightly packed rows or an
incorrect size declaration. Renderability and safe mutation require different
levels of evidence.

## Capture manifest

For a reproducible corpus, save immutable originals before analysis. Hash files
with SHA-256 and retain a private manifest with these fields. Published research
should use anonymous sample IDs and omit personal serial numbers, Track names,
and image content unless the owner has chosen to share them.

| Group | Required context |
| --- | --- |
| Device | Anonymous unit ID, model/order number, generation, hardware/board identifiers, firmware version and build as reported by device and metadata, modified hardware/firmware status. |
| Environment | Filesystem type, restore history, Host OS, iTunes or alternate writer version/build, and which application last touched each artifact. |
| Timing | Capture time, before/after operation, mounted state, successful flush/eject history, and whether the device rendered the captured library before further synchronization. |
| Identity evidence | Original SysInfo, SysInfoExtended or native query output, capture mechanism, and whether a tool generated or reconciled these files. |
| Library | ArtworkDB and iTunesDB/iTunesCDB; for Photos, Photo Database and relevant full-resolution originals. Record each artifact's path, size, and hash. |
| iTHMB files | Complete filename inventory, sizes, hashes, and enough exact ranges to reproduce every claimed layout, including tails and boundary-adjacent records. |
| Source media | Reproducible generated source images and dimensions; where appropriate, source tags and embedded artwork selection. |
| Analysis | Script source, script hash/revision, tool version, extraction method, raw field values, decoded outputs, and calculations. |
| Device result | Exact screen, Track or Photo association, display orientation, reboot/reconnect status, observed image result, and any timing or responsiveness measurement. |

If only range samples can be shared, include their original absolute file offsets,
range hashes, parent file hash/size, and the enclosing database records. A screenshot
is useful for display behavior but cannot substitute for the binary data. A
synthetic replacement database tests program behavior; it does not preserve
the provenance of the original device artifact.

## Read-only analysis sequence

1. Freeze the input set and verify the manifest hashes before and after analysis.
2. Parse actual Chunk boundaries. Export MHIF and every relevant MHNI: parent
   image ID, type, path, offset, both raw size fields, dimensions, padding, and
   unknown extension words. Retain malformed records as diagnostics.
3. Group by artifact, anonymous unit, firmware, producer, purpose, format ID, and
   candidate descriptor. Do not aggregate all 1061 records into one population.
4. Compute distributions of data size, allocation size, offset deltas, dimensions,
   and padding. Deduplicate identical ranges before counting stored images;
   separately count Track references, image identities, representations, and files.
5. Check every referenced range against the actual file length. Report exact shared
   ranges, partial overlaps, dangling paths, duplicates, gaps, and trailing bytes.
   An unreferenced range is not permission to delete it.
6. Test competing layouts against the same bytes. Use physical stride and plane or
   field offsets first; apply the proposed crop afterward. Record failing candidates
   as well as successful ones.
7. Compare against known source images and an independently implemented decoder.
   Source-code ports with shared ancestry are not independent format evidence.
8. Reconcile discrepancies without changing the source: e.g. a large MHIF field
   may be a writer's file length, and an extra I420 tail may hold meaningful data.

The [older UYVY investigation](../ithmb-uyvy-format.md) already reports one local
Classic sample with nonzero F1067 auxiliary-tail image data. That observation
argues for inspecting tails rather than calling them zeros or disposable padding.
Its meaning for other devices remains unresolved.

## Controlled physical tests to run later

Begin with a known-good reference produced on the specific unit, and retain a
recoverable baseline. Use small, identified test images before scaling to rollover.
This research request has not changed a device or run the experiments below.

| Experiment | Hold constant | Change and inspect |
| --- | --- | --- |
| 1061 geometry | Device, firmware, source image, associations, file placement, other representations | Data rows, visible bounds, and allocation each in separate trials; inspect the actual list screen as well as Now Playing and Cover Flow. |
| Rollover | Device, records, image bytes, format definitions, auxiliary records | Move the same ranges into correctly named and indexed shards at controlled boundaries; inspect entries before and after each boundary. |
| 1068 role | Same device, firmware, iTunes build, and initial reference state | Add one content category at a time, trace any new 1068 reference, then test later edits and restart behavior. |
| Metadata fields | Same payloads and live associations | Change one understood field at a time; preserve Unknown Data and keep before/after dumps. |
| Writer interoperability | Same reference library and unit | Extend with one writer, reconnect with another, record normalization and display before additional rewrites. |
| Firmware variability | Same hardware where practicable, reference procedure, writer, and images | Compare safely obtainable firmware samples or independently supplied units; do not assume a firmware upgrade/downgrade is reversible. |

The latest report's 9,601 artwork-bearing Tracks versus 10,000 transferred Tracks
needs explanation before it can be treated as a matched comparison. Deduplication,
extraction, exclusions, and counting method are possible confounders, not findings.
Likewise, a fresh rebuild plus a new shard cap cannot isolate the cap as the cause.
[report and chronology](issue-evidence.md#starting-point-issue-178)

## Synthetic checks worth retaining in a future implementation

These would test software contracts, not prove firmware support:

- RGB565 primary colors and asymmetric byte-order vectors; RGB555 cases with each
  high-bit value retained and documented.
- Coordinate-labelled recursive RGB555 and rotated rectangular images so a
  transpose or Morton-axis reversal cannot pass unnoticed.
- UYVY rows with distinct luma and distinct `Y0`/`Y1`; black/white limited-range
  vectors and asymmetric chroma.
- I420 plane-boundary probes, nonzero tails, and independent physical versus
  visible dimensions.
- Odd visible widths with explicit row padding; 6,050/6,160/6,272-byte F1061 cases
  tested as separately described inputs, never inferred solely from the ID.
- Separate data/allocation fields, zero legacy extension, longer MHNI headers,
  unknown MHOD bodies, shared ranges, malformed counts, and truncated files.
- Shard-boundary, alignment-gap, stale-MHIF, large-offset, and overlap cases.
- Unchanged parse/serialize and retained payload byte equality, including Unknown
  Data. Decoder/encoder round trips alone can conceal a shared mistake.

## Unresolved format areas

High-priority gaps are the physical F1061 compatibility matrix; 1068/1069 and
`AssociatedFormat` semantics; optional versus firmware-required representations;
firmware-sensitive root and auxiliary fields; exact rollover and alignment rules;
the purpose of F1067's auxiliary tail; and the color-range behavior of I420.
Additional gaps include RGB555's high bit, less-evidenced RGB888/JPEG/CL variants,
rectangular recursive layouts, rotation conventions, and later iOS/macOS caches.
See [pixel-format limits](pixel-formats.md) and
[profile provenance](device-profiles.md).

Promotion of a hypothesis into a default writer policy should require a traceable
sample, reproducible interpretation, a scoped physical-display result, and a clear
fallback/preservation policy. One same-model firmware sample increases evidence;
it does not close the matrix. Architectural consequences belong in a later ADR.
