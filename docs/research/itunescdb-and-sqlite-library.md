# iTunesCDB and SQLite Library format evidence

This note records the external evidence used for ADR-0061. Original iOpenPod was
used as the local behavioral baseline; the format was corroborated against libgpod
and the independent HASHAB clean-room implementation.

## iTunesCDB

libgpod's format overview describes iTunesCDB as the preferred database when both
files exist and distinguishes the checksum required by each device generation:

- <https://github.com/fadingred/libgpod/blob/master/README.overview>
- <https://sources.debian.org/src/libgpod/0.8.3-17/src/itdb_zlib.c/>

The root `mhbd` header remains uncompressed. Bytes after its declared header extent
form one zlib stream. The physical root extent is the compressed byte count, the
runtime compression flag at `0xA8` is set, and zlib level 1 matches libgpod/iTunes.
The checksum is calculated after compression because firmware verifies the physical
artifact.

## SQLite companion set

libgpod's SQLite implementation and schema queries establish the six-artifact set,
the 1024-byte SHA1 block checksum book, Core Data timestamps, signed checksum-book
header, and SysInfoExtended postprocess command contract:

- <https://github.com/gtkpod/libgpod/blob/master/README.sqlite>
- <https://sources.debian.org/src/libgpod/0.8.3-17/src/itdb_sqlite.c/>
- <https://sources.debian.org/src/libgpod/0.8.3-17/src/itdb_sqlite_queries.h/>

The databases are `Library.itdb`, `Locations.itdb`, `Dynamic.itdb`, `Extras.itdb`,
and `Genius.itdb`; `Locations.itdb.cbk` covers the Locations database. The highest
numbered `UserVersionCommandSets` entry selects ordered command names from
`SQLCommands`. Commands execute with the other four databases attached to
`Library.itdb` and with the `iPhoneSortKey` and `iPhoneSortSection` functions
available. Libgpod passes each selected command string to `sqlite3_exec`, so one
named command may contain multiple SQL statements.

A historical, observed `com.apple.mobile.iTunes` value documents the same command
dictionary and versioned command-set shape, including the real
`CreateItemArtistIndex` statement retained as a sanitized test fixture:

- <https://github.com/cipi1965/MobileDeviceAccess/blob/master/deviceValueForDomain.md>

## HASH72 and HASHAB

libgpod's HASH72 code establishes the AES-CBC envelope and recoverable device IV;
the device's `HashInfo` record supplies its 12 random bytes and 16-byte IV. HASHAB
uses a 57-byte result at root offset `0xAB` for Nano 6 and 7.

- <https://sources.debian.org/src/libgpod/0.8.3-17/src/itdb_hash72.c/>
- <https://github.com/dstaley/hashab>

The bundled `calcHashAB` asset is pinned to upstream commit
`f80d46432204c6238cad7d8ca3b3dd52ea66836b` and checked against upstream's published
test vector. Its adjacent notice records the Unlicense grant.

Read-only checks against physical Nano 5 and Nano 7 captures additionally established
that both CDBs parse and reproduce byte-for-byte, both semantic snapshots generate
five SQLite databases that pass SQLite `quick_check`, and both generated checksum
books verify with their device-generation algorithm. The Nano 7 capture also exposed
two details now covered by tests: distinct artist names can reuse one native artist
reference and therefore require deterministic collision-free projection IDs, and an
iTunes-written HASHAB CDB publishes `hashing_scheme = 3` even though the HASHAB digest
normalization uses discriminator 4.

## Album ordering without device postprocessing

The previous v2.0.4 SQLite generator assigned every album `name_order = sort_order = 100`
and omitted `item.album_order`. Nano 6 and 7 profiles allow generation without
device postprocess commands, so nothing subsequently supplied these browse ranks.
A two-album generation with lower persistent ID for `Zimbo Trio` than `Blink 182`
therefore returns Z before B when ordered by album rank and persistent ID.
This reproduces the missing ordering information behind a Nano 7 report; it does
not establish the firmware's exact tie-breaking query.

The locally retained `orig_nano7` Library.itdb has 234 albums with 222 distinct
name ranks and 220 distinct sort ranks. Its album browse indexes use `sort_order`.
The captured order places numeric album names after letters and an unknown album
last; it also distinguishes display-name ranks from explicit Sort Album ranks.
Original iOpenPod independently computes ranks in steps of 100 and strips leading
English articles for default sort names. It is a compatibility reference, not a
firmware oracle.

Generation now fills album name ranks, album sort ranks, and each Track's album
rank before device postprocessing. Default names strip `A`, `An`, or `The`;
explicit Sort Album values remain authoritative. Equivalent case-folded names
share ranks, numeric names follow letters, and empty names follow known names.
Album rows take the first member's effective sort name, consistent with the
existing snapshot-order group projection; each Track retains its own effective
sort name. Conflicting tags within one album and full locale-specific collation
are not resolved by this fallback. Device postprocess commands may replace the
generated values. Track physical order, identities, and CDB metadata are unchanged.

Regression tests cover the reported B/Z pair in both input orders, separate artists,
Sort Album overrides, article/case handling, numeric/empty names, and subsequent
device postprocessing. These are serialized-database checks, not physical firmware
validation. Existing SQLite artifacts are replaced on the next CDB-changing save
under ADR-0061; a no-op Sync does not regenerate them.
