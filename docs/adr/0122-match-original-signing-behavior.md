# ADR-0122: Match Original iOpenPod signing behavior

- Status: Accepted
- Date: 2026-10-06
- Supersedes: ADR-0061's Nano 5 iTunesCDB checksum assignment
- Extends: ADR-0004, ADR-0021, ADR-0061, and ADR-0115

## Context

Original iOpenPod 1.x writes a HASH72 iTunesCDB and HASH72 Locations Checksum
Book for Nano 5. It refreshes a retained HASH72 signature before computing a
Classic's HASH58 signature, because HASH58 covers that HASH72 field. Its Nano 6
and 7 HASHAB writer uses the same `calcHashAB` module and publishes header
scheme 3 after calculating with scheme 4. The current HASH58 and HASHAB
primitives already match that behavior, but the 2.0 Nano 5 profile assigned
HASH58 to iTunesCDB, and its Classic write path left a retained HASH72 field
stale. A recovery helper also normalized the retained database's scheme to 2,
preventing verified recovery from a Classic's scheme-1 dual signature.

## Decision

Nano 5 uses HASH72 for both iTunesCDB and the Locations Checksum Book. A
Classic HASH58 write refreshes a verifiably recoverable retained HASH72
signature under scheme 1 before HASH58. HASH72 recovery hashes the retained
database with its actual scheme. The SHA1/HMAC, AES envelope, and HASHAB WASM
algorithms remain unchanged.

The Application Layer first uses device-bound `HashInfo`. When it is absent,
it may recover material from a verified retained HASH72 database, then from a
Locations Checksum Book whose block hashes match the retained Locations file
and whose full HASH72 envelope verifies. These reads use the Active iPod's
Filesystem Session. The existing device identity, source preconditions,
review, verification, and recoverable Storage Transaction remain required.
Material is never invented or taken from another device.

## Consequences

Previously written HASH58 Nano 5 CDBs without `HashInfo` can still be updated
when their retained checksum book is valid. If no valid retained signing
artifact exists, preparation stops before any device mutation. The signed
checksum book is optional evidence during preparation; it does not become a
Library read authority during selection. Physical firmware acceptance of
newly generated 2.0 artifacts still needs device validation.
