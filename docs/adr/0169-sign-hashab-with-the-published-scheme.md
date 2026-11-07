# ADR-0169: Sign HASHAB with the published scheme

- Status: Accepted
- Date: 2026-10-22
- Amends: ADR-0061 and ADR-0122

## Evidence

Two Apple Nano 6 iTunesCDB captures publish scheme 3 and verify exactly when the
normalized SHA1 includes that same scheme. Both failing Original and 2.x captures
publish 3 but verify only when the digest substitutes 4. The existing verifier
regenerates with the same faulty writer and therefore accepts its output.

Apple uses different 23-byte random values in its HASHAB envelopes. Recovering
those bytes through the upstream output permutation permits exact verification
without mistaking a random-envelope difference for corruption. The same GUID
and primitive verify all four Locations Checksum Books, including every block
hash and aggregate hash. See the
[capture evidence](../research/nano6-hashab-signatures-2026-10-22.md).

## Decision

HASHAB CDB publication signs and writes scheme 3. Verification checks the published
scheme and the stored envelope using its recovered random bytes, independently
of the writer's choice of random bytes. A digest made with scheme 4 and a header
published as 3 is invalid. Known root field locations continue to come from the
shared MHBD definition.

Keep the existing HASHAB primitive and device-bound GUID contract. Ordinary
signing retains its established random-byte policy; verification must accept a
valid envelope with other random bytes. The pinned WASM asset stays unchanged;
explicit random material is supplied only to a fresh private runtime instance,
after checking the expected fixed material occurs uniquely. Missing or ambiguous
runtime material fails closed. No dependency or artifact format is added.
The Locations Checksum Book uses the same envelope verification over its aggregate
digest, without a CDB header scheme; ordinary checksum-book output is unchanged.

Apple capture evidence takes precedence over parity with the demonstrated
Original signing defect. Regression expectations include independently established
scheme-3 outputs with recovered Apple random parts, plus wrong-scheme, wrong-GUID,
and corrupted-content rejection. Portable fixtures use synthetic database bytes
and identities under the existing fixture privacy policy. Opt-in local tests
exercise the actual Apple and failing captures without copying them into the
repository. Writer/verifier agreement alone cannot establish compatibility.

## Consequences and limits

Changed HASHAB databases are signed correctly through the existing preparation
and Storage Transaction path. Ordinary no-op serialization still reproduces the
source bytes exactly under ADR-0006. This change does not introduce a separate
repair workflow or authorize discovery-time mutation. SQLite-only regeneration
continues to retain an unchanged CDB; it does not repair an older bad signature.

Nano 5's separate HASH72 behavior remains unchanged. The shared Nano 6/7 HASHAB
path uses the corrected convention, while the direct capture evidence here is
Nano 6. Physical Finder acceptance after the fix still requires a device test.
Codec metadata, PhotosDB authoring, and other capture differences are separate
work and are not part of this decision.
