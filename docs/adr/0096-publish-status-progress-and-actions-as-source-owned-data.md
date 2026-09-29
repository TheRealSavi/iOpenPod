# ADR-0096: Publish status progress and actions as source-owned data

- Status: Accepted
- Date: 2026-09-29

## Context

`ApplicationStatus` originally carried text only. Backup progress and chaptered
Album conversion each added separate widgets directly to the global status bar.
Those widgets had different styling and their progress and actions were absent from
the statuses popup.

## Decision

Each active status may carry typed progress and one named action alongside its text.
The status is owned and cleared by its source. A zero progress total means the work
is indeterminate. The status model emits action requests by source and key; it does
not own GUI widgets or operation callbacks. One presentation renders the current
status in the global bar, and the statuses popup renders every active status using
the same progress and action controls.

## Consequences

- Callers can add progress or an action without constructing status bar widgets.
- The bar rotates text and controls together; the popup keeps every active operation
  available while another source is current.
- Action requests are ignored after their source clears or changes that action.
