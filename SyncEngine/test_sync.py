"""
Quick test of SyncEngine functionality.

Usage:
    uv run python -m SyncEngine.test_sync "D:/Music"
"""

import sys
import tempfile
from pathlib import Path

from .sync_db import SyncDB, SyncEntry
from .pc_library import PCLibrary


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m SyncEngine.test_sync <music_folder>")
        print("Example: python -m SyncEngine.test_sync D:/Music")
        sys.exit(1)

    music_path = sys.argv[1]

    print(f"🎵 Testing SyncEngine with: {music_path}")
    print("-" * 50)

    # 1. Test PC Library Scanner
    print("\n📂 Scanning PC library...")
    try:
        library = PCLibrary(music_path)
        count = library.count_audio_files()
        print(f"   Found {count} audio files")

        # Scan first 10 tracks
        print("\n   First 10 tracks:")
        for i, track in enumerate(library.scan()):
            if i >= 10:
                print(f"   ... and {count - 10} more")
                break
            print(f"   {i + 1}. {track.artist} - {track.title}")
            print(f"      Album: {track.album}")
            print(f"      Duration: {track.duration_ms // 1000}s, Format: {track.extension}")
            print(f"      Needs transcoding: {track.needs_transcoding}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
        sys.exit(1)

    # 2. Test SyncDB
    print("\n💾 Testing SyncDB...")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        db = SyncDB(db_path)
        db.initialize(music_path, "TEST_DEVICE_001", "Test iPod")

        meta = db.get_metadata()
        if meta:
            print(f"   Created database for: {meta.ipod_name}")
            print(f"   PC Library: {meta.pc_library_path}")
        else:
            print("   ❌ Failed to get metadata")

        # Insert a test entry
        entry = SyncEntry(
            pc_path=f"{music_path}/test/song.mp3",
            pc_mtime=1234567890.0,
            pc_size=5000000,
            artist="Test Artist",
            album="Test Album",
            title="Test Song",
            duration_ms=180000,
            ipod_dbid=9876543210,
            ipod_path=":iPod_Control:Music:F00:TEST.mp3",
            last_synced="2026-02-05T12:00:00",
            synced_mtime=1234567890.0,
        )
        db.upsert(entry)

        # Test lookups
        found = db.get_by_dbid(9876543210)
        assert found is not None
        print(f"   ✅ Lookup by dbid works: {found.title}")

        found = db.get_by_pc_path(f"{music_path}/test/song.mp3")
        assert found is not None
        print(f"   ✅ Lookup by path works: {found.title}")

        found = db.find_by_fingerprint("Test Artist", "Test Album", "Test Song", 180000)
        assert found is not None
        print(f"   ✅ Fingerprint match works: {found.title}")

        db.close()
        print("   ✅ SyncDB working correctly")

    finally:
        Path(db_path).unlink(missing_ok=True)

    # 3. Summary
    print("\n" + "=" * 50)
    print("✅ SyncEngine tests passed!")
    print("\nNext steps:")
    print("  1. Connect an iPod and parse iTunesDB")
    print("  2. Call DiffEngine.compute_diff() with iPod tracks")
    print("  3. Review the SyncPlan")
    print("  4. Execute the sync (iTunesDB writer needed)")


if __name__ == "__main__":
    main()
