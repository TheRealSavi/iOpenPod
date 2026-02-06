"""
Surgical Test Database Generator & Diagnostic Tool

Workflow:
  1. Sync music to your test iPod copy using the iOpenPod GUI
  2. Run this script to create hybrid databases that isolate each component
  3. Copy each surgical DB to iPod, test which ones work

This tells you exactly which MHSD section (tracks, playlists, albums, etc.)
or header is causing the iPod to reject the database.

Usage:
    uv run python make_surgical_tests.py
    uv run python make_surgical_tests.py --verify   (compare test vs clean structure)
"""

import struct
import sys
from pathlib import Path

CLEAN_DB = Path(r"C:\Users\JohnG\Music\cleanipod\iPod_Control\iTunes\iTunesDB")
TEST_DB = Path(r"C:\Users\JohnG\Music\testing\iPod_Control\iTunes\iTunesDB")
OUTPUT_DIR = Path(r"C:\Users\JohnG\Music\surgical_tests")


# ── MHBD header field map (from libgpod MhbdHeader) ──────────────────────

MHBD_FIELDS = [
    (0x00, 4, 'header_id', 'str'),
    (0x04, 4, 'header_len', 'u32'),
    (0x08, 4, 'total_len', 'u32'),
    (0x0C, 4, 'unknown1', 'u32'),
    (0x10, 4, 'version', 'u32'),
    (0x14, 4, 'num_children', 'u32'),
    (0x18, 8, 'db_id', 'u64'),
    (0x20, 2, 'platform', 'u16'),
    (0x22, 2, 'unk_0x22', 'u16'),
    (0x24, 8, 'id_0x24', 'u64'),
    (0x2C, 4, 'unk_0x2c', 'u32'),
    (0x30, 2, 'hashing_scheme', 'u16'),
    (0x32, 20, 'unk_0x32', 'hex'),
    (0x46, 2, 'language', 'str'),
    (0x48, 8, 'lib_persistent_id', 'u64'),
    (0x50, 4, 'unk_0x50', 'u32'),
    (0x54, 4, 'unk_0x54', 'u32'),
    (0x58, 20, 'hash58', 'hex'),
    (0x6C, 4, 'timezone', 'i32'),
    (0x70, 2, 'unk_0x70', 'u16'),
    (0x72, 46, 'hash72', 'hex'),
    (0xA0, 2, 'audio_language', 'u16'),
    (0xA2, 2, 'subtitle_language', 'u16'),
    (0xA4, 2, 'unk_0xa4', 'u16'),
    (0xA6, 2, 'unk_0xa6', 'u16'),
    (0xA8, 2, 'unk_0xa8', 'u16'),
    (0xAA, 1, 'unk_0xaa', 'u8'),
    (0xAB, 57, 'hashAB', 'hex'),
    (0xE4, 16, 'unk_0xe4', 'hex'),
]

MHSD_NAMES = {1: "Tracks", 2: "Playlists", 3: "Podcasts", 4: "Albums", 5: "SmartPL"}


# ── Database parsing ─────────────────────────────────────────────────────

def extract_mhsds(data: bytes) -> dict:
    """Extract all MHSDs from a database, preserving order."""
    mhsds = {}
    header_len = struct.unpack('<I', data[4:8])[0]
    num_mhsds = struct.unpack('<I', data[20:24])[0]

    offset = header_len
    for _ in range(num_mhsds):
        if offset >= len(data) or data[offset:offset + 4] != b'mhsd':
            break
        total_len = struct.unpack('<I', data[offset + 8:offset + 12])[0]
        mhsd_type = struct.unpack('<I', data[offset + 12:offset + 16])[0]
        mhsds[mhsd_type] = data[offset:offset + total_len]
        offset += total_len
    return mhsds


