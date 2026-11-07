# ADR-0164: Keep Library save progress and safety visible

- Status: Accepted
- Date: 2026-10-21
- Extends: ADR-0096

Library preparation and saving retain typed stage progress through the controller
to both the status bar and Review Changes. Counts describe the current stage;
unknown totals use an activity indicator. Completing a stage never implies that
the entire save has finished. Only the controller's terminal result clears the
running presentation, and verified success reminds the user to eject the iPod.

An active status may carry a source-owned safety warning. Shared status controls
render that warning prominently. While warnings exist, the bar rotates only among
those sources; ordinary statuses remain available in the popup and resume normal
rotation afterward. This extends ADR-0096's equal rotation policy so an unrelated
notification cannot hide “Do not disconnect your iPod” during saving, including
verification, flushing, and cleanup. Preparation for review does not claim that
device publication has started. The existing Storage workflow is unchanged.
