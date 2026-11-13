# ADR-0253: Preserve native browse links during Track membership edits

> [ADR-0254](0254-reuse-exact-artist-records-during-mixed-edits.md) covers
> Album Artist edits and shared-record splits in the same Library Draft as Adds.
> [ADR-0255](0255-preserve-duplicate-browse-owners-during-track-edits.md) covers
> Artist renames and Album edits involving duplicate native records.

- Status: Accepted
- Date: 2026-11-11
- Amends: ADR-0172 for source Album Artist ownership and duplicate browse records

## Context

Several native Album or artist records can serve one group of Tracks with
matching tags. One name can have two records with the same label. It can also
span a Track Artist record and a record for the effective Album Artist.

A retained iTunes-written nano 7G Library contained a Various Artists record
serving 35 compilation Tracks with 30 distinct Artist tags. The record label
matched the effective Album Artist of every member. Removing a Track from an
affected group invoked artist splitting and failed preparation. Synthetic
fixtures also reproduced rejection on additions and removals with same-name
native IDs for Albums and artists.

## Decision

For membership edits in these groups, preserve the native browse links of
surviving Tracks. Use the Album Artist interpretation for a source artist record
when its label matches the effective Album Artist of all its members and at
least one Track has a different Artist. Apply this preservation while the
retained members keep their browse identity tags. ADR-0172 still governs
explicit retagging and incompatible shared records.

Resolve incoming Tracks using the retained native Album and its artist links
when that context applies. With compatible records of the same label, prefer
the one with the most surviving members in the requested group, then the
lowest native ID. Report that choice as a warning. For duplicate Album records,
compare their browse metadata and known Store Album IDs before selecting a
destination. Preserve separate Podcast ownership under ADR-0165.

When a removed Track was a native Album's representative, use the lowest
surviving persistent Track ID in that Album, or zero if none survives. Preserve
other bytes of the record. Verification checks each planned Track link in the
reparsed database and compares retained records with the source, accounting
for the allowed representative change. Album and artist SQLite PIDs remain
projection-local.

## Validation

Public preparation tests cover Album and artist addition, majority and tie
selection, surviving duplicate owners, representative repair, and Album
Artist links. Replay against the retained nano 7G capture prepared both
removals with the captured SQLite companions and preserved all 831 surviving
Tracks' native Album and artist IDs.
