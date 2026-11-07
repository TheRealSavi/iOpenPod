# ADR-0212: Share Host staging ownership across workspaces

- Status: Accepted
- Date: 2026-10-30
- Extends: ADR-0117
- Supersedes: ADR-0117's lifetime owner lock per workspace

## Context

[Issue 295](https://github.com/TheRealSavi/iOpenPod/issues/295) reports Windows
file-descriptor exhaustion during large Syncs. Sync intentionally retains all
prepared media until publication, but each media workspace also retained an open
ownership marker. A Windows reproduction retaining 10,000 empty media workspaces
failed at 8,188 with the reported `.iopenpod-owner` error. This requires neither
media decoding nor a device: retained ownership alone exhausts descriptors.

## Decision

Storage shares one OS-held ownership lease per process and resolved staging root.
Each workspace retains its separate context and cleanup lifetime. Reference counts
keep the lease until the last workspace exits. Creation, reference changes, normal
removal, and startup cleanup remain serialized by the root cleanup guard. The
process identity prevents new work in a fork from adopting its parent's owner.

Version-2 workspace markers reference a random process-owner filename in the same
private root. Cleanup accepts only the exact filename grammar and process-marker
content, ordinary files with one link and the current user where applicable, and
an available OS lock. Missing or malformed owners grant no cleanup authority.
Version-1 workspace markers remain recoverable through their original marker lock.
Older versions reject the new marker rather than treating live work as abandoned.

Normal cleanup removes each workspace before releasing its owner reference. An
unlocked owner record remains whenever workspaces remain, so failed directory
removal can be retried. Startup cleanup still removes only marked, flat directories
without following links or unexpected children. Idle process-owner records are
reclaimed once no workspace remains. Their names alone never authorize deletion.

Sync logs the first five Track preparation failures with their underlying errors,
then a total and omitted count. Library analysis, resources, and preparation DEBUG
logs retain counts and samples of at most twelve records and fields per collection,
with omitted counts. Complete issues remain in the Sync result. Routine validation
must not replace the rotating log's entire history with per-Track field dumps.

## Consequences

Staging ownership consumes a bounded number of descriptors independently of batch
size. Prepared files still require Host space proportional to the complete batch;
the selected temporary-volume policy, media verification, and device transaction
are unchanged. No dependency or product setting is added.

The new marker depends on its sibling owner record; absent evidence leaves files
untouched. An unsafe remaining workspace can delay removal of small idle owner
records. Non-contention lock errors preserve the operating-system failure instead
of claiming another iOpenPod process holds the resource.

Windows checks retain 10,000 workspaces successfully after the change. Regression
coverage includes concurrent preparation, overlapping lifetimes, another process's
live work, process crashes, legacy markers, malformed owners, and cleanup retry.
A complete NAS-backed, transcoding Sync to a physical iPod remains unverified.
