# ADR-0182: Verify Host transaction outputs once before commit

- Status: Accepted
- Date: 2026-10-24
- Amends: ADR-0167 and ADR-0181

## Context

Host transactions read every published file immediately after its atomic write,
then read the entire output set again before commit. On USB 2.0 iPods this doubles
destination verification traffic. Hashing during copying already checks that the
outgoing bytes match the planned content, but does not independently verify the
destination. The user requested removal of redundant reads while retaining safe
Sync and recoverability.

## Decision

Host transaction publication and restoration defer their individual destination
readbacks to the existing final transaction verification. Each copy still hashes
the outgoing stream, compares its size and SHA-256 with the planned content, checks
source stability, flushes its staged file, and publishes by atomic replacement.
Requested modification times are still set on the private stage.

The private deferred publication path returns no verified fingerprint. The final
transaction check reads every resulting file once, verifies content and requested
timestamps, verifies removals and dependencies, and supplies the verified
fingerprints. Only then may flushing and the terminal journal transition proceed.
The writer lease and connection checks span the operation. Host recovery copies
remain available through verification and commit.

Standalone writes, journal writes, and other transaction policies retain their
immediate readback contract. Independent recovery inspection continues to require
fresh observations. Confirmed terminal cleanup continues to reuse durability
evidence under ADR-0180.

## Consequences

New and replacement Sync files require one complete destination read instead of
two, including files with preserved timestamps. Restoration also removes its
duplicate immediate readback. This halves output verification bytes; it does not
promise to halve total Sync time. Copying and unrelated preparation still take time.

Destination corruption can be detected later in the batch, after subsequent files
have been published. The transaction remains nonterminal and recoverable until all
outputs pass verification. Edits preserving file size and modification time still
fail the final content check.

Hashing only the outgoing stream would remove all destination verification, but
could not establish that the destination returns the expected bytes. That policy
is not adopted. The single remaining read uses normal filesystem semantics; it
does not independently bypass OS caches or prove physical-media integrity. The
existing flush contract establishes the reported durability.

## Validation

Virtual-Volume tests count one destination read per newly published file with and
without timestamp overrides. Fault tests corrupt a published file during execution
and restoration, including size- and timestamp-preserving edits, and verify that
the journal remains nonterminal with original recovery material retained. Tests
also change a Host input after preparation to exercise the streaming digest,
restore from that interruption, and confirm standalone atomic writes still reject
corruption before returning. Existing disconnect tests cover publication and
restoration mutation boundaries.