def get_mhsd_child_info(mhsd_data: bytes) -> dict:
    """Parse the first child chunk inside an MHSD to get counts."""
    hdr_len = struct.unpack('<I', mhsd_data[4:8])[0]
    child_offset = hdr_len
    if child_offset >= len(mhsd_data):
        return {}

    child_magic = mhsd_data[child_offset:child_offset + 4]
    child_hdr_len = struct.unpack('<I', mhsd_data[child_offset + 4:child_offset + 8])[0]
    child_total_len = struct.unpack('<I', mhsd_data[child_offset + 8:child_offset + 12])[0]

    info = {
        'magic': child_magic.decode('ascii', errors='replace'),
        'header_len': child_hdr_len,
        'total_len': child_total_len,
    }

    # mhlt and mhlp have child count at offset 8 of their content (offset +8)
    if child_magic in (b'mhlt', b'mhlp', b'mhla'):
        count = struct.unpack('<I', mhsd_data[child_offset + 8:child_offset + 12])[0]
        info['count'] = count

    return info


def find_first_mhit(mhsd_data: bytes) -> int | None:
    """Find the offset of the first MHIT within a tracks MHSD."""
    hdr_len = struct.unpack('<I', mhsd_data[4:8])[0]
    mhlt_offset = hdr_len
    if mhsd_data[mhlt_offset:mhlt_offset + 4] != b'mhlt':
        return None
    mhlt_hdr_len = struct.unpack('<I', mhsd_data[mhlt_offset + 4:mhlt_offset + 8])[0]
    mhit_offset = mhlt_offset + mhlt_hdr_len
    if mhsd_data[mhit_offset:mhit_offset + 4] != b'mhit':
        return None
    return mhit_offset


# ── Build hybrid databases ───────────────────────────────────────────────

def build_hybrid(header: bytes, mhsd_list: list, clean_data: bytes) -> bytes:
    """Build database from header + MHSDs, then rehash."""
    from iTunesDB_Writer.hash72 import (
        extract_hash_info_to_dict, _compute_itunesdb_sha1,
        _hash_generate, OFFSET_HASH72,
    )

    result = bytearray(header) + b''.join(mhsd_list)
    struct.pack_into('<I', result, 8, len(result))          # total_len
    struct.pack_into('<I', result, 0x14, len(mhsd_list))    # num_children

    # Copy hash58 from clean (can't recompute without FireWire ID)
    result[0x58:0x6C] = clean_data[0x58:0x6C]

    # Regenerate hash72 with clean's IV/rndpart
    hash_info = extract_hash_info_to_dict(clean_data)
    if hash_info:
        sha1 = _compute_itunesdb_sha1(bytearray(result))
        sig = _hash_generate(sha1, hash_info['iv'], hash_info['rndpart'])
        result[OFFSET_HASH72:OFFSET_HASH72 + 46] = sig
    else:
        print("  WARNING: Could not extract hash info — hash72 NOT regenerated!")

    return bytes(result)


# ── Verification / comparison ────────────────────────────────────────────

def compare_headers(clean: bytes, test: bytes):
    """Compare MHBD headers field-by-field."""
    print("\n" + "=" * 70)
    print("MHBD HEADER COMPARISON")
    print("=" * 70)

    diffs = 0
    for offset, size, name, fmt in MHBD_FIELDS:
        c = clean[offset:offset + size]
        t = test[offset:offset + size] if offset + size <= len(test) else b'\x00' * size

        if c == t:
            continue  # Skip matching fields

        diffs += 1
        if fmt == 'str':
            cv = c.decode('ascii', errors='replace')
            tv = t.decode('ascii', errors='replace')
            print(f"  {name:25s} (0x{offset:02X}): clean={cv!r:20s}  test={tv!r}")
        elif fmt == 'hex':
            print(f"  {name:25s} (0x{offset:02X}): clean={c[:8].hex()}{'...' if size > 8 else ''}")
            print(f"  {'':25s}          test={t[:8].hex()}{'...' if size > 8 else ''}")
        elif fmt == 'u64':
            cv = struct.unpack('<Q', c)[0]
            tv = struct.unpack('<Q', t)[0]
            print(f"  {name:25s} (0x{offset:02X}): clean=0x{cv:016X}  test=0x{tv:016X}")
        elif fmt == 'i32':
            cv = struct.unpack('<i', c)[0]
            tv = struct.unpack('<i', t)[0]
            print(f"  {name:25s} (0x{offset:02X}): clean={cv:10d}  test={tv:10d}")
        elif fmt == 'u16':
            cv = struct.unpack('<H', c)[0]
            tv = struct.unpack('<H', t)[0]
            print(f"  {name:25s} (0x{offset:02X}): clean={cv:10d}  test={tv:10d}")
        elif fmt == 'u8':
            print(f"  {name:25s} (0x{offset:02X}): clean={c[0]:10d}  test={t[0]:10d}")
        else:
            cv = struct.unpack('<I', c)[0]
            tv = struct.unpack('<I', t)[0]
            print(f"  {name:25s} (0x{offset:02X}): clean={cv:10d}  test={tv:10d}")

    if diffs == 0:
        print("  (no differences outside hashes)")
    else:
        print(f"\n  {diffs} field(s) differ")


