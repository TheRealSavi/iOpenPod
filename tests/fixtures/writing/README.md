# Semantic writing evidence

`hash58-original.json` contains fixed outputs captured from Original iOpenPod's
`src/iopenpod/itunesdb_writer/hash58.py` on 2026-09-05. Its source-file SHA-256 and
the deterministic input construction are recorded with the vectors. The capture
executed its key derivation and explicit HMAC implementation with its literal AES
tables, independently of iOpenPod 2.0's computed tables and standard-library HMAC.
Tests use only the captured JSON; Original iOpenPod is never imported at runtime.

`playlists-original.json` captures `write_mhyp` output for regular, folder, grouped
podcast, and Rentals rows, plus `write_mhod_playlist_prefs`, from Original iOpenPod
on 2026-09-05. The source SHA-256 is recorded. Inputs use name `Example`, Track IDs
`[1, 2, 1]`, Playlist ID `12345`, database ID `67890`, and timestamp `0`; podcast
albums are `1` and `2`. The Rentals row carries category `7` and the Master flag;
the folder carries flag `0x100`. Tests consume these fixed bytes without importing
Original iOpenPod. The 648-byte preference record is also compared directly with
new semantic output.

Additional preservation tests reuse the independently generated fixtures in
`../iTunesDB/` and `../ArtworkDB/`. Packed primary-color vectors come directly from
the RGB565/RGB555 bitfields. Original `mhyp_writer.py`, `mhip_writer.py`,
`mhod52_writer.py`, `mhla_writer.py`, and `playlist_hierarchy.py` supply the baseline
for zero-based ordinary positions, grouped podcast item IDs, browse ordering,
album representative IDs, and recursive folder membership/rules.

These fixtures establish binary compatibility evidence, not a physical-device Sync
test. Physical Sync remains outside this preparation workflow.
