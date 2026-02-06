"""
Compare MHYP headers byte-by-byte between clean and test databases.
"""

import struct

CLEAN_ITDB = r"C:\Users\JohnG\Music\cleanipod\iPod_Control\iTunes\iTunesDB"
TEST_ITDB = r"C:\Users\JohnG\Music\testing\iPod_Control\iTunes\iTunesDB"


def find_first_mhyp(data: bytes) -> int:
    """Find offset of first MHYP in data."""
    return data.find(b'mhyp')


def read_mhyp_header(data: bytes, offset: int, label: str):
    """Read and display MHYP header fields."""
    print(f"\n{'=' * 70}")
    print(f"{label} - MHYP at offset 0x{offset:X}")
    print('=' * 70)

    # Read the full header (108 bytes for libgpod, up to 184 for iTunes)
    header_len = struct.unpack_from('<I', data, offset + 4)[0]

    # Hex dump of first 64 bytes
    print("\nHex dump of MHYP header (first 64 bytes):")
    for row in range(4):
        row_offset = row * 16
        hex_str = ' '.join(f'{data[offset + row_offset + i]:02X}' for i in range(16))
        ascii_str = ''.join(chr(data[offset + row_offset + i]) if 32 <= data[offset + row_offset + i] < 127 else '.' for i in range(16))
        print(f"  0x{row_offset:02X}: {hex_str}  {ascii_str}")

    # Parse known fields
    fields = [
        (0x00, 4, "magic", "4s"),
        (0x04, 4, "header_len", "<I"),
        (0x08, 4, "total_len", "<I"),
        (0x0C, 4, "num_mhod", "<I"),
        (0x10, 4, "num_items", "<I"),
        (0x14, 1, "type (libgpod reads as 8-bit)", "B"),
        (0x15, 1, "flag1", "B"),
        (0x16, 1, "flag2", "B"),
        (0x17, 1, "flag3", "B"),
        (0x18, 4, "timestamp", "<I"),
        (0x1C, 8, "playlist_id", "<Q"),
        (0x24, 4, "unknown_0x24", "<I"),
        (0x28, 2, "str_mhod_count", "<H"),
        (0x2A, 2, "podcastflag", "<H"),
        (0x2C, 4, "sortorder", "<I"),
    ]

    print("\nParsed fields:")
    for off, size, name, fmt in fields:
        if fmt == "4s":
            val = data[offset + off:offset + off + size]
            print(f"  0x{off:02X} {name:25s} = {val}")
        elif size == 1:
            val = data[offset + off]
            print(f"  0x{off:02X} {name:25s} = {val} (0x{val:02X})")
        elif size == 2:
            val = struct.unpack_from(fmt, data, offset + off)[0]
            print(f"  0x{off:02X} {name:25s} = {val} (0x{val:04X})")
        elif size == 4:
            val = struct.unpack_from(fmt, data, offset + off)[0]
            print(f"  0x{off:02X} {name:25s} = {val} (0x{val:08X})")
        elif size == 8:
            val = struct.unpack_from(fmt, data, offset + off)[0]
            print(f"  0x{off:02X} {name:25s} = {val} (0x{val:016X})")

    # Bytes 0x30-0x3F (the contentious area)
    print("\nBytes 0x30-0x6B (after libgpod's standard header at 0x30):")
    for row in range(4):
        row_offset = 0x30 + row * 16
        hex_str = ' '.join(f'{data[offset + row_offset + i]:02X}' for i in range(16))
        print(f"  0x{row_offset:02X}: {hex_str}")


def main():
    with open(CLEAN_ITDB, 'rb') as f:
        clean_data = f.read()

    with open(TEST_ITDB, 'rb') as f:
        test_data = f.read()

    # Find first MHYP in each
    clean_mhyp = find_first_mhyp(clean_data)
    test_mhyp = find_first_mhyp(test_data)

    print(f"Clean MHYP found at: 0x{clean_mhyp:X}")
    print(f"Test MHYP found at: 0x{test_mhyp:X}")

    read_mhyp_header(clean_data, clean_mhyp, "CLEAN")
    read_mhyp_header(test_data, test_mhyp, "TEST")

    # Compare header bytes
    print("\n" + "=" * 70)
    print("COMPARISON - First 64 bytes of MHYP header")
    print("=" * 70)

    clean_header = clean_data[clean_mhyp:clean_mhyp + 64]
    test_header = test_data[test_mhyp:test_mhyp + 64]

    print("\nDifferences (offset, clean_byte, test_byte):")
    diffs = []
    for i in range(64):
        if clean_header[i] != test_header[i]:
            diffs.append((i, clean_header[i], test_header[i]))
            print(f"  0x{i:02X}: clean=0x{clean_header[i]:02X}, test=0x{test_header[i]:02X}")

    if not diffs:
        print("  No differences in first 64 bytes!")


if __name__ == "__main__":
    main()
