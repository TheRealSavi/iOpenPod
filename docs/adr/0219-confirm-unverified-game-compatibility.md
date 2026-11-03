# ADR-0219: Confirm unverified game compatibility

- Status: Accepted
- Date: 2026-10-31

At the user's request, a family or firmware mismatch warns instead of disabling
Install Games. Before preparation, show the actual reported values and offer Cancel
or Continue anyway. This supersedes ADR-0208's requirement for a verified release
as a prerequisite to every game publication; it does not expand verified support.

The Application Layer captures the reviewed identity values, model, and codec
choice. A single known reported family takes precedence. For absent, ambiguous,
or unknown family evidence, use the codec for the identified Video, Classic, or
nano model and disclose that fallback. Existing equivalent codec groups make a
representative family sufficient; no new cryptographic format is inferred.
Device metadata is never rewritten to claim the inferred family.

Carry the confirmation through authorization and selected-game installation,
but recheck the live values before each publication. It is scoped to the Active
iPod connection and cleared on a device change; a new preparation asks again.
Cancel, Escape, and dialog dismissal start no work. Read-only volumes, ongoing
operations, recovery, GUID checks, codec validation, and recoverable Storage
publication remain mandatory. Synthetic end-to-end tests cover both buttons,
confirmation, cancellation, model fallback, and changed identity before writes;
physical game-launch acceptance remains separate.
