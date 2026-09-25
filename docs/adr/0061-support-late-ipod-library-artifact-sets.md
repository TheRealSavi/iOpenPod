# ADR-0061: Support late-iPod Library artifact sets

- Status: Accepted
- Date: 2026-09-16
- Extends: ADR-0006, ADR-0019, ADR-0021, ADR-0029, and ADR-0033
- Supersedes: the compressed-database and SQLite-companion blockers in ADR-0021

## Context

Fifth-, sixth-, and seventh-generation iPod nano devices do not consume one plain
`iTunesDB`. They retain an `iTunesCDB` whose child bytes are zlib-compressed and a
firmware-facing SQLite Library consisting of five databases and a Locations checksum
book. The artifacts have different checksum requirements: Nano 5 uses HASH58 for the
CDB and HASH72 for the checksum book, while Nano 6 and 7 use HASHAB. Treating one
profile checksum as applying uniformly to every artifact either blocks supported
devices or generates invalid output.

The common Library API and reviewed Storage Transaction are already the authority
for editing and publication. Adding a parallel late-device workflow would duplicate
semantic reconciliation and weaken the all-or-nothing safety model.

## Decision

- iTunesCDB is a physical framing codec around the one definition-driven iTunesDB
  parser and writer. The root header stays uncompressed, the child extent is a
  bounded zlib stream, and signing occurs over the final physical bytes.
- `IPodLibrary` retains exact physical CDB bytes for no-op output. iTunesCDB is the
  sole readable Library authority; selection does not read or reconcile SQLite
  firmware state.
- `iPodDB.SQLiteDB` generates and validates `Library.itdb`, `Locations.itdb`,
  `Dynamic.itdb`, `Extras.itdb`, `Genius.itdb`, and `Locations.itdb.cbk` as one
  coherent projection from the independently checked CDB Library Snapshot. It does
  not know device paths, perform persistence, or expose a SQLite read projection.
- Device Registry declares the binary checksum, SQLite checksum, and whether
  device-supplied SQLite postprocessing is required independently. The Application
  Layer obtains device-bound FireWire GUID or typed HashInfo material, selects the
  profile-required primary database, and captures existing SQLite paths as write
  preconditions only when a CDB-changing save will replace them.
- HASH58 is implemented directly. HASH72 uses PyCryptodome's maintained AES
  primitive for its CBC envelope rather than carrying a private AES implementation.
  HASHAB runs the clean-room, public-domain `calcHashAB` WebAssembly module through
  Wasmtime. Device-provided
  SQLite postprocess SQL from SysInfoExtended runs only against the generated,
  in-memory database group before validation and serialization. Each named command
  retains the multi-statement semantics of SQLite's `sqlite3_exec` contract.
- Storage publishes the primary CDB, the complete generated SQLite set, the checksum
  book, and the empty iTunesDB compatibility file in the same staged, verified,
  recoverable transaction as other Library artifacts.

## Consequences

Late Nano devices use the same common Library Draft, review, and recovery workflow
as plain-iTunesDB devices. Missing or damaged SQLite companions do not block
selection because the CDB is sufficient to load the Library. A changed SQLite
precondition, absent signing identity, missing required or malformed postprocess
command set, failed signature, or failed reparse blocks publication before device
mutation. The exact SysInfoExtended bytes used to select those commands are a
reviewed file precondition and must still match at publication. Profiles without an
evidenced requirement may retain an empty command set.

SQLite is a firmware projection, not a new application domain model or persistence
authority. The application must keep the complete artifact generation together and
must not update only one companion. Firmware-side SQLite-only changes are
deliberately ignored and are replaced from CDB on the next CDB-changing save. HASH72
adds PyCryptodome's platform wheel or source-build dependency in exchange for an
audited AES implementation. HASHAB adds a Wasmtime runtime dependency and a
versioned public-domain WebAssembly asset. Signed ArtworkDB remains outside this
decision.