def compare_mhsds(clean_mhsds: dict, test_mhsds: dict):
    """Compare MHSD sections structurally."""
    print("\n" + "=" * 70)
    print("MHSD SECTION COMPARISON")
    print("=" * 70)

    all_types = sorted(set(clean_mhsds.keys()) | set(test_mhsds.keys()))

    for t in all_types:
        name = MHSD_NAMES.get(t, f"Type {t}")
        if t not in clean_mhsds:
            print(f"\n  MHSD type {t} ({name}): MISSING from clean")
            continue
        if t not in test_mhsds:
            print(f"\n  MHSD type {t} ({name}): MISSING from test")
            continue

        c_data = clean_mhsds[t]
        t_data = test_mhsds[t]
        c_info = get_mhsd_child_info(c_data)
        t_info = get_mhsd_child_info(t_data)

        match = "✓" if c_data == t_data else "≠"
        print(f"\n  MHSD type {t} ({name}): {match}")
        print(f"    Clean: {len(c_data):>8,} bytes  child={c_info.get('magic', '?')}"
              f"  count={c_info.get('count', '?')}")
        print(f"    Test:  {len(t_data):>8,} bytes  child={t_info.get('magic', '?')}"
              f"  count={t_info.get('count', '?')}")


def compare_first_mhit(clean_mhsds: dict, test_mhsds: dict):
    """Compare the first MHIT header between clean and test."""
    if 1 not in clean_mhsds or 1 not in test_mhsds:
        return

    c_mhit_off = find_first_mhit(clean_mhsds[1])
    t_mhit_off = find_first_mhit(test_mhsds[1])

    if c_mhit_off is None or t_mhit_off is None:
        print("\n  Could not find MHIT in one or both databases")
        return

    c_data = clean_mhsds[1]
    t_data = test_mhsds[1]

    c_hlen = struct.unpack('<I', c_data[c_mhit_off + 4:c_mhit_off + 8])[0]
    t_hlen = struct.unpack('<I', t_data[t_mhit_off + 4:t_mhit_off + 8])[0]

    print(f"\n{'=' * 70}")
    print("FIRST MHIT COMPARISON")
    print("=" * 70)
    print(f"  Clean MHIT header: {c_hlen} bytes  |  Test MHIT header: {t_hlen} bytes")

    # Key MHIT fields
    mhit_fields = [
        (0x04, 4, 'header_len'),
        (0x08, 4, 'total_len'),
        (0x0C, 4, 'num_mhods'),
        (0x10, 4, 'track_id'),
        (0x14, 4, 'visible'),
        (0x18, 4, 'filetype'),
        (0x1C, 4, 'vbr'),
        (0x20, 8, 'dbid'),
        (0x28, 4, 'length_ms'),
        (0x2C, 4, 'track_num'),
        (0x30, 4, 'total_tracks'),
        (0x34, 4, 'year'),
        (0x38, 4, 'bitrate'),
        (0x3C, 4, 'sample_rate'),
        (0x50, 4, 'play_count'),
        (0x54, 4, 'play_count2'),
        (0x5C, 4, 'disc_number'),
        (0x60, 4, 'total_discs'),
        (0x68, 4, 'date_added'),
        (0xD0, 4, 'media_type'),
    ]

    diffs = 0
    for offset, size, fname in mhit_fields:
        if offset + size > c_hlen or offset + size > t_hlen:
            continue
        if size == 8:
            cv = struct.unpack('<Q', c_data[c_mhit_off + offset:c_mhit_off + offset + 8])[0]
            tv = struct.unpack('<Q', t_data[t_mhit_off + offset:t_mhit_off + offset + 8])[0]
        else:
            cv = struct.unpack('<I', c_data[c_mhit_off + offset:c_mhit_off + offset + 4])[0]
            tv = struct.unpack('<I', t_data[t_mhit_off + offset:t_mhit_off + offset + 4])[0]

        if cv != tv:
            diffs += 1
            if size == 8:
                print(f"    {fname:20s} (0x{offset:02X}): clean=0x{cv:016X}  test=0x{tv:016X}")
            elif fname == 'filetype':
                cf = c_data[c_mhit_off + offset:c_mhit_off + offset + 4]
                tf = t_data[t_mhit_off + offset:t_mhit_off + offset + 4]
                print(f"    {fname:20s} (0x{offset:02X}): clean={cf}  test={tf}")
            else:
                print(f"    {fname:20s} (0x{offset:02X}): clean={cv:10d}  test={tv:10d}")

    # Also show non-zero bytes that differ across the full header
    max_len = min(c_hlen, t_hlen)
    extra_diffs = 0
    for i in range(max_len):
        cb = c_data[c_mhit_off + i]
        tb = t_data[t_mhit_off + i]
        if cb != tb:
            extra_diffs += 1

    print(f"\n  Total differing bytes in header: {extra_diffs}/{max_len}")


