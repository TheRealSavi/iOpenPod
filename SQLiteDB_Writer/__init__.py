"""SQLiteDB_Writer — Write SQLite databases for iPod Nano 6G/7G.

These iPods ignore the traditional binary iTunesDB (or iTunesCDB) and read
music metadata from SQLite databases located in:

    /iPod_Control/iTunes/iTunes Library.itlp/

The directory contains:
    Library.itdb     — tracks, albums, artists, composers, playlists, genres
    Locations.itdb   — iPod file paths for each track
    Dynamic.itdb     — play counts, ratings, bookmarks
    Extras.itdb      — lyrics, chapters (optional, can be empty)
    Genius.itdb      — genius data (optional, can be empty)
    Locations.itdb.cbk — HASHAB-signed block checksums of Locations.itdb

Reference implementation: libgpod itdb_sqlite.c
"""

from .sqlite_writer import write_sqlite_databases

__all__ = ["write_sqlite_databases"]
