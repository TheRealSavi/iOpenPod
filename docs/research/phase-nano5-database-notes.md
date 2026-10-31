# Phase on nano 5: database evidence

Research date: 2026-10-30. This bounded note inventories the nano 5 database
representation independently of the Classic Phase SDK investigation. It records
firmware literals, captured database relationships, and present application code.
It does not claim that a physical nano 5 played a custom Phase song.

## Exact firmware and mapping

The inspected firmware is nano 5 RetailOS **1.0.2 / 34A20020**. Its decrypted
`osos.raw.bin` SHA-256 is
`dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49`.
The independently inspected `osos.dram.bin` is 7,095,208 bytes, SHA-256
`841239b40db45c10b71e09b5a1d9b3c3107f1a6e0de0e77120a12ce02ec2e408`.
Its first byte maps to runtime `0x08000000`; the original raw-image DRAM bytes
start at file offset `0x2e27c`. The startup copy also appends initialized data
and establishes separate SRAM regions. See the
[runtime map](../../../ipod-firmware-lab/Nano5FW/notes/classic-to-nano-transfer.md#runtime-map-correction).

## Firmware SQL literals

These exact SQL strings are present in the initialized DRAM image. Their presence
establishes native format vocabulary; SDK-to-query reachability must come from
the separate function and call-graph investigation.

| Runtime address | Query and significance |
| --- | --- |
| `0x08432910` | `SELECT pid, primary_container_pid, audio_language, subtitle_language FROM db_info;` — database identity and primary container |
| `0x08432964` | `SELECT item_pid FROM item_to_container WHERE container_pid = ?1 ORDER BY physical_order;` — ordered Playlist membership references Track PIDs |
| `0x084329c0` | `SELECT pid,media_kind,is_compilation,artwork_cache_id,total_time_ms,album_pid,artist_pid,track_artist_pid,title,exclude_from_shuffle,(CASE sort_title WHEN title THEN NULL ELSE sort_title END),has_lyrics  FROM item;` — Track identity, media kind, duration, and title |
| `0x084333a0` | Begins `SELECT container.pid,distinguished_kind,name,parent_pid,media_kinds,is_hidden,smart_is_folder,smart_is_dynamic,smart_is_filtered,smart_is_genius,...` and joins `container_ui` by container PID — Playlist identity, classification, title, and presentation |
| `0x0853ce8a` | Begins `SELECT pid, media_kind, is_song, is_audio_book, is_music_video,...` and ends `FROM item WHERE pid=?1;` — per-Track metadata keyed by PID |

`Library.itdb`, `Dynamic.itdb`, `Extras.itdb`, `Genius.itdb`, and `Locations.itdb`
path literals all occur below `iPod_Control/iTunes/iTunes Library.itlp/`.
The `container.pid` and `item.pid` columns are therefore the obvious candidates
for the SDK's persistent identities. The capture checks below independently
establish their correspondence with binary database persistent IDs, rather than
assuming that ordinary 32-bit Track IDs are interchangeable with them.

## Read-only capture cross-check

Three retained nano 5 captures were checked beneath
`C:/Users/JohnG/Coding/ipods/nano5/`. SQLite bytes were deserialized into in-memory
connections, and their companion iTunesCDBs were decompressed and parsed using
the existing iPodDB codecs. No capture file was opened for writing.

| Capture | Track count | SQLite `item.pid` equals MHIT `db_track_id` set | Every SQLite `container.pid` exists among MHYP Playlist IDs | Observed distinguished kinds |
| --- | --- | --- | --- | --- |
| `MINE` | 51 | Yes | Yes | 0: two containers |
| `USER2` | 4 | Yes | Yes | 0: one container; 11: one container |
| `USERS` | 4 | Yes | Yes | 0: one container; 11: one container |

For comparison, SQLite integers were interpreted modulo `2^64`, preserving all
64 identifier bits even when SQLite presents a negative signed integer. All
three SQLite databases returned `ok` from `PRAGMA quick_check`.

None has a container whose title contains `Phase`, or whose `distinguished_kind`
is 25. These captures therefore cannot prove the encoding of an iTunes-created
Phase Playlist or establish a semantic meaning for historical binary value 25.

| Capture | `Library.itdb` SHA-256 | `iTunesCDB` SHA-256 |
| --- | --- | --- |
| `MINE` | `a9e95bc9305ed1b5f479b3c05c984c81511a90166c0e39402bd8728bcb84c373` | `cc701817f656b1c41fe489f6452551e7eb477c3ac6e8cee44d1ab21c16526b78` |
| `USER2` | `19e3e45472af91aa843071aa004fd2bab1dba1a773be8d3e5c79945d5a5d2943` | `33f8b2300cc887f9e5d70c5bd4981a36b2b48ccf3bb812a2b557b187812cee90` |
| `USERS` | `9a38c60af769a0ea265facfa18be262651366ab163a0a637465ceb4cbbe9d3e4` | `d87145f83fe9d44c105946d3dc8a3743dcb6519554be52d59e0bb128c95e8042` |

## Application implications and limits

Current SQLite projection obtains Track PIDs from `Track.ipod.db_track_id`, with
the ordinary Track ID as a fallback only when a persistent ID is absent. It
retains valid unique native Playlist IDs and reallocates collisions
deterministically. SQLite insertion converts unsigned IDs into their signed
64-bit representations without changing their bits.
[Identity helpers](../../src/iPodDB/SQLiteDB/database.py#L138),
[container allocation](../../src/iPodDB/SQLiteDB/database.py#L811).

For future Phase preparation, companion-file IDs must agree with the **final
published database identities**. A producer must not blindly use an earlier
Playlist ID if collision handling changed it. That is an application invariant
derived from cross-file identity references, not a newly discovered firmware
restriction.

The present projection does not carry the raw MHYP `+0x52` halfword into SQLite.
It uses dataset-5 `mhsd_5_type` as category input, emits known category kinds 4/5,
special Podcasts kind 11, or ordinary kind 0. Genius Mix projection is separate.
[Native projection](../../src/iPodDB/library/_sqlite_projection.py#L98),
[container construction](../../src/iPodDB/SQLiteDB/database.py#L833).
The firmware literal at `0x084333a0` does load `distinguished_kind`, but that alone
does not establish any requirement that Phase use kind 25. The subsequent
[independent SDK investigation](phase-nano5-firmware-contract.md) closes that
calling-convention gap and finds a native classifier accepting kinds
0, 17, 101, 20, and 25. It confirms PID/name selection and recognition of 25,
while preserving the limits of these capture-only observations.

These findings complement the
[Phase game and Classic contract](phase-playlist-contract.md) and
[application audit](phase-application-contract.md). They do not change the
accepted iTunesCDB semantic read authority or Storage publication boundaries in
[ADR-0150](../adr/0150-retain-firmware-sqlite-metadata-and-dual-signatures.md).
