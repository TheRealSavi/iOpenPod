# ADR-0254: Reuse exact artist records during mixed edits

> [ADR-0257](0257-continue-writes-after-browse-id-conflicts.md) defines fresh
> IDs for splits where exact-name source records are unavailable.

- Status: Accepted
- Date: 2026-11-12
- Amends: ADR-0172 and ADR-0253

An Add can share one Library Draft with an Album Artist edit or with the split
of a native artist record shared by distinct Artists. Both combinations could
block preparation when one Artist had multiple native records.

When a retained Track's Artist stays the same and its native artist record
matches that exact name, an Album Artist edit preserves the artist reference.
A reference whose label establishes Album Artist ownership still depends on
the effective Album Artist under ADR-0253.

When splitting a shared artist record, a group with multiple source IDs can
reuse an exact-name record from its own source group. Each candidate ID must
resolve to one source record, and the split applies to Track Artist ownership.
Preserve surviving exact-name links and select a destination for the other
Tracks using the most surviving members, then the lowest native ID. Warn when
choosing between compatible records. Other affected Artists continue through
the shared-record split policy. Preserve the source records and their Unknown
Data. A split with multiple candidates and no exact-name record remains
blocked because the source provides no unique record to clone.

Public Library preparation tests cover Adds with Album Artist changes and
shared-record splits, including rejection when none of the source labels
matches. Verification checks the planned artist links and retained bytes.
