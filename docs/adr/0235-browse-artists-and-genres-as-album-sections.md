# ADR-0235: Browse Artists and Genres as Album sections

- Status: Accepted
- Date: 2026-11-04
- Extends: ADR-0072 and ADR-0126

## Context

iTunes 11 style previously affected the Albums route while Artists and Genres
retained a collection grid/list switch and a separate Track table. The requested
presentation instead keeps a source list beside the selected collection's Albums.

## Decision

In iTunes 11 style, Artists and Genres use list-only browsing and hide the grid/list
switch. The detail heading contains the collection name, Album and Track counts,
and Play, Add to top of queue, and Add to bottom of queue actions. Album sections
show artwork on the left, title and year above two columns of Track number, title,
and duration. Ratings are omitted. Genre sections use smaller artwork and add a
muted Album Artist byline beside the Album title.

`CollectionAlbumList` owns the shared header and scroll surface. It projects the
Album model and filtered Track model into sections, materializing widgets around the
viewport and retaining sections with keyboard focus or selection. Sections reuse
`InlineAlbumPanel` in a stacked presentation. The same Track identities, ordering,
selection, drag controller, context actions, and activation paths serve both
presentations. New section views receive the shell's existing Track action and
Library Workspace bindings. No per-Track widgets are created.

Genre sections include only matching Tracks, including Albums containing several
Genres. Header actions use these same Tracks in Album order. Changing the setting
restores the other layouts and their grid/list choice without replacing models.
Select Media does not adopt this presentation. TV Shows and Music Videos retain
their existing layout policy.

## Consequences

Artists and Genres share one implementation, with explicit differences for cover
size and Album Artist attribution. Large collections keep widget creation bounded
by the visible sections and retained selections. Layout and playback tests cover
view-mode transitions, filtering, empty collections, ordering, and action scope.
