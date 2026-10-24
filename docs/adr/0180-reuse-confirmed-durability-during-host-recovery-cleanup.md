# ADR-0180: Reuse confirmed durability during Host recovery cleanup

- Status: Accepted
- Date: 2026-10-24
- Amends: ADR-0167's terminal cleanup verification
- Extends: ADR-0093 and ADR-0134

## Context

A live Sync spent over 820 seconds in Clean up recovery files. Its committed
Operation Journal described 353 changed files totaling 8.84 GB and already recorded
confirmed content durability. Host recovery cleanup nevertheless called recovery
inspection, which read every result and dependency twice, then finalization read
them all again. About 26.5 GB of device reads followed successful publication.

ADR-0167 required verification during terminal cleanup, even though publication
and restoration already verify the complete result before their durability barrier.
This bypassed the confirmed-content fast path established by ADR-0093 and ADR-0134.

## Decision

Host recovery uses the persisted content durability evidence for terminal cleanup,
as device-retained recovery already does. A confirmed committed or restored
transaction requires no additional media or dependency content reads. The terminal
convenience methods capture the validated journal observation directly; they do not
call the full inspection required for restoration.

Cleanup still requires the exact Physical Device and Volume identities, terminal
state, unchanged journal fingerprint, matching Host/device intent when both
journals exist, writer lease, validated paths, and a successful Volume flush.
Unconfirmed transactions require one fresh verification pass over the expected
result and dependencies after that successful flush. A failed flush or mismatched
result retains recovery material. Restoration retains its full content checks.

Device recovery namespace removal is flushed before Host originals are removed.
Host cleanup flushes its own directory; it does not require another device flush
after making no further device changes. The Host journal permits retry when device
namespace deletion succeeded but its flush did not.

## Consequences

Confirmed cleanup cost depends on journals, recovery-file deletion, and flushes,
rather than the size of newly published media. It does not serve as a later scrub
for corruption or unrelated edits after an already verified durable commit. It
never rewrites current Library or media contents. Unconfirmed durability still
requires evidence that the expected result survived before originals are discarded.

Tests measure zero content reads for confirmed cleanup and exactly one read per
present result/dependency for unconfirmed cleanup, including committed/restored
states, direct/convenience calls, and reconnection. They also cover corrupt or
unexpectedly present results, changed dependencies, stale observations, and flush
failure with retry from the Host journal. Virtual Volume tests establish the read
budget and failure behavior, not physical-device timing or persistence guarantees.
