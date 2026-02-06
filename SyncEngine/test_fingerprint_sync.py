"""
Test script for the fingerprint-based sync engine.

Run: uv run python SyncEngine/test_fingerprint_sync.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from SyncEngine import (  # noqa: E402
    is_fpcalc_available,
    is_ffmpeg_available,
    compute_fingerprint,
    read_fingerprint,
    MappingFile,
    needs_transcoding,
)


def test_dependencies():
    """Check if required tools are available."""
    print("=== Dependency Check ===")
    print(f"fpcalc (Chromaprint): {'✅ Available' if is_fpcalc_available() else '❌ Not found'}")
    print(f"ffmpeg (Transcoding): {'✅ Available' if is_ffmpeg_available() else '❌ Not found'}")

    if not is_fpcalc_available():
        print("\n⚠️  fpcalc not found!")
        print("   Download from: https://acoustid.org/chromaprint")
        print("   Windows: Extract fpcalc.exe to C:\\Program Files\\fpcalc\\ or add to PATH")
    print()


def test_mapping_file():
    """Test the mapping file CRUD operations."""
    print("=== Mapping File Test ===")

    # Create a test mapping in memory
    mapping = MappingFile()
    print(f"New mapping created: {mapping.track_count} tracks")

    # Add a track
    mapping.add_track(
        fingerprint="AQADtNQyRUkSRZEiJYqSKMmS",
        dbid=0x1234567890ABCDEF,
        source_format="flac",
        ipod_format="alac",
        source_size=45000000,
        source_mtime=1738756200.0,
        was_transcoded=True,
        source_path_hint="D:/Music/Queen/Bohemian Rhapsody.flac",
    )
    print(f"Added track: {mapping.track_count} tracks")

    # Lookup by fingerprint
    track = mapping.get_track("AQADtNQyRUkSRZEiJYqSKMmS")
    if track:
        print(f"Found track: dbid=0x{track.dbid:016X}, format={track.source_format}→{track.ipod_format}")

    # Lookup by dbid
    result = mapping.get_by_dbid(0x1234567890ABCDEF)
    if result:
        fp, track = result
        print(f"Found by dbid: fingerprint={fp[:20]}...")

    # Serialize to dict
    data = mapping.to_dict()
    print(f"Serialized: {len(data['tracks'])} tracks in JSON")

    # Deserialize
    restored = MappingFile.from_dict(data)
    print(f"Restored: {restored.track_count} tracks")
    print()


def test_transcoding_detection():
    """Test format detection for transcoding."""
    print("=== Transcoding Detection ===")

    test_files = [
        "song.mp3",
        "song.m4a",
        "song.flac",
        "song.wav",
        "song.ogg",
        "song.opus",
    ]

    for filename in test_files:
        needs = needs_transcoding(filename)
        print(f"  {filename}: {'Needs transcoding' if needs else 'iPod-native'}")
    print()


def test_fingerprinting(test_file: str | None = None):
    """Test fingerprint computation on a real file."""
    print("=== Fingerprint Test ===")

    if not is_fpcalc_available():
        print("⚠️  Skipping: fpcalc not available")
        return

    if test_file is None:
        print("Usage: Pass a music file path to test fingerprinting")
        print("Example: python test_fingerprint_sync.py D:/Music/song.mp3")
        return

    path = Path(test_file)
    if not path.exists():
        print(f"❌ File not found: {path}")
        return

    print(f"File: {path}")

    # Check for existing fingerprint
    existing = read_fingerprint(path)
    if existing:
        print(f"Existing fingerprint: {existing[:40]}...")
    else:
        print("No existing fingerprint stored")

    # Compute fingerprint
    print("Computing fingerprint...")
    fp = compute_fingerprint(path)
    if fp:
        print(f"Computed: {fp[:40]}...")
        print(f"Length: {len(fp)} chars")
    else:
        print("❌ Failed to compute fingerprint")


if __name__ == "__main__":
    test_dependencies()
    test_mapping_file()
    test_transcoding_detection()

    # If a file path was provided, test fingerprinting
    if len(sys.argv) > 1:
        test_fingerprinting(sys.argv[1])
    else:
        test_fingerprinting()
