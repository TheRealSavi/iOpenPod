# ADR-0155: Preview publisher covers in Podcast discovery

- Status: Accepted
- Date: 2026-10-19
- Amends: ADR-0037
- Extends: ADR-0154

## Decision

Podcast search results display show artwork resolved from the publisher's RSS feed.
The Apple directory adapter continues to retain only textual metadata and the feed
URL. Its promotional artwork fields remain excluded. This replaces ADR-0037's
text-only discovery presentation without changing the source policy.

The existing Application Layer artwork controller resolves requested feed URLs on
its bounded worker pool, then loads the publisher image through the existing image
loader. Feed requests retain their deadlines, redirect validation, and byte limits.
Duplicate work is coalesced; failures are cached for the controller lifetime, and
decoded images share the byte-bounded pixel cache. Only painted results request
covers. The GUI receives pixels and repaint notifications, never feed-parser data.
Previewing a result neither subscribes to it nor persists metadata.

Episode tiles prefer the Episode's RSS image, followed by existing device artwork,
the source show's RSS cover, and a deterministic placeholder. Aggregate rows carry
their own show's cover URL so All Podcasts cannot borrow another show's image.
Device artwork remains available while a publisher image is loading or unavailable.
The separate Sync import precedence in ADR-0154 is unchanged.

## Presentation

The native Podcast browser keeps the shared iOpenPod typography, semantic colors,
source rail, and keyboard interaction. A compact show header leads into artwork-led
Episode tiles. Dates, duration, and nonstandard Episode types remain visible;
selection reveals additional author and Episode metadata. Long titles wrap and
descriptions are bounded. Full descriptions do not appear on hover; Episode
descriptions remain available to accessibility clients.
Batch actions appear with selection, and show Sync controls sit below the list.

Discovery pairs show covers with title, publisher, and brief category/count metadata.
The direct-RSS form opens on request. Loading, empty, and failed searches have an
explicit result state; unavailable images do not prevent subscribing. Searching
clears stale results and disables activation while the controller is busy.

## Validation

Controller tests cover lazy feed resolution, deduplication, missing covers, and
failed feeds. Painted-delegate tests verify Episode/device/show precedence in both
single-show and aggregate views, and search covers keyed by feed identity. Dialog
tests exercise direct-RSS disclosure and busy-state subscription guards. Native Qt
renders are inspected in light and dark themes at ordinary and compact desktop
window sizes. This decision adds no device writer or dependency.
