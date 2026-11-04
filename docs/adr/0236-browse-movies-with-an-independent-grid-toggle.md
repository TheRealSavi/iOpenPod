# ADR-0236: Browse Movies with an independent grid toggle

- Status: Accepted
- Date: 2026-11-04

## Decision

Movies defaults to a grid of artwork and titles, with the shared grid/list toggle
switching to its existing Track table. This page does not follow the iPod Library
View Mode setting. A single click selects a Movie without opening details or
activating playback. Explicit Track actions retain their existing behavior.

`TrackPage` opts into a virtualized `TrackGridView` only for Movies. Both views use
the same filtered Track model and search; switching transfers selection and keeps
the existing table instance, sorting, and column configuration. Cards reuse shared
Library painting, selection, drag, and Track actions. Other Track pages and Select
Media retain their current presentation.

## Consequences

Movie browsing remains independent of Album and collection detail layouts, without
another Library model or a new persisted setting. Tests cover the default, each
Library view mode, single-click behavior, switching, and explicit activation.
