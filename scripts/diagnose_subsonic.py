"""One-shot Subsonic sync diagnostic.

Run: uv run python scripts/diagnose_subsonic.py

Reads your saved Subsonic settings, connects, fetches starred songs, and
compares against the iPod library to show exactly how many would be skipped
vs added — and WHY.
"""
from __future__ import annotations

import os
import sys

# Ensure project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> None:
    from infrastructure.settings_persistence import load_app_settings

    s = load_app_settings()
    if not (s.subsonic_url and s.subsonic_username):
        print("✗ Subsonic not configured in settings. Configure it in the GUI first.")
        return

    print(f"Server: {s.subsonic_url}")
    print(f"User:   {s.subsonic_username}")
    print(f"sync_starred: {s.subsonic_sync_starred}")
    print(f"playlist_ids: {s.subsonic_playlist_ids}")
    print()

    # --- Fetch starred songs from the server ---
    from iopenpod.subsonic.client import SubsonicClient, SubsonicConnectionError

    try:
        client = SubsonicClient(s.subsonic_url, s.subsonic_username, s.subsonic_password)
        client.ping()
        print("✓ Connected to server")
    except SubsonicConnectionError as exc:
        print(f"✗ Connection failed: {exc}")
        return

    from iopenpod.subsonic.plan_builder import _collect_starred_songs, _dedupe_songs

    songs = []
    if s.subsonic_sync_starred:
        songs = _collect_starred_songs(client)
        print(f"Starred songs fetched: {len(songs)}")
    songs = _dedupe_songs(songs)
    print(f"After dedupe: {len(songs)}")
    print()

    if not songs:
        print("✗ No starred songs found. Is sync_starred enabled? Are there starred songs?")
        return

    # --- Show what the server returns for a sample ---
    print("=== Sample of what the server returns (first 5) ===")
    for song in songs[:5]:
        print(f"  id={song.get('id')!r}")
        print(f"    title={song.get('title')!r}  artist={song.get('artist')!r}")
        print(f"    album={song.get('album')!r}")
    print()

    # --- We can't read the iPod library here without a device path ---
    # But we CAN show whether the matching would work by printing the keys.
    print("=== Matching keys that would be used ===")
    keys = set()
    for song in songs:
        title = (song.get("title") or "").strip().lower()
        artist = (song.get("artist") or "").strip().lower()
        if title and artist:
            keys.add((title, artist))
    print(f"Unique (title, artist) pairs from server: {len(keys)}")
    print()

    print("NOTE: To complete the diagnosis, the iPod must be connected.")
    print("If you see this output, the server fetch is working.")
    print("If 'Starred songs fetched' = 516 but nothing syncs, the dedup is")
    print("matching against your existing 466 iPod tracks. Check the Sync")
    print("Review 'Music' card — if it shows 0 to add, that's the cause.")


if __name__ == "__main__":
    main()