def verify_hash72(data: bytes, label: str):
    """Verify the hash72 signature in a database."""
    from iTunesDB_Writer.hash72 import (
        _compute_itunesdb_sha1, _hash_extract, _hash_generate,
    )

    sig = bytes(data[0x72:0x72 + 46])
    if sig[0:2] != b'\x01\x00':
        print(f"  {label}: No valid hash72 (prefix: 0x{sig[0]:02X}{sig[1]:02X})")
        return False

    sha1 = _compute_itunesdb_sha1(bytearray(data))
    result = _hash_extract(sig, sha1)
    if result is None:
        print(f"  {label}: hash72 INVALID — signature does not match content")
        return False

    iv, rndpart = result
    regen = _hash_generate(sha1, iv, rndpart)
    if regen == sig:
        print(f"  {label}: hash72 VALID ✓")
        return True
    else:
        print(f"  {label}: hash72 MISMATCH ✗")
        return False


# ── Main commands ────────────────────────────────────────────────────────

def cmd_verify():
    """Compare clean vs test database structure + verify hashes."""
    print("Loading databases...")
    clean = CLEAN_DB.read_bytes()
    test = TEST_DB.read_bytes()
    print(f"  Clean: {len(clean):,} bytes ({CLEAN_DB})")
    print(f"  Test:  {len(test):,} bytes ({TEST_DB})")

    compare_headers(clean, test)

    clean_mhsds = extract_mhsds(clean)
    test_mhsds = extract_mhsds(test)
    compare_mhsds(clean_mhsds, test_mhsds)
    compare_first_mhit(clean_mhsds, test_mhsds)

    print(f"\n{'=' * 70}")
    print("HASH VERIFICATION")
    print("=" * 70)
    verify_hash72(clean, "Clean")
    verify_hash72(test, "Test")


