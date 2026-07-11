# Testing Plan — Refactor Validation

This plan covers all changes in the current refactor vs origin/main.
Work through each section with a real iPod connected.

---

## 1. Startup & Settings

Tests: `settings.py`, `src/iopenpod/__main__.py`, `src/iopenpod/gui/settings.py` (deleted shim), function renames

- [ ] App launches without import errors
- [ ] Settings load correctly (check theme, transcode format, backup toggle)
- [ ] Change a setting, restart — setting persists
- [ ] Settings page displays correct version number
- [ ] Data directory and cache directory resolve correctly (check log for paths)

---

## 2. iTunesDB Parsing (Read Path)

Tests: deleted list parsers (`mhlt`, `mhla`, `mhli`, `mhlp`), `_parse_child_list()`, `field_base.read_fields()`, `extraction.py`, `mhod_parser.py` changes

- [ ] Connect iPod with existing library — app reads and displays all tracks
- [ ] Album count in grid matches expected count
- [ ] Artist list populates correctly
- [ ] Playlists (regular + smart) all appear in sidebar
- [ ] Track metadata correct: title, artist, album, genre, duration, sample rate
- [ ] Verify sample rate displays in Hz (e.g. 44100), not fixed-point garbage (e.g. 2890137600)
- [ ] Artwork loads for albums that have it

---

## 3. Sync — Analysis Phase

Tests: `src/iopenpod/sync/__init__.py`, `_formats.py`, `_track_conversion.py`, `pc_library.py`, `integrity.py`

- [ ] Add a few new tracks to PC library, click Sync
- [ ] Sync review shows correct additions (new tracks listed)
- [ ] Remove a track from PC library — sync review shows removal
- [ ] Tracks needing transcoding (FLAC, OGG) correctly identified
- [ ] Native formats (MP3, AAC, ALAC, M4A) listed as direct copy
- [ ] Video files correctly identified if applicable

---

## 4. Sync — Playlist Building

Tests: `_playlist_builder.py`, `_db_io.py`

- [ ] Regular playlists sync correctly (tracks in right order)
- [ ] Smart playlists evaluate and populate correctly
- [ ] Master playlist contains all tracks
- [ ] Podcast playlist appears if device supports podcasts
- [ ] Playlist names preserved (no garbled Unicode)

---

## 5. Sync — Execution & Database Write

Tests: `sync_executor.py` (extraction), `_db_io.py`, `mhbd_writer.py`, `mhod52_writer.py` (ord fix), `mhla_writer.py`, `mhli_writer.py`

- [ ] Full sync completes without "database write failed" error
- [ ] Eject iPod, reconnect — all synced tracks visible and playable
- [ ] Jump table / letter index works (scroll by letter on iPod)
- [ ] Test with tracks containing special characters in metadata:
  - [ ] Non-ASCII letters (accented: e, u, o, etc.)
  - [ ] CJK characters (Japanese, Chinese, Korean)
  - [ ] German sharp-s (ß) — this was the ord() bug trigger
  - [ ] Ligatures (fi, fl) if possible
- [ ] Album grouping correct on iPod
- [ ] Artist grouping correct on iPod

---

## 6. Sync — Transcoding

Tests: `transcoder.py`, `_formats.py` constants

- [ ] FLAC file transcodes to ALAC (or AAC depending on setting)
- [ ] OGG file transcodes correctly
- [ ] Transcoded files play on iPod
- [ ] Transcode cache works — re-sync same tracks, no re-transcode (check log)

---

## 7. SQLite Database (Nano 6G/7G only)

Tests: `src/iopenpod/sqlitedb_writer/_helpers.py`, `library_writer.py`, `dynamic_writer.py`, `extras_writer.py`, `genius_writer.py`, `locations_writer.py`, `sqlite_writer.py`

Skip if no Nano 6G/7G available.

- [ ] Sync completes on Nano 6G/7G
- [ ] Core Data timestamps correct (tracks show right dates on device)
- [ ] Playlist PIDs correctly passed from library_writer to dynamic_writer
- [ ] All 5 SQLite databases created without errors
- [ ] Tracks playable on device after sync

---

## 8. Podcast Sync

Tests: `src/iopenpod/podcasts/downloader.py` (new `download_and_probe_episode()`), `podcast_sync.py`, `subscription_store.py`

- [ ] Subscribe to a podcast feed
- [ ] Episodes download successfully
- [ ] Episode metadata correct (bitrate, sample rate, duration)
- [ ] Podcast episodes sync to iPod
- [ ] Podcast playlist appears on device (if supported)

---

## 9. Backup & Restore

Tests: `backup_manager.py`

- [ ] Backup before sync works (if enabled in settings)
- [ ] Backup browser shows snapshots
- [ ] Restore from backup works

---

## 10. Integrity & Edge Cases

Tests: `integrity.py`, `_db_io.py`, `playcounts.py`

- [ ] Orphan files on iPod detected during integrity check
- [ ] Play counts merge correctly (play a track on iPod, sync, check count updates)
- [ ] Empty iPod (fresh restore) — first sync works from scratch
- [ ] Large library (1000+ tracks) — sync completes without timeout or memory issues

---

## 11. GUI

Tests: import path changes (`iopenpod.gui.settings` -> `settings`), `src/iopenpod/gui/app.py`

- [ ] All theme changes work (dark, light, system, catppuccin variants)
- [ ] High contrast toggle works
- [ ] Window size persists across restart
- [ ] Sync error dialog shows correctly (if sync fails)
- [ ] Auto-updater check works (Settings > Check for update)
- [ ] Music browser splitter position persists
- [ ] Track list artwork toggle works

---

## Summary of Bug Fixes in This Refactor

| Fix | File | Description |
|-----|------|-------------|
| ord() crash | `mhod52_writer.py:90` | `ch.upper()` can return >1 char for Unicode (ß->SS). Fixed with `[0]` |

## What Was Refactored (no logic changes)

| Area | What changed |
|------|-------------|
| List parsers | 4 near-identical parsers consolidated into `_parse_child_list()` |
| Field I/O | `read_fields()` / `write_fields()` centralized in `field_base.py` with read/write transforms |
| Extraction helpers | `extract_datasets()`, `extract_mhod_strings()`, `extract_playlist_extras()` moved to `extraction.py` |
| SyncEngine | Large `sync_executor.py` split into `_db_io.py`, `_formats.py`, `_track_conversion.py`, `_playlist_builder.py` |
| SQLiteDB helpers | `unix_to_coredata()`, `s64()`, `open_db()` extracted to `_helpers.py` |
| Settings shim | `src/iopenpod/gui/settings.py` removed; all imports point to root `settings.py` |
| Function visibility | `_default_data_dir()`, `_default_cache_dir()`, `_get_settings_dir()` made public (underscore removed) |
| Podcast download | `download_and_probe_episode()` added to `downloader.py`, used by sync_executor |
