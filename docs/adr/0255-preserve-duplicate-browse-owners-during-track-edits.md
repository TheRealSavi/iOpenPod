# ADR-0255: Preserve duplicate browse owners during Track edits

> [ADR-0256](0256-resolve-duplicate-album-destinations-by-release.md) refines
> compatibility and release selection for joining Tracks.

- Status: Accepted
- Date: 2026-11-12
- Amends: ADR-0253 and ADR-0254

An Artist rename or Album edit can change group membership without adding or
deleting a Track. Affected groups can have several native records even when
those records agree about ownership.

When every candidate artist record has the exact name of the requested
Artist, preserve the links of Tracks that stay in the group. Tracks joining
that group use the record with the most surviving members, then the lowest
native ID. Keep the shared-record split and Album Artist rules in ADR-0253
and ADR-0254 for groups whose source evidence requires them.

An Album edit retains the links of Tracks that stay in their group when each
candidate native record exists exactly once and belongs to that source group.
Derive Sort Album Artist and feed changes from the continuing members of each
native record, in Library order. Update that record's affected text fields
and preserve its other metadata, SQL ID, and Unknown Data. Assign a joining
Track only when the candidate records have compatible browse metadata and
known Store Album IDs across their source members and all Tracks that join.
Use the same selection and warning rules as an Add. Podcast ownership retains
the rules of ADR-0165.

When a representative Track moves to a different native Album, choose the
lowest surviving persistent Track ID in its former Album, or zero if it is
empty. Verify the resulting links and compare retained Album Items with the
source bytes plus the authorized text and representative changes.
