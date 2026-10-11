# iTHMB research versus current iOpenPod policy

Research date: 2026-10-11. Implementation inspected at local HEAD
`e6fa69065edc5858277b818fe5ccee1925566eeb`; Original iOpenPod baseline at
`a20242428b93b672d14b37230772dbad75139c69` (`origin/1.x`). This is a research
comparison, not a production patch or a replacement ADR.

## Boundaries already established

[CONTEXT.md](../../../CONTEXT.md), [GLOSSARY.md](../../../GLOSSARY.md),
[source architecture](../../source_architecture.md), and
[ADR-0012](../../adr/0012-load-artwork-lazily-across-existing-boundaries.md)
already place capability knowledge in Device Registry, binary interpretation in
iPodDB, device I/O in Storage, and workflow composition in iOpenPod. iTHMB decoding
receives bounded bytes plus an explicit layout. Format investigation does not
require putting filesystem access into a decoder or creating a separate runtime
dependency on Original iOpenPod.

The [Original artwork writer](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/artworkdb_writer/artwork_writer.py)
preserves retained representations with unexpected sizes and selects the most
common size for MHIF when a format has mixed lengths. Its
[format presets](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/device/artwork_presets.py)
include model-specific overrides. These are relevant baseline behaviors, not
independent confirmation that all produced files were tested on every firmware.

## Existing decisions relevant to the new evidence

| Record | Existing policy | Research implication |
| --- | --- | --- |
| [ADR-0033](../../adr/0033-create-artworkdb-from-catalog-capabilities.md) | Create initial ArtworkDB from identified capabilities, use creation root value 6, preserve retained variants, verify references and bytes. | Root value 6 and generating all declared cover formats are project choices; #178 merits a later review of required versus associated formats. |
| [ADR-0111](../../adr/0111-correct-evidenced-artwork-format-sizes-during-preparation.md) | Correct conflicting MHIF sizes when sufficiently supported by retained fixed-size representations and file evidence. | Consistent with foo_dop's alternative file-size semantics, but an arbitrary mismatch is not proof of a safe correction. Later ADRs amend its equality/geometry rules. |
| [ADR-0121](../../adr/0121-preserve-retained-f1061-raster-height.md) | Preserve evidenced 55/56-row F1061 behavior. | The latest reported 55-row samples increase motivation for better provenance, without settling empty-library defaults globally. |
| [ADR-0124](../../adr/0124-accept-validated-mixed-f1061-layouts.md) | Validate each known F1061 raster and its allocation; retain mixed sizes and choose output from validated evidence. | Explicitly acknowledges physical mixed-layout compatibility remains unverified. |
| [ADR-0131](../../adr/0131-accept-bounded-visible-dimensions-in-packed-artwork.md) | Separate visible bounds from fixed packed-raster size with explicit stride. | Matches the need to keep visible content and stored geometry separate; does not automatically generalize to planar or field-based layouts. |
| [ADR-0133](../../adr/0133-recover-evidenced-artwork-without-clearing-unavailable-covers.md) | Recover evidenced hidden records and replace damaged artwork through scoped workflows. | Artwork disappearance can arise from counts, missing data, or workflow intent independently of a codec mismatch. |
| [ADR-0135](../../adr/0135-pack-photos-into-bounded-shared-shards.md) | Pack Photos into bounded shared shards and preserve old ranges. | Photo sharding evidence should not silently become proof of an album-art firmware limit. |

These decisions remain in place. This dossier does not change a format definition,
remove 1068, normalize retained ArtworkDB records, or change shard sizes.

## Concrete disagreements and policy gaps

### F1061 default versus sampled iTunes output

The current [catalog](../../../src/device_registry/data/catalog.py) defines F1061
as 56 by 56 RGB565LE with 112-byte rows. The
[preparation path](../../../src/iPodDB/library/_artwork_writing.py) recognizes
retained 6,160- and 6,272-byte rasters, prefers an existing MHIF size that occurs
among validated rasters, and otherwise chooses the most common size with the
Device Profile as tie-breaker. With no retained images, an accepted MHIF size can
select rows; a new database falls back to the profile.

The newest issue report says its sampled iTunes 1061 allocations are 6,160 bytes.
That conflicts with treating the catalog default as a universal on-device truth,
but not with the existence of a deliberate fallback policy. The current tests and
ADRs establish acceptance/preservation behavior, not physical proof of the default
on all devices. The [issue ledger](issue-evidence.md) retains both supporting and
contrary reports.

### Allocation rules were broadened by ADR-0133

