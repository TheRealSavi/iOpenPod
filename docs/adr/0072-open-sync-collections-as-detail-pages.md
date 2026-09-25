# ADR-0072: Open Sync collections as detail pages

- Status: Accepted
- Date: 2026-09-24
- Extends: ADR-0067

## Context

The Select Media stage reused the iPod browser's split grid and Track table. This
left less space for Album and collection cards and kept an unrelated Track list
visible before the user opened a collection. The Track search belonged to the
splitter's title bar, so removing that split also requires a new search location.

## Decision

In Sync selection mode, Album and collection pages initially show only their
browser and toolbar. An ordinary card click or keyboard activation opens a full
detail page with artwork, collection metadata, Select All and Deselect All actions,
and the existing Track table. The detail page contains a standalone Track search
above the table and a Back action. It has no Track title bar or vertical splitter.
Artist and Genre list views retain their source rail; opening an Album there uses
the same detail page.

Back returns to the existing browser instance, retaining its query, sorting,
grouping, view mode, and scroll position. Opening a collection clears the detail
search. Card checkboxes, group headers, and modified selection gestures retain
their existing behavior without opening a detail page.

The detail page captures the scoped Track identities when it opens. Bulk actions
apply to that complete collection scope, independent of the current Track search,
through the existing Sync Selection. Search affects only the table rows. Selection
regrouping must not replace the open collection, and replacing the scanned Library
returns the page to its browser.

## Consequences

The GUI reuses the source-isolated Host artwork provider, Track model, table,
settings, and context actions. Sync navigation is a presentation mode of the shared
Library pages. The normal iPod browser defaults to its existing split layout. This
change adds no device writes or Sync execution behavior.

## Extension: iPod Library View Mode (2026-09-25)

The global iPod Library View Mode preference offers Split Table (default) and Whole
Page Table. The latter reuses this detail presentation for iPod Album and collection
pages, retaining their existing Track table and iPod actions while hiding Sync
Selection controls. The preference applies immediately and persists across
restarts. The Host browser keeps its own presentation policy independently of this
iPod preference.
