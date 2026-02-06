"""
Deep binary comparison of clean vs test MHSD sections.
Finds exactly where/why the writer output differs structurally.
"""
import struct
from pathlib import Path

CLEAN_DB = Path(r"C:\Users\JohnG\Music\cleanipod\iPod_Control\iTunes\iTunesDB")
TEST_DB = Path(r"C:\Users\JohnG\Music\testing\iPod_Control\iTunes\iTunesDB")


def extract_mhsds(data: bytes) -> dict:
    header_len = struct.unpack('<I', data[4:8])[0]
    num = struct.unpack('<I', data[20:24])[0]
    mhsds = {}
    offset = header_len
    for _ in range(num):
        if offset >= len(data) or data[offset:offset + 4] != b'mhsd':
            break
        total_len = struct.unpack('<I', data[offset + 8:offset + 12])[0]
        mhsd_type = struct.unpack('<I', data[offset + 12:offset + 16])[0]
        mhsds[mhsd_type] = data[offset:offset + total_len]
        offset += total_len
    return mhsds


def dump_mhsd_header(label, data):
    print(f"  {label} MHSD:")
    print(f"    magic:      {data[0:4]}")
    print(f"    header_len: {struct.unpack('<I', data[4:8])[0]}")
    print(f"    total_len:  {struct.unpack('<I', data[8:12])[0]}")
    print(f"    type:       {struct.unpack('<I', data[12:16])[0]}")
    # Show next 16 bytes of header (padding/unknown)
    hdr_len = struct.unpack('<I', data[4:8])[0]
    if hdr_len > 16:
        print(f"    padding[16:{hdr_len}]: {data[16:min(hdr_len, 48)].hex()}")


def dump_child_header(label, data, offset):
    magic = data[offset:offset + 4]
    hdr_len = struct.unpack('<I', data[offset + 4:offset + 8])[0]
    print(f"  {label} child at offset {offset}:")
    print(f"    magic:      {magic}")
    print(f"    header_len: {hdr_len}")
    if magic in (b'mhlt', b'mhlp', b'mhla'):
        count = struct.unpack('<I', data[offset + 8:offset + 12])[0]
        print(f"    count:      {count}")
    elif magic in (b'mhit', b'mhyp', b'mhia'):
        total = struct.unpack('<I', data[offset + 8:offset + 12])[0]
        num_mhods = struct.unpack('<I', data[offset + 12:offset + 16])[0]
        print(f"    total_len:  {total}")
        print(f"    num_mhods:  {num_mhods}")
    # Hex dump first 64 bytes
    end = min(offset + 64, len(data))
    hex_data = data[offset:end].hex()
    for i in range(0, len(hex_data), 32):
        off = offset + i // 2
        print(f"    0x{off:04X}: {hex_data[i:i + 32]}")


def dump_first_mhod(label, data, offset):
    """Find and dump first MHOD after given offset."""
    magic = data[offset:offset + 4]
    if magic != b'mhod':
        print(f"  {label}: Expected mhod at {offset}, got {magic}")
        return
    hdr_len = struct.unpack('<I', data[offset + 4:offset + 8])[0]
    total_len = struct.unpack('<I', data[offset + 8:offset + 12])[0]
    mhod_type = struct.unpack('<I', data[offset + 12:offset + 16])[0]
    print(f"  {label} MHOD at offset {offset}:")
    print(f"    header_len: {hdr_len}")
    print(f"    total_len:  {total_len}")
    print(f"    type:       {mhod_type}")
    # String sub-header
    if hdr_len >= 24:
        sh_offset = offset + hdr_len
        if sh_offset + 16 <= len(data):
            field1 = struct.unpack('<I', data[sh_offset:sh_offset + 4])[0]
            field2 = struct.unpack('<I', data[sh_offset + 4:sh_offset + 8])[0]
            field3 = struct.unpack('<I', data[sh_offset + 8:sh_offset + 12])[0]
            field4 = struct.unpack('<I', data[sh_offset + 12:sh_offset + 16])[0]
            print(f"    str_subhdr: [{field1}, {field2}, {field3}, {field4}]")
            # Try to decode string
            str_data = data[sh_offset + 16:sh_offset + 16 + field2]
            try:
                if field1 == 2:
                    decoded = str_data.decode('utf-8', errors='replace')
                else:
                    decoded = str_data.decode('utf-16-le', errors='replace')
                print(f"    string:     {decoded[:80]!r}")
            except Exception:
                print(f"    string:     (decode failed)")
    # Full hex dump
    end = min(offset + total_len, offset + 96)
    hex_data = data[offset:end].hex()
    for i in range(0, len(hex_data), 32):
        off = offset + i // 2
        print(f"    0x{off:04X}: {hex_data[i:i + 32]}")


