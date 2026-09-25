# ADR-0057: Manage Photo Album membership through collection cards

- Status: Accepted
- Date: 2026-09-15
- Extends: ADR-0053 and ADR-0054

## Context

ADR-0053 permits retained user Photo Album membership edits through the common
Library Draft, but ADR-0054 left the Photo context-menu actions as placeholders.
Separate add and remove menus would require the user to remember the current Photo
Album and would not show the complete membership of a Photo across albums.

The interaction also needs to preserve the Photo browser's virtualized presentation
and lazy image-loading bounds. It must not create a widget per Photo Album, expose a
PhotosDB document, or authorize a device write.

## Decision

- The selected-Photo context menu exposes one **Manage Albums…** action. It opens a
  modal dialog containing every retained user Photo Album; the Master Photo Album is
  not editable and is omitted.
- Photo Albums use the shared virtualized Library collection-card geometry. Each
  card paints a two-by-two collage from at most four distinct retained member Photos
  through `PhotoPixmapProvider`. Empty collage positions retain the ordinary
  placeholder treatment.
- A large circular checkbox is painted over the top-right of each collage. For one
  selected Photo, checked means the Photo is a member and unchecked means it is not.
  For a multiple-Photo selection, checked means every selected Photo is a member,
  unchecked means none is a member, and the mixed mark means only some are members.
- Clicking a checked control removes every occurrence of the selected Photo
  identities from that user Photo Album. Clicking an unchecked or mixed control
  appends only missing Photo identities in grid-selection order. Existing membership
  order and unrelated duplicate occurrences remain unchanged.
- Each toggle is applied immediately through one validated `LibraryWorkspace`
  membership intent. It remains a reversible Library Draft edit and reaches the iPod
  only through Review Changes and Save to iPod.
- The dialog closes when the Workspace generation changes and disables membership
  controls while the Library Workspace is locked for saving. Clicking anywhere on
  the rendered collection card toggles its membership state instead of selecting
  the card; whitespace between cards remains inert. Keyboard activation remains
  available for the current card.

## Consequences

A user can see and change a Photo's complete user-album membership from one place,
and bulk Photo selection has explicit, lossless mixed-state behavior. The dialog
reuses the bounded Photo cache and allocates no persistent card widgets.

This does not permit Master Photo Album edits, Photo asset addition or removal,
Photo Album creation or deletion, or direct device mutation. Membership changes
remain subject to the existing PhotosDB preparation, verification, and publication
rules.
