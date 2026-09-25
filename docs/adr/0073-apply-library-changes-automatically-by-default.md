# ADR-0073: Apply Library changes automatically by default

- Status: Accepted
- Date: 2026-09-24
- Extends: ADR-0022, ADR-0026, and ADR-0030

The user requested immediate application of Library edits with an optional manual
draft workflow. The global **Draft all changes** setting defaults to off. Off hides
the sidebar's Review Changes button and automatically prepares and accepts each
current Library Draft through the existing verified Storage Transaction. On keeps
Review Changes and the explicit Save to iPod action. Turning the setting off also
applies an existing pending draft.

The Application Layer schedules preparation after the current edit finishes
notifying its observers. An edit during preparation invalidates that candidate and
prepares the latest revision. Device reservations defer writes until available;
disconnects, source changes, cancellation, and shutdown never authorize stale
output. Turning drafting on prevents automatic acceptance of a pending candidate;
an already-started save finishes with its existing verification guarantees.

Only verified success clears the draft. Failed or blocked attempts retain changes
and open the existing diagnostics dialog even while the sidebar button is hidden.
The same failed revision is not automatically retried: the user can correct it,
retry in the dialog, or turn drafting on and off. All modes keep source checks,
signing, staging, recovery journals, and verification in the existing save path.
The separate Sync Workspace and its review-only Sync Plan are unchanged.