def cmd_build():
    """Build surgical test databases."""
    print("Loading databases...")
    clean = CLEAN_DB.read_bytes()
    test = TEST_DB.read_bytes()
    print(f"  Clean: {len(clean):,} bytes")
    print(f"  Test:  {len(test):,} bytes")

    clean_mhsds = extract_mhsds(clean)
    test_mhsds = extract_mhsds(test)

    clean_hdr_len = struct.unpack('<I', clean[4:8])[0]
    test_hdr_len = struct.unpack('<I', test[4:8])[0]
    clean_header = clean[:clean_hdr_len]
    test_header = test[:test_hdr_len]

    # Read MHSD order from clean DB
    order = list(clean_mhsds.keys())
    mhsd_desc = ", ".join(f"{t}={MHSD_NAMES.get(t, '?')}" for t in order)
    print(f"\n  Clean MHSDs: [{mhsd_desc}]")

    tests = [
        # Baseline
        ("01_clean_baseline",
         "Clean DB — should always work",
         "clean", {t: "clean" for t in order}),
        # Isolate each section
        ("02_test_tracks",
         "Clean + Test TRACKS (type 1) — if fails, track writing is broken",
         "clean", {**{t: "clean" for t in order}, 1: "test"}),
        ("03_test_playlists",
         "Clean + Test PLAYLISTS (type 2) — if fails, playlist writing is broken",
         "clean", {**{t: "clean" for t in order}, 2: "test"}),
        ("04_test_albums",
         "Clean + Test ALBUMS (type 4) — if fails, album writing is broken",
         "clean", {**{t: "clean" for t in order}, 4: "test"}),
        ("05_test_header",
         "Test HEADER + Clean data — if fails, header fields are wrong",
         "test", {t: "clean" for t in order}),
        # Combinations
        ("06_test_tracks_playlists",
         "Clean + Test tracks AND playlists",
         "clean", {**{t: "clean" for t in order}, 1: "test", 2: "test"}),
        ("07_test_tracks_albums",
         "Clean + Test tracks AND albums",
         "clean", {**{t: "clean" for t in order}, 1: "test", 4: "test"}),
        ("08_full_test",
         "Full test DB (everything from test)",
         "test", {t: "test" for t in order}),
    ]

    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"\nBuilding {len(tests)} surgical databases → {OUTPUT_DIR}\n")

    for name, desc, hdr_src, mhsd_sources in tests:
        header = clean_header if hdr_src == "clean" else test_header
        mhsd_list = []
        parts = []
        for t in order:
            src = mhsd_sources.get(t, "clean")
            mhsd_list.append(clean_mhsds[t] if src == "clean" else test_mhsds[t])
            if src == "test":
                parts.append(MHSD_NAMES.get(t, f"T{t}"))

        hybrid = build_hybrid(header, mhsd_list, clean)
        path = OUTPUT_DIR / f"{name}_iTunesDB"
        path.write_bytes(hybrid)

        test_parts = ", ".join(parts) if parts else "none"
        hdr_label = "TEST" if hdr_src == "test" else "clean"
        print(f"  {name}: {len(hybrid):>10,} bytes  "
              f"hdr={hdr_label:5s}  test_parts=[{test_parts}]")

    print(f"\n{'=' * 70}")
    print("TESTING INSTRUCTIONS")
    print("=" * 70)
    print(f"""
For each file in {OUTPUT_DIR}:
  1. Copy it to your iPod at /iPod_Control/iTunes/iTunesDB
  2. Safely eject, check if iPod reads it

Expected results:
  01_clean_baseline      → MUST work (it's the clean DB, rehashed)
  02_test_tracks         → If FAILS → mhit_writer or mhod_writer is broken
  03_test_playlists      → If FAILS → mhyp_writer or mhip_writer is broken
  04_test_albums         → If FAILS → mhla_writer is broken
  05_test_header         → If FAILS → MHBD header fields are wrong
  06_test_tracks_playlists → Combination test
  07_test_tracks_albums    → Combination test
  08_full_test           → Full test (same as your synced DB)

If 01 fails, the hash72 regeneration itself is broken.
If 01 works but all others fail, the issue is in whichever section you swapped.
""")


def main():
    mode = "build"
    if len(sys.argv) > 1:
        arg = sys.argv[1].lstrip('-').lower()
        if arg in ("verify", "v", "compare", "c"):
            mode = "verify"
        elif arg in ("all", "a"):
            mode = "all"

    if mode == "verify":
        cmd_verify()
    elif mode == "all":
        cmd_verify()
        print("\n\n")
        cmd_build()
    else:
        cmd_build()


if __name__ == "__main__":
    main()