ADR-0124 originally restricted a retained F1061 allocation to 6,160 or 6,272 bytes.
ADR-0133 explicitly amends that decision: a nonzero secondary size describes
allocation, which may include padding, while zero means no separate allocation
was recorded. Allocation must be at least the validated raster length, fit the
captured file, and satisfy overlap checks. F1061 retains its two known raster
heights; extra allocation does not establish another raster layout.
[Original decision](../../adr/0124-accept-validated-mixed-f1061-layouts.md)
[Accepted amendment](../../adr/0133-recover-evidenced-artwork-without-clearing-unavailable-covers.md)

The inspected `_validate_retained_artwork_format` implements that later rule:
the raster is restricted to 6,160 or 6,272 bytes, while allocation is computed as
`image_size_2 or image_size` and validated separately. Tests cover a zero secondary
field, additional nonzero allocation bytes, retained-byte preservation, and file
bounds. There is no unresolved ADR/code discrepancy here.
[implementation](../../../src/iPodDB/library/_artwork_writing.py)
[allocation regressions](../../../tests/iPodDB/library/test_artwork_allocations.py)

An earlier version of this research overlooked ADR-0133's amendment. Narrowing
the implementation to the original ADR-0124 wording would regress the accepted
padding support, not fix a format inconsistency. These tests establish software
behavior and preservation, not compatibility of every allocation on every firmware.

### Older PhotosDB physical-size explanation

The [PhotosDB format notes](../photosdb-format.md#photo-specific-meanings) describe
recovering the stored dimensions by adding MHNI padding to MHNI dimensions. The
later [UYVY/I420 investigation](../ithmb-uyvy-format.md#connected-ipod-experiment)
explicitly reports a captured F1067 width of 704 and padding of 8 in a physical
720-pixel raster, for which that addition gives 712 and misplaces the chroma
planes. It advocates using independently established physical geometry first.

The older explanation is therefore a writer convention with limited applicability,
not a safe general decoding equation. Its historical wording remains unchanged
here; the [container notes](container-and-index.md#geometry-four-quantities-that-must-remain-separate)
make the distinction explicit. This investigation did not repeat the older
connected-device measurement.

### Size limits are different policies with different units

The current [WriteTarget](../../../src/iPodDB/library/writing.py) defaults artwork
files to `256 * 1024 * 1024` (268,435,456 bytes) and Photo files to
`256_000_000`. The latter matches the numerical historical libgpod constant; the
former does not. The album-art allocator checks prospective end against its target
cap and the 32-bit address bound. The historical libgpod writer checks its existing
offset before writing; foo_dop checks the prospective end against 500 MiB.
[allocator](../../../src/iPodDB/library/_artwork_writing.py)
[historical comparison](container-and-index.md#shards-offsets-and-rollover)

Calling all of these “256 MB” or “500 MB” loses necessary information. Neither
matching iTunes's observed shard length nor matching libgpod's constant is, alone,
a validated fix for #178. Correct references and controlled boundary tests are
still required.

### Provenance of capability metadata

The [metadata authority implementation](../../../src/device_registry/authority.py)
can synthesize artwork specifications from catalog capabilities. A subsequently
captured SysInfoExtended file may therefore repeat an application assumption.
It must not automatically be counted as an independent native-device measurement.
The [Device Profiles notes](device-profiles.md) distinguish queried metadata,
generated caches, inferred layouts, and hard-coded fallbacks.

### Application-only artwork is not native display support

[ADR-0118](../../adr/0118-write-application-artwork-for-non-cover-devices.md)
uses an application-only F1060 representation on profiles without native cover
display. A newly found F1060 file on a screenless or monochrome device therefore
cannot by itself establish native firmware support for that layout. Producer and
purpose belong in the evidence key.

## Questions for a later implementation decision

1. How should a format descriptor record evidence scope, firmware/writer variants,
   pixel encoding, raster order, physical geometry, visible-bound convention,
   stride, and allocation without treating the numeric ID as globally unique?
2. Which declared formats are ordinary Track covers, associated/conditional
   representations, Photos, chapter images, or application-only output?
3. When should retained verified representations determine output, and what should
   happen when an empty library offers no sample evidence?
4. Which independently evidenced format variants are safe to append together, and
   which require preserving data while declining an unsupported mutation?
5. How can fixture provenance distinguish device-generated bytes, iTunes output,
   third-party output, generated metadata, and synthetic tests?

These questions follow from the research rather than committing to a new design.
Any resulting durable architectural decision should be an ADR, and any behavior
change should include proportionate tests plus explicit physical-validation limits.

## Work performed in this pass

Only research Markdown files were added under this directory. Primary source and
issue inspection, read-only analysis, citation checks, and Markdown validation
support the dossier. No new runtime dependency, production codec, firmware claim,
or device mutation is part of this change. Existing local user changes were left
outside the research scope.
