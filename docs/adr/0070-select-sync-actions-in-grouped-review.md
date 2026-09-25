# ADR-0070: Select Sync actions in grouped Review

- Status: Accepted
- Date: 2026-09-24
- Extends: ADR-0067
- Supersedes: the flat Review table presentation in ADR-0066

Sync Review follows the Original iOpenPod's collapsible change groups, with counts,
group and item checkboxes, and persistent selection and expansion actions. Groups
come only from supported Sync Plan actions: Track and Photo additions, removals,
and file updates, plus non-actionable Needs attention and In sync items. Expanded
groups use bounded, virtualized tables. Search and media/action filters remain
available; group selection applies to matching items, while Select All and Select
None apply to all reviewable changes, including those hidden by filters.

Sync Selection owns final action exclusions separately from desired Host membership.
Unchecking an Update skips that update; it must not deselect its Host item and thereby
request removal. Excluded actions stay in Review so they can be selected again.
iPod-only removals still start unchecked. Attention and unchanged items never become
checkable. Returning to Select Media preserves exclusions for identical actions;
changing an item's proposed action drops its previous exclusion. A new scan or
Active iPod clears all choices. The immutable comparison remains unchanged.

The final selected Sync Plan drives both counts and the existing storage estimate.
These choices do not authorize writes, and Sync Selected stays disabled until the
separate execution workflow exists. Playlist, rating, and metadata-only groups are
not inferred from the Original interface before their planning policies exist.
