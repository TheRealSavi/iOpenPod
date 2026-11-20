# ADR-0291: Publish qualified native Genius Mix covers

- Status: Accepted
- Date: 2026-11-18
- Extends: ADR-0184 and ADR-0289

## Evidence

The [firmware investigation](../research/classic-genius-mix-artwork-2026-11-18.md)
establishes optional native covers, with proxy fallback. Classic 2.0.4/2.0.5 uses
F1069 at 142 × 142; Nano 7 1.0.4 and 7.5 1.1.2 use F1010 at 240 × 240.
Both use RGB565 and ArtworkDB's reverse image identity linked to the Mix's
persistent identity. Native format support is separate from native Mix playback.

## Decision

Device Registry refines `GeniusCapabilities.mix_artwork` only from qualified
RetailOS and updater-family evidence at the strongest authority. The application
maps supported Classic and Nano 7 profiles to explicit image formats. Missing or
conflicting evidence, other releases, and other Nano generations remain unknown
for this writer. New device research does not automatically enable publication.

Use the colored genre/mood symbol and rings from Add Mixes. At the user's request,
runtime rendering replaces the initial bundled PNG approach. One shared painter
produces the chooser and renders device covers on demand at 142/240 pixels, using
the canonical dark palette. There are no generated PNG assets, build step, or
pixel cache. The existing small SVG source cache remains.

Application composition supplies a byte-only `MixCoverRenderer` to the Device
Coordinator. The service has no GUI import. Its worker calls the renderer, which
owns a separate QImage, QPainter and QSvgRenderer for each call and returns owned
RGB bytes. Static SVG/image painting requires no widget, QPixmap or GUI event
loop. Tests cover concurrent rendering without a Qt application and equality with
the chooser painter. A migration check confirmed all 44 runtime covers matched
the former PNG pixels exactly, avoiding unnecessary device artwork replacements.

`GeniusMixArtwork` is explicit Library Draft intent, separate from Track artwork.
The Application Layer supplies it for owned Mixes, including backfill during the
next save/Sync, and captures ownership and existing image dependencies. iPodDB
resolves final Mix identities after binary/SQLite reconciliation, so removed or
depleted Mixes lose their image link. It writes ordinary MHII/MHNI records and
new, nonoverlapping iTHMB files, then reparses and verifies the reverse identity,
format, geometry, bounds, and packed pixels. No fake Track or firmware patch is
involved. Storage publishes artwork with native Mix data and ownership in the
existing recoverable transaction.

New Mix IDs avoid retained Track and artwork reverse identities; Classic also
avoids its browser's low-word cache collisions. Existing ambiguous reverse links
or Track-shared image ownership block replacement rather than reassigning it.
An identical cover retains exact bytes and adds no file. Replacement/removal
clears only the owned reverse link: old records and immutable pixel ranges stay
retained, consistent with Track artwork. This does not introduce compaction or
delete unrelated assets. Retained files are never overwritten to publish a cover.

## Consequences

Classic shared 2.0.5 on older physical Classic hardware uses the running firmware's
qualified cover path. Nano 5 and 6 remain outside this implementation; Nano 6 has
a distinct F1073 path requiring separate qualification. Existing external Mixes
and their artwork remain untouched unless explicitly managed through a later
supported workflow. Tests cover device gates, UI rendering parity, complete virtual
publication, rollback, removal/depletion, repeat saves, and preservation of album
artwork. Physical display verification is still outstanding.
