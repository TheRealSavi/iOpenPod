# ADR-0121: Preserve retained F1061 raster height

- Status: Accepted
- Date: 2026-10-06
- Extends: ADR-0012 and ADR-0111

## Context

F1061 RGB565 artwork appears with 56 columns and either 55 or 56 stored rows.
Those fixed-size images occupy 6,160 or 6,272 bytes respectively. A single
Device Profile height cannot describe both existing ArtworkDB layouts. The
56-row layout is the Original iOpenPod default for a new database, but an
existing library may contain consistent 55-row MHNI records and a matching
MHIF entry. Preparing new artwork against the default then refuses a valid
retained layout.

Original iOpenPod 1.x declares F1061 as 56x56 and encodes new images from that
fixed definition. Its writer also carries retained image sizes forward and
uses their most common size for MHIF during a rewrite. This is useful
compatibility evidence, but does not establish one size for every library.

## Decision

For F1061 only, iPodDB selects the row count for new images from all retained
MHNI image-size fields when they consistently establish one of the two known
fixed sizes. It validates the corresponding dimensions, padding, filenames,
captured file bounds, fingerprints, and non-overlapping ranges before appending.
If the retained MHIF size disagrees with consistent MHNI evidence, preparation
corrects only that MHIF size under ADR-0111. Conflicting or unverifiable MHNI
evidence still blocks preparation.

When there are no retained F1061 images, a recognized MHIF size selects the
layout. A first ArtworkDB uses the Device Profile's 56-row default. Lazy cover
decoding uses the retained MHNI dimensions for either row count. Other formats
retain their existing layout rules. Unrelated edits leave the source bytes
unchanged.

## Consequences

Existing 55-row and 56-row libraries can receive new cover artwork without
rewriting retained thumbnails. The prepared database and thumbnail files still
pass independent verification and the recoverable Storage Transaction. A blank
ArtworkDB cannot establish a device-specific 55-row preference, so it uses the
56-row default until stronger device evidence is available.
