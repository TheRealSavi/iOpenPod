# ADR-0237: Share Album browsing with Music Videos

- Status: Accepted
- Date: 2026-11-04
- Extends: ADR-0072 and ADR-0235

## Decision

Music Video groups are browsed as Albums. Music Videos reuses `LibraryPage`,
`AlbumGridView`, and the Album card delegate, including the same single-cover
artwork selection, placeholders, captions, sorting, and search. The iPod page
follows Split Table, Whole Page Table, and iTunes 11 inline expansion exactly as
Albums does. Host browsing and Select Media use the same Album components while
retaining their existing source isolation and selection policy.

`AlbumListModel` has an explicit media scope, defaulting to Music. The Music Videos
projection includes only Music Video Tracks; the page derives its Track filter
from that scope. Album grid actions and drags resolve the summary's Track
identities through the current Library Workspace, rather than assuming Music or
matching an Album name across media kinds. Counts, artwork, playback, and queue
actions therefore agree about each group's membership.

## Consequences

Both routes share presentation and interaction behavior without parallel page
implementations. Tests cover layout changes, one-cover metadata, media isolation,
playback and queue actions, drags, and Select Media behavior.
