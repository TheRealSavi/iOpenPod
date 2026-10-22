# Nano 6 HASHAB signature evidence

Read-only investigation on 2026-10-22 compared a freshly recovered Apple Nano 6,
an Apple Sync of 19 Tracks, and failing Sync captures from Original iOpenPod and
2.x. The user reported Finder accepting the Apple baseline and rejecting both
iOpenPod outputs. The source snapshots, device identity, and library metadata
remain in private local evidence; this note records the signing result.

## Captured behavior

Every CDB publishes 3 in the two-byte MHBD `hashing_scheme` field at `0x30`.
Its HASHAB envelope occupies 57 bytes at `0xAB`.

| Capture | Published scheme | Signature matches digest scheme 3 | Signature matches digest scheme 4 | Locations Checksum Book |
| --- | ---: | --- | --- | --- |
| Apple recovered | 3 | Yes | No | Valid |
| Apple Sync | 3 | Yes | No | Valid |
| Original iOpenPod | 3 | No | Yes | Valid |
| iOpenPod 2.x | 3 | No | Yes | Valid |

These are exact cryptographic comparisons after accounting for each envelope's
random bytes. They are not conclusions from differing compressed sizes, database
IDs, or signature bytes alone. Both accepted Apple captures have zero HASH58 and
HASH72 fields, so the Nano 5 dual-signature policy is not the missing component.

## Independent envelope reconstruction

The pinned upstream
[calcHashAB implementation](https://github.com/dstaley/hashab/blob/f80d46432204c6238cad7d8ca3b3dd52ea66836b/src/calcHashAB.c)
interleaves 23 input random bytes and 32 computed bytes through `permutation_56`.
The corresponding
[WASM wrapper](https://github.com/dstaley/hashab/blob/f80d46432204c6238cad7d8ca3b3dd52ea66836b/src/wasm.zig)
uses the fixed random sequence `ABCDEFGHIJKLMNOPQRSTUVW`. Apple's captures use
different random sequences, which can be recovered directly from their envelopes.

The diagnostic harness recovered all 23 bytes, supplied them to a fresh private
in-memory instance of the same primitive, and recomputed all 57 bytes. The SHA1
normalization cleared the established excluded MHBD fields and signature slots:
`db_id`, `unk0x32`, `hash58`, `hash72`, and `hashab`. It varied only the scheme
included in the digest. Both Apple signatures match with 3; both iOpenPod
signatures match with 4. Enumeration from 0 through 5 found no alternative match.

This procedure does not fit a signature by choosing arbitrary randomness: all
23 random bytes are read from fixed wire positions, leaving 32 cryptographic
bytes that must still agree. Altering recovered randomness changes the computed
bytes. A changed payload and a wrong GUID both fail validation.

All four Locations Checksum Books also reconstruct exactly with their stored
random parts and the same device GUID. Each book has a 57-byte envelope, a 20-byte
aggregate SHA1, and a sequence of 20-byte SHA1s for 1024-byte Locations blocks.
The complete block list and aggregate match each captured Locations database.
There is no CDB scheme field in this signing input. This excludes the GUID,
primitive, and checksum-book framing as explanations for the CDB mismatch.

## Producer and verifier defect

The previous `sign_hashab` set scheme 4 before calculating SHA1 and changed the
published header to 3 afterward. `verify_hashab` called that same writer and
compared the result. This accepted the incorrect iOpenPod output and rejected
valid Apple envelopes. The latter result also reflected its fixed random part;
it could not by itself distinguish bad normalization from valid randomness.

A diagnostic copy of the 4,114-byte failing v2 CDB with a scheme-3 signature
changes exactly 32 bytes, all within HASHAB. Its random bytes, header outside
HASHAB, and entire compressed body remain unchanged. It validates under the Apple
convention. This local result establishes the signing correction independently
of any codec, Photo, artwork, preference, or SQLite metadata changes.

The repaired contract is recorded in
[ADR-0169](../adr/0169-sign-hashab-with-the-published-scheme.md). Regression coverage
checks fixed expected output independently from sign/verify agreement. The pinned
WASM file is unchanged: the runtime supplies explicit random bytes in a fresh
private instance after checking the expected fixed array occurs uniquely, failing
closed if it is absent or ambiguous. The algorithm and ordinary Locations
Checksum Book output remain unchanged.

## Regression fixtures and actual-capture tests

The portable `nano6-hashab-envelopes.json` fixture uses synthetic CDB bytes and a
synthetic GUID. Its non-default random parts come from the two Apple envelopes;
its expected scheme-3 and rejected legacy scheme-4 signatures are precomputed
through the independently checked upstream primitive. These are capture-derived
regression vectors, not byte-identical Apple CDB excerpts.

An Apple signature covers the protected database content, so anonymizing a full
CDB while retaining its original valid signature is impossible without finding a
cryptographic collision. The actual captures remain private. Opt-in tests use
`IOPENPOD_NANO6_CAPTURES` to read the supplied capture directory and exercise the
real Apple and rejected iOpenPod CDBs in place. Normal portable tests do not depend
on the user's desktop files. The
[iTunesDB fixture guide](../../tests/fixtures/iTunesDB/README.md) records fixture
provenance and test invocation.

## Verification limits

The defect is established by captured bytes. The hypothesis that this defect is
the complete cause of Finder rejection still needs a physical acceptance test.
The captures also contain unrelated metadata discrepancies, which are deliberately
outside this signing change. No source capture or connected device was modified
to produce this evidence.

Unchanged parsing/serialization remains byte-exact. Fixing the signer does not
silently repair a retained CDB during a no-op or SQLite-only refresh; a changed
database reaches the corrected signing path through ordinary reviewed publication.
