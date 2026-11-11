# ADR-0253: Reuse an existing native browse record when a name has duplicates

- Status: Accepted
- Date: 2026-11-11
- Amends: ADR-0172 for same-name duplicate native browse records

## Context

ADR-0172 treats multiple candidate source records for one exact name as a
preparation blocker, because such a condition does not identify the one record to
preserve and clone.

Older desktop iTunes builds could leave exactly that state behind: two or more
native Album or artist records carrying the same name, each owning a subset of the
Tracks. The members are then not a source-identity conflict — the name identifies
one browse group, and every member already belongs to a retained record. Adding a
Track to such a group needs no clone and no new identity, yet preparation refused
the whole write, so an affected Library could not accept new music at all.

## Decision

When a changed Album or artist group has several retained candidate records and
the edit does not split the group by name, keep the candidate that owns the most
surviving members of the group and relink the group's members to it. Equal overlap
resolves to the lowest native ID, so the choice is deterministic.

The selection is reported as `library.ambiguous_group` with `WARNING` severity:
nothing downstream knows which record the user meant, so the outcome stays
visible in the Sync report instead of being silent.

Independent verification accepts any retained candidate identity for such a group,
because the writer may legitimately keep any of the existing records. It still
rejects an identity outside the candidate set, and still rejects a group that
borrows or invents an ID.

## What still blocks preparation

- An artist-name change that splits one shared record across distinct exact names
  (ADR-0172's clone path), including missing or repeated native IDs.
- A changed native browse record shared by incompatible groups.
- A retained group whose chosen owner appears more than once in the dataset.
- Missing records, where no candidate exists at all.

## Consequences

- Adding media to a Library that carries same-name duplicate browse records
  succeeds, and the chosen owner is observable.
- The stale duplicate record is preserved unmodified and stays unreferenced by the
  new members; the writer already keeps unreferenced records.
- Two Libraries in the same state can converge on different owner choices if their
  overlap differs. That is accepted: the records are equivalent by name, and the
  choice is deterministic within one Library.
