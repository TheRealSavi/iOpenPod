# ADR-0208: Prepare game authorizations with a standalone codec

- Status: Accepted
- Date: 2026-10-30

The research transfer tool executes stock ARM firmware to authenticate and
convert IC-Info.sidb. Shipping firmware images and an emulator would make that
research harness an application dependency. Instead, iPodDB owns a standalone
byte codec using reconstructed algorithms and bounded cryptographic tables.
Firmware execution remains an offline differential verification tool in the lab.

The Application Layer owns the supplied Classic 6.5 authorization resource and
its source GUID. It passes those bytes and the qualified destination identity to
iPodDB. The codec does not discover devices, import Storage, invoke Ghidra, or
persist files. No new runtime dependency is required beyond existing PyCryptodome.

Games is an explicit Library sidebar action on the Active iPod. Device Registry
evidence must identify a supported updater family and evidenced RetailOS release.
iOpenPod captures current identity metadata and the existing authorization file,
then publishes prepared bytes through a recoverable Storage Transaction. A
corrupt existing file is an error, never permission to initialize a replacement.

Merge identity is the account selector together with the key selector. Identical
entries are retained once; different selectors remain independently addressable
even when their values match. The bundled entry wins a conflicting selector, as
requested. Destination-only records and Unknown Data are preserved. Shared
accounts retain their destination session: imported values must be reencrypted
under that session before merging, since unequal RSA ciphertext does not establish
unequal session material. Unsupported account-version combinations fail before
publication. An unchanged merge returns the original envelope bytes.

The action updates authorizations only. Installing game executables is separate.
Type 2 remains an opaque device-bound value, with no claim to a recovered final
content key. The codec must preserve its established session relationship.

See [IC-Info and Games](../ipod-games.md) for the implementation contract and
validation evidence.
