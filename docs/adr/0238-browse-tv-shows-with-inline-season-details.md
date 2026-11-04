# ADR-0238: Browse TV Shows with inline Season details

- Status: Accepted
- Date: 2026-11-04
- Extends: ADR-0072, ADR-0126, and ADR-0235

## Decision

TV Shows uses the shared Library card presentation with one cover, selected from
the first Track with artwork in the show. The representative cover is projected
over all show Tracks, independently of the four-tile collection artwork limit.
Whole Page Table and Split Table retain every Track in the selected show. Host
browsing and Select Media also use single-cover cards and detail artwork while
retaining their existing presentation and selection policy.

In iTunes 11 style, a show opens inside the existing expanding grid row.
`InlineTVShowPanel` specializes `InlineAlbumPanel` with numerically ordered Season
tabs and one virtualized episode per row. Switching Season keeps the panel open,
replaces its Tracks, and updates its artwork and derived colors from the first
episode with artwork in that Season. Missing Season numbers share an Unknown
season tab. Episode ordering uses episode number, with Track number as fallback.

Each row has two text columns: episode number, release date, and duration on the
left; title and a two-line, elided description on the right. Release dates use the
calendar date in the metadata's UTC value. There is no More action or description
expansion. The panel retains the shared cover placement, selection, keyboard,
context-menu, drag, playback, and queue behavior. Its group actions apply only to
the displayed Season; show-card actions still apply to the entire show.

## Consequences

The grid expansion accepts the shared equalized grid interface, so TV Shows and
Albums use the same reveal, scrolling, resize, and dismissal behavior. Album
panels expose small context and Track-projection hooks instead of duplicating
their interaction code. Episode rows remain delegate-painted, with no widget per
Track. Tests cover Season switching, artwork/color changes, incomplete metadata,
live updates, view-mode transitions, media isolation, and action scope.
