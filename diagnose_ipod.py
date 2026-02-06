"""
Diagnose iPod database issues - check things we might have overlooked.
"""

import os
import struct
from pathlib import Path

TEST_IPOD = Path(r"C:\Users\JohnG\Music\testing\iPod_Control")
CLEAN_IPOD = Path(r"C:\Users\JohnG\Music\cleanipod\iPod_Control")


def check_file_attributes(path: Path):
    """Check file attributes and permissions."""
    print(f"\n{'=' * 60}")
    print(f"FILE ATTRIBUTES: {path}")
    print('=' * 60)

    if not path.exists():
        print("  FILE DOES NOT EXIST!")
        return

    stat = path.stat()
    print(f"  Size: {stat.st_size:,} bytes")
    print(f"  Modified: {stat.st_mtime}")

    # Check if file is readable
    try:
        with open(path, 'rb') as f:
            magic = f.read(4)
            print(f"  Magic: {magic}")
            print(f"  Readable: YES")
    except Exception as e:
        print(f"  Readable: NO - {e}")


def check_directory_structure(ipod_root: Path, label: str):
    """Check iPod directory structure."""
    print(f"\n{'=' * 60}")
    print(f"DIRECTORY STRUCTURE: {label}")
    print('=' * 60)

    required_dirs = [
        "iTunes",
        "Music",
        "Artwork",
        "Device",
    ]

    for d in required_dirs:
        path = ipod_root / d
        if path.exists():
            files = list(path.iterdir())
            print(f"  /{d}/ - EXISTS ({len(files)} items)")
        else:
            print(f"  /{d}/ - MISSING!")


def check_itunes_files(ipod_root: Path, label: str):
    """Check iTunes folder contents."""
    print(f"\n{'=' * 60}")
    print(f"iTUNES FOLDER: {label}")
    print('=' * 60)

    itunes = ipod_root / "iTunes"
    if not itunes.exists():
        print("  iTunes folder MISSING!")
        return

    important_files = [
        "iTunesDB",
        "iTunesSD",  # Shuffle database
        "iTunesPrefs",
        "iTunesControl",
        "Play Counts",
    ]

    for filename in important_files:
        path = itunes / filename
        if path.exists():
            size = path.stat().st_size
            print(f"  {filename}: {size:,} bytes")
        else:
            print(f"  {filename}: not present")

    # List all files
    print(f"\n  All files in iTunes/:")
    for f in itunes.iterdir():
        size = f.stat().st_size if f.is_file() else 0
        print(f"    {f.name}: {size:,} bytes")


def check_device_info(ipod_root: Path, label: str):
    """Check Device folder for SysInfo."""
    print(f"\n{'=' * 60}")
    print(f"DEVICE INFO: {label}")
    print('=' * 60)

    sysinfo = ipod_root / "Device" / "SysInfo"
    if not sysinfo.exists():
        print("  SysInfo: NOT FOUND")
        return

    print("  SysInfo contents:")
    try:
        with open(sysinfo, 'r', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line:
                    print(f"    {line}")
    except Exception as e:
        print(f"    Error reading: {e}")


def compare_db_basics(clean: Path, test: Path):
    """Compare basic database properties."""
    print(f"\n{'=' * 60}")
    print("DATABASE COMPARISON")
    print('=' * 60)

    clean_db = clean / "iTunes" / "iTunesDB"
    test_db = test / "iTunes" / "iTunesDB"

    if not clean_db.exists():
        print("  Clean DB missing!")
        return
    if not test_db.exists():
        print("  Test DB missing!")
        return

    clean_size = clean_db.stat().st_size
    test_size = test_db.stat().st_size

    print(f"  Clean DB size: {clean_size:,} bytes")
    print(f"  Test DB size:  {test_size:,} bytes")

    # Check header
    with open(clean_db, 'rb') as f:
        clean_header = f.read(244)
    with open(test_db, 'rb') as f:
        test_header = f.read(244)

    # Version
    clean_ver = struct.unpack('<I', clean_header[0x10:0x14])[0]
    test_ver = struct.unpack('<I', test_header[0x10:0x14])[0]
    print(f"  Clean version: 0x{clean_ver:X}")
    print(f"  Test version:  0x{test_ver:X}")

    # Hash scheme
    clean_hs = struct.unpack('<H', clean_header[0x30:0x32])[0]
    test_hs = struct.unpack('<H', test_header[0x30:0x32])[0]
    print(f"  Clean hash_scheme: {clean_hs}")
    print(f"  Test hash_scheme:  {test_hs}")

    # Total length
    clean_len = struct.unpack('<I', clean_header[0x08:0x0C])[0]
    test_len = struct.unpack('<I', test_header[0x08:0x0C])[0]
    print(f"  Clean total_len: {clean_len:,}")
    print(f"  Test total_len:  {test_len:,}")

    # Verify total_len matches file size
    print(f"\n  Clean file size matches total_len: {clean_size == clean_len}")
    print(f"  Test file size matches total_len:  {test_size == test_len}")


def suggest_alternatives():
    """Suggest alternative approaches."""
    print(f"\n{'=' * 60}")
    print("ALTERNATIVE APPROACHES")
    print('=' * 60)
    print("""
  If the database still doesn't work, consider:

  1. USE LIBGPOD DIRECTLY:
     pip install python-gpod  (if available for Windows)
     Or use WSL with libgpod

  2. USE GTKPOD TO CREATE A KNOWN-GOOD DATABASE:
     - Install gtkpod (Linux/WSL)
     - Add one track manually
     - Compare that database byte-by-byte with ours

  3. CHECK THE IPOD ITSELF:
     - Try a fresh "Restore" in iTunes
     - Check if the iPod works with iTunes after restore
     - Then compare the fresh database

  4. USE ROCKBOX:
     - Rockbox firmware reads standard music files
     - No database hassle at all
     - Works great on iPod Classic

  5. CHECK WINDOWS-SPECIFIC ISSUES:
     - File might need to be marked as "hidden" or "system"
     - Try copying to iPod while iPod is in disk mode
     - Check if Windows is adding BOM or other artifacts
""")


def main():
    print("iPod Database Diagnostics")
    print("=" * 60)

    # Check both iPod structures
    for ipod, label in [(CLEAN_IPOD, "CLEAN"), (TEST_IPOD, "TEST")]:
        check_directory_structure(ipod, label)
        check_itunes_files(ipod, label)
        check_device_info(ipod, label)

    # Compare databases
    compare_db_basics(CLEAN_IPOD, TEST_IPOD)

    # Check specific file attributes
    check_file_attributes(CLEAN_IPOD / "iTunes" / "iTunesDB")
    check_file_attributes(TEST_IPOD / "iTunes" / "iTunesDB")

    # Suggest alternatives
    suggest_alternatives()


if __name__ == "__main__":
    main()
