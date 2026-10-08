# ADR-0134: Verify unconfirmed durability before recovery cleanup

- Status: Accepted
- Date: 2026-10-08
- Amends: ADR-0093
- Extends: ADR-0029

## Context

The artwork Sync audit reproduced a Storage Transaction recording COMMITTED after
an unsuccessful Volume flush. After reconnecting, a later successful flush could
authorize deleting originals even when a published file had not survived intact.
Restoration has the analogous cleanup risk.

Requiring a successful Volume flush before ordinary publication would prevent
unelevated Windows users from syncing: Windows requires administrative privileges
for a writable Volume handle. File writes already require their own flush and
`fsync`; those operations and a privileged Volume-wide flush are different facts.
See the [research](../research/artwork-sync-loss-2026-10-08.md).

## Decision

Ordinary execution and restoration retain their warning behavior when a Volume
flush is unavailable. The Operation Journal records whether the verified result
crossed a successful preterminal durability barrier. A failed barrier is never
reported as confirmed durability.
Version 3 stores `content_durability_confirmed` as a strict boolean; versions 1
and 2 remain readable and default to unconfirmed.

Confirmed terminal journals retain the established cleanup path. Unconfirmed
terminal journals, including older journals without this evidence, require a
later successful Volume flush and fresh verification of the recorded result and
dependencies before cleanup can delete originals. This applies both to direct
finalization and the committed/restored convenience operations. A mismatch keeps
the recovery namespace intact.

Restoration resets prior confirmation until its own result crosses a successful
barrier. A failed final terminal-marker flush does not erase already established
content durability. External transactions retain their existing strict barriers.

## Consequences

Normal Windows publication does not gain an elevation requirement. Unavailable
Volume flushing still produces a warning and retains recovery files until cleanup
can establish the required evidence. Only unconfirmed or legacy transactions pay
for fresh result verification; confirmed transactions do not rehash all media.

This does not override concurrent-edit protection or automatically overwrite a
file matching neither recorded version. Tests use virtual Volume failures and
reconnects; they do not establish a controller's physical persistence guarantees.
