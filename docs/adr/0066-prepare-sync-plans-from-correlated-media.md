# ADR-0066: Prepare Sync Plans from correlated media

- Status: Accepted
- Date: 2026-09-18
- Extends: ADR-0005, ADR-0025, ADR-0063, and ADR-0065

## Context

A completed Host Media Scan and iPod Media Scan provide both Library records and
source-specific matching evidence. Sync needs to turn that evidence into a simple,
reviewable account of what exists only on the Host, only on the Active iPod, or on
both. For a previously synced item, it also needs to determine whether the Host
source has changed since the successful Sync that produced the iPod copy.

Raw Host and device file sizes cannot be compared directly. A compatible iPod copy
may have been transcoded, so its container size and modification time can
legitimately differ from its Host source. Duplicate fingerprints and failed media
inspection also make an arbitrary one-to-one match unsafe, especially when the
result could authorize removal.

## Decision

After both scans complete, the Application Layer prepares an immutable, review-only
Sync Plan for Tracks and full-resolution Photos. Plan preparation performs no file
copy, Library Draft edit, database serialization, or device mutation.

Previously proven relationships are correlated first by the Host path hint retained
in Sync Details. This lets changed content at the same Host path remain associated
with the iPod item it previously produced. Remaining Tracks correlate by Acoustic
Fingerprint, and remaining full-resolution Photos correlate by exact Image Content
Fingerprint. A matching key must identify exactly one item on each side. Missing or
ambiguous identities become **Needs attention** items and receive no device action
in the comparison. An explicitly selected Host-only Track whose only problem is a
missing identity may derive an **Add** action, because adding a new Host source does
not require a safe Host-to-iPod correlation. Ambiguous and conflicting correlations
remain non-actionable.

Each safe correlation produces one of these results:

- A Host-only item is planned to be **Added** to the iPod.
- An iPod-only item is planned to be **Removed** from the iPod.
- A matched item with Sync Details compares the current Host size and modification
  time with the Host facts recorded by the last successful Sync. A difference in
  either value is planned as **Update**; matching facts are **In sync**.
- A unique content match without Sync Details is **In sync** for this plan. The scan
  does not invent successful-Sync provenance.
- Matching prior Host facts paired with a conflicting content identity is **Needs
  attention**, not silently unchanged.

The GUI opens a dedicated Sync Plan page after preparation. A virtualized Qt table
shows Plan, Type, Item, Host source, iPod source, and reason columns. A compact
summary reports Add, Update, Remove, and Already in sync counts. The default filter
shows planned changes and attention items; users can inspect all items, one action,
Tracks or Photos, and search the complete plan. The page states explicitly that it
is read-only. Changing the Active iPod invalidates the plan.

## Consequences

The first Sync Plan is easy to inspect without implying that Sync execution already
exists. Transcoded files are not repeatedly updated merely because their device
bytes differ from their Host bytes. Changed Host content at a proven path becomes an
Update instead of an unrelated Add plus Remove.

Acoustic Fingerprints remain content-correlation evidence rather than exact Track
file hashes. Duplicate media, missing fingerprints, Photos without retained
full-resolution files, Playlist reconciliation, artwork comparison, metadata
selection, plan editing, and execution require later policy. Plan preparation does
not weaken the analyze, plan, validate, execute, verify, commit, and cleanup phases
required for a future Sync transaction.

A deliberately selected Host-only Track may still be executed as a one-way Add
when no Acoustic Fingerprint is available. The committed Track remains valid, but
the non-authoritative Library Sync Helper omits provenance that cannot be represented
as matching evidence; a later comparison therefore requires explicit review again.
