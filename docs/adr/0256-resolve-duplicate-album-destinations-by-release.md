# ADR-0256: Resolve duplicate Album destinations by release

> [ADR-0257](0257-continue-writes-after-browse-id-conflicts.md) supersedes
> blocking on destination ambiguity.

- Status: Accepted
- Date: 2026-11-12
- Amends: ADR-0253 and ADR-0255

Changing Sort Album Artist on one of two native Album records previously made
the same Add succeed in a combined write and fail after saving the sort edit.
Comparing all candidate Store Album IDs together also blocked a Track with a
known release even when one native record matched it exactly.

Use the same destination policy for an Add and for a Track moving into a group
with multiple native Album IDs. Check title, Album Artist, content type,
compilation, show, and season against each record. Use feed evidence where it
exists. Sort text and Album ratings remain record-local display metadata.
Preserve existing links and apply authorized Album text edits to the owning
record as specified in ADR-0255.

Read Store Album IDs from the source members of each candidate and from any
joining Track retained in the source Library. A candidate with known release
evidence can receive a Track from that release if its members agree on the ID.
When all eligible candidates identify just one release, a joining Track without
a Store Album ID can use a record with that evidence. If multiple known releases
remain plausible for that Track, block preparation and report the candidate
IDs. A batch can place Tracks into separate records that identify their
respective releases. If no candidate has release evidence, accept at most one
known release across the joining Tracks. Prefer the eligible record with the
most surviving members, then the lowest native ID. Keep the warning when several
eligible records remain. Podcast Album ownership follows ADR-0165.

Public Library preparation tests cover one-write and two-write sort edits,
matching and conflicting Store Album IDs, distinct releases joining together,
and Adds without release evidence.