def walk_chunks(data, start, end, depth=0, max_items=3):
    """Walk chunk structure and print hierarchy."""
    offset = start
    count = 0
    indent = "  " * depth
    while offset < end and count < max_items:
        if offset + 12 > len(data):
            break
        magic = data[offset:offset + 4]
        if magic == b'\x00\x00\x00\x00':
            break
        try:
            magic_str = magic.decode('ascii')
        except Exception:
            print(f"{indent}  [INVALID MAGIC at 0x{offset:04X}: {magic.hex()}]")
            break
        hdr_len = struct.unpack('<I', data[offset + 4:offset + 8])[0]

        # Chunks with total_len
        if magic in (b'mhsd', b'mhit', b'mhyp', b'mhip', b'mhod', b'mhia', b'mhii', b'mhni'):
            total_len = struct.unpack('<I', data[offset + 8:offset + 12])[0]
            extra = ""
            if magic == b'mhod':
                mhod_type = struct.unpack('<I', data[offset + 12:offset + 16])[0]
                extra = f" type={mhod_type}"
            elif magic == b'mhit':
                track_id = struct.unpack('<I', data[offset + 16:offset + 20])[0]
                num_mhods = struct.unpack('<I', data[offset + 12:offset + 16])[0]
                extra = f" trackID={track_id} mhods={num_mhods}"
            elif magic == b'mhyp':
                num_mhods = struct.unpack('<I', data[offset + 12:offset + 16])[0]
                num_items = struct.unpack('<I', data[offset + 16:offset + 20])[0]
                extra = f" mhods={num_mhods} items={num_items}"
            print(f"{indent}  {magic_str} hdr={hdr_len} total={total_len}{extra}")
            offset += total_len
        # List chunks (mhlt, mhlp, mhla) - no total_len, use children
        elif magic in (b'mhlt', b'mhlp', b'mhla'):
            child_count = struct.unpack('<I', data[offset + 8:offset + 12])[0]
            print(f"{indent}  {magic_str} hdr={hdr_len} children={child_count}")
            # Walk children
            child_offset = offset + hdr_len
            for _ in range(min(child_count, max_items)):
                if child_offset >= end:
                    break
                child_magic = data[child_offset:child_offset + 4]
                if child_magic in (b'mhit', b'mhyp', b'mhia'):
                    child_total = struct.unpack('<I', data[child_offset + 8:child_offset + 12])[0]
                    walk_chunks(data, child_offset, child_offset + child_total, depth + 1, max_items=2)
                    child_offset += child_total
                else:
                    break
            if child_count > max_items:
                print(f"{indent}    ... ({child_count - max_items} more)")
            offset = end  # List chunks fill their parent MHSD
        else:
            print(f"{indent}  {magic_str} hdr={hdr_len}")
            offset += hdr_len
        count += 1


def main():
    clean = CLEAN_DB.read_bytes()
    test = TEST_DB.read_bytes()

    clean_mhsds = extract_mhsds(clean)
    test_mhsds = extract_mhsds(test)

    NAMES = {1: "Tracks", 2: "Playlists", 3: "Podcasts", 4: "Albums", 5: "SmartPL"}

    for t in sorted(set(clean_mhsds.keys()) | set(test_mhsds.keys())):
        name = NAMES.get(t, f"Type {t}")
        print(f"\n{'=' * 70}")
        print(f"MHSD TYPE {t} ({name})")
        print('=' * 70)

        if t in clean_mhsds:
            c = clean_mhsds[t]
            print(f"\n--- CLEAN ---")
            dump_mhsd_header("Clean", c)
            hdr_len = struct.unpack('<I', c[4:8])[0]
            walk_chunks(c, hdr_len, len(c), max_items=3)

        if t in test_mhsds:
            d = test_mhsds[t]
            print(f"\n--- TEST ---")
            dump_mhsd_header("Test", d)
            hdr_len = struct.unpack('<I', d[4:8])[0]
            walk_chunks(d, hdr_len, len(d), max_items=3)

        # Compare MHSD headers byte-by-byte
        if t in clean_mhsds and t in test_mhsds:
            c = clean_mhsds[t]
            d = test_mhsds[t]
            c_hdr_len = struct.unpack('<I', c[4:8])[0]
            d_hdr_len = struct.unpack('<I', d[4:8])[0]
            if c_hdr_len != d_hdr_len:
                print(f"\n  *** MHSD HEADER LENGTH MISMATCH: clean={c_hdr_len} test={d_hdr_len} ***")
            else:
                diffs = []
                for i in range(c_hdr_len):
                    if c[i] != d[i]:
                        diffs.append(i)
                if diffs:
                    print(f"\n  MHSD header byte diffs at: {diffs[:20]}")


if __name__ == "__main__":
    main()
