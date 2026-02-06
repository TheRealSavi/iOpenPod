"""Compare clean vs synced iTunesDB to find issues."""
import struct

clean_path = r"C:\Users\JohnG\Music\cleanipod\iPod_Control\iTunes\iTunesDB"
synced_path = r"C:\Users\JohnG\Music\testing\iPod_Control\iTunes\iTunesDB"


def hex_dump(data, start, length, label):
    """Print hex dump of data section."""
    print(f"\n{label} (offset 0x{start:X}, {length} bytes):")
    chunk = data[start:start + length]
    hex_str = " ".join(f"{b:02X}" for b in chunk)
    print(f"  {hex_str}")


def analyze_mhbd(data, label):
    """Analyze MHBD header."""
    print(f"\n{'=' * 60}")
    print(f"=== {label} ===")
    print(f"{'=' * 60}")

    print(f"Magic: {data[0:4]}")
    header_len = struct.unpack("<I", data[4:8])[0]
    total_len = struct.unpack("<I", data[8:12])[0]
    unk_0c = struct.unpack("<I", data[12:16])[0]
    version = struct.unpack("<I", data[16:20])[0]
    child_count = struct.unpack("<I", data[20:24])[0]
    db_id = struct.unpack("<Q", data[24:32])[0]
    platform = struct.unpack("<H", data[32:34])[0]
    unk_22 = struct.unpack("<H", data[34:36])[0]

    print(f"Header length: {header_len} (0x{header_len:X})")
    print(f"Total length: {total_len} (file size: {len(data)})")
    print(f"unk_0x0C: {unk_0c}")
    print(f"Version: 0x{version:X}")
    print(f"Child count: {child_count}")
    print(f"DB ID: 0x{db_id:016X}")
    print(f"Platform: {platform}")
    print(f"unk_0x22: {unk_22}")

    # More fields
    unk_24 = struct.unpack("<Q", data[36:44])[0]
    print(f"unk_0x24 (at 36): 0x{unk_24:016X}")

    # Check hash fields
    hash_scheme = struct.unpack("<H", data[0x46:0x48])[0] if header_len > 0x46 else 0
    print(f"Hash scheme (0x46): {hash_scheme}")

    # Language
    if header_len >= 0x48:
        lang = data[0x46:0x48]
        print(f"Language bytes at 0x46: {lang}")

    # Dump first 100 bytes
    hex_dump(data, 0, min(100, header_len), "First 100 bytes of header")

    return header_len


def analyze_mhsd(data, offset, label):
    """Analyze MHSD at offset."""
    magic = data[offset:offset + 4]
    header_len = struct.unpack("<I", data[offset + 4:offset + 8])[0]
    total_len = struct.unpack("<I", data[offset + 8:offset + 12])[0]
    ds_type = struct.unpack("<I", data[offset + 12:offset + 16])[0]

    print(f"\n  MHSD at 0x{offset:X}: type={ds_type}, header={header_len}, total={total_len}")

    # Look at child chunk
    child_offset = offset + header_len
    child_magic = data[child_offset:child_offset + 4]
    child_header = struct.unpack("<I", data[child_offset + 4:child_offset + 8])[0]
    child_count_field = struct.unpack("<I", data[child_offset + 8:child_offset + 12])[0]
    print(f"    Child: {child_magic}, header={child_header}, count/len={child_count_field}")

    return offset + total_len


def analyze_first_mhit(data, mhlt_offset, label):
    """Find and analyze first MHIT."""
    # MHLT header
    mhlt_header_len = struct.unpack("<I", data[mhlt_offset + 4:mhlt_offset + 8])[0]
    track_count = struct.unpack("<I", data[mhlt_offset + 8:mhlt_offset + 12])[0]

    if track_count == 0:
        print(f"\n  No tracks in MHLT")
        return

    # First MHIT
    mhit_offset = mhlt_offset + mhlt_header_len
    magic = data[mhit_offset:mhit_offset + 4]
    if magic != b'mhit':
        print(f"\n  Expected mhit but got {magic}")
        return

    mhit_header_len = struct.unpack("<I", data[mhit_offset + 4:mhit_offset + 8])[0]
    mhit_total_len = struct.unpack("<I", data[mhit_offset + 8:mhit_offset + 12])[0]
    mhod_count = struct.unpack("<I", data[mhit_offset + 12:mhit_offset + 16])[0]
    track_id = struct.unpack("<I", data[mhit_offset + 16:mhit_offset + 20])[0]
    visible = struct.unpack("<I", data[mhit_offset + 20:mhit_offset + 24])[0]

    print(f"\n  First MHIT at 0x{mhit_offset:X}:")
    print(f"    Header len: {mhit_header_len} (0x{mhit_header_len:X})")
    print(f"    Total len: {mhit_total_len}")
    print(f"    MHOD count: {mhod_count}")
    print(f"    Track ID: {track_id}")
    print(f"    Visible: {visible}")

    # Key fields
    dbid = struct.unpack("<Q", data[mhit_offset + 0x70:mhit_offset + 0x78])[0]
    print(f"    DBID (0x70): 0x{dbid:016X}")

    media_type = struct.unpack("<I", data[mhit_offset + 0xD0:mhit_offset + 0xD4])[0]
    print(f"    Media type (0xD0): {media_type}")

    # Dump some of the header
    hex_dump(data, mhit_offset, 64, "First 64 bytes of MHIT")


# Load both databases
with open(clean_path, 'rb') as f:
    clean_data = f.read()

with open(synced_path, 'rb') as f:
    synced_data = f.read()

# Analyze clean
clean_header_len = analyze_mhbd(clean_data, "CLEAN (working)")

# Find MHSDs in clean
print("\n--- MHSD analysis (CLEAN) ---")
offset = clean_header_len
for i in range(3):
    if offset < len(clean_data) and clean_data[offset:offset + 4] == b'mhsd':
        offset = analyze_mhsd(clean_data, offset, f"MHSD {i + 1}")
    else:
        break

# Find first track
print("\n--- First track (CLEAN) ---")
mhsd1_offset = clean_header_len
mhsd1_header = struct.unpack("<I", clean_data[mhsd1_offset + 4:mhsd1_offset + 8])[0]
mhlt_offset = mhsd1_offset + mhsd1_header
analyze_first_mhit(clean_data, mhlt_offset, "CLEAN")

# Analyze synced
synced_header_len = analyze_mhbd(synced_data, "SYNCED (broken)")

# Find MHSDs in synced
print("\n--- MHSD analysis (SYNCED) ---")
offset = synced_header_len
for i in range(3):
    if offset < len(synced_data) and synced_data[offset:offset + 4] == b'mhsd':
        offset = analyze_mhsd(synced_data, offset, f"MHSD {i + 1}")
    else:
        break

# Find first track
print("\n--- First track (SYNCED) ---")
mhsd1_offset = synced_header_len
mhsd1_header = struct.unpack("<I", synced_data[mhsd1_offset + 4:mhsd1_offset + 8])[0]
mhlt_offset = mhsd1_offset + mhsd1_header
analyze_first_mhit(synced_data, mhlt_offset, "SYNCED")

print("\n" + "=" * 60)
print("COMPARISON SUMMARY")
print("=" * 60)
print(f"Clean file size: {len(clean_data)}")
print(f"Synced file size: {len(synced_data)}")
