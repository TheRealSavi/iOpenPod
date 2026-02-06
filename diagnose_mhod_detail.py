"""
Deep byte-level comparison of first MHIT + MHODs between clean and test.
"""
import struct
from pathlib import Path

CLEAN_DB = Path(r"C:\Users\JohnG\Music\cleanipod\iPod_Control\iTunes\iTunesDB")
TEST_DB = Path(r"C:\Users\JohnG\Music\testing\iPod_Control\iTunes\iTunesDB")


def extract_mhsds(data):
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


def find_first_item(mhsd_data, item_magic):
    """Find first child item (mhit/mhyp/mhia) in an MHSD."""
    hdr_len = struct.unpack('<I', mhsd_data[4:8])[0]
    # Skip to child list (mhlt/mhlp/mhla)
    list_offset = hdr_len
    list_hdr_len = struct.unpack('<I', mhsd_data[list_offset + 4:list_offset + 8])[0]
    item_offset = list_offset + list_hdr_len
    if mhsd_data[item_offset:item_offset + 4] == item_magic:
        total_len = struct.unpack('<I', mhsd_data[item_offset + 8:item_offset + 12])[0]
        return mhsd_data[item_offset:item_offset + total_len]
    return None


def dump_mhods(label, item_data):
    """Dump all MHODs within an item."""
    hdr_len = struct.unpack('<I', item_data[4:8])[0]
    total_len = struct.unpack('<I', item_data[8:12])[0]
    num_mhods = struct.unpack('<I', item_data[12:16])[0]

    print(f"\n  {label}: {num_mhods} MHODs, hdr_len={hdr_len}, total_len={total_len}")

    offset = hdr_len
    for i in range(num_mhods):
        if offset >= total_len:
            break
        magic = item_data[offset:offset + 4]
        if magic != b'mhod':
            print(f"    MHOD {i}: UNEXPECTED MAGIC {magic} at offset {offset}")
            break
        mhod_hdr_len = struct.unpack('<I', item_data[offset + 4:offset + 8])[0]
        mhod_total = struct.unpack('<I', item_data[offset + 8:offset + 12])[0]
        mhod_type = struct.unpack('<I', item_data[offset + 12:offset + 16])[0]

        TYPE_NAMES = {
            1: "Title", 2: "Location", 3: "Album", 4: "Artist",
            5: "Genre", 6: "Filetype", 7: "EQ", 8: "Comment",
            12: "Composer", 13: "Grouping", 22: "AlbumArtist",
            23: "SortArtist", 27: "SortName", 28: "SortAlbum",
            29: "SortAlbumArtist", 30: "SortComposer", 31: "SortShow",
            50: "SmartData", 51: "SmartRules", 52: "LibPlaylistIdx",
            100: "PlaylistPos",
        }
        type_name = TYPE_NAMES.get(mhod_type, f"Unk{mhod_type}")

        # Parse string sub-header if string type
        string_info = ""
        if mhod_type < 50 and mhod_hdr_len + 16 <= mhod_total:
            sh = offset + mhod_hdr_len
            field1 = struct.unpack('<I', item_data[sh:sh + 4])[0]      # encoding/position
            field2 = struct.unpack('<I', item_data[sh + 4:sh + 8])[0]    # string_len
            field3 = struct.unpack('<I', item_data[sh + 8:sh + 12])[0]   # unk
            field4 = struct.unpack('<I', item_data[sh + 12:sh + 16])[0]  # unk

            str_data = item_data[sh + 16:sh + 16 + field2]
            try:
                if field1 == 2:
                    decoded = str_data.decode('utf-8', errors='replace')
                else:
                    decoded = str_data.decode('utf-16-le', errors='replace')
            except Exception:
                decoded = "(decode error)"
            string_info = f" subhdr=[{field1},{field2},{field3},{field4}] str={decoded[:60]!r}"

        # Hex dump of first 48 bytes
        hex_preview = item_data[offset:offset + min(48, mhod_total)].hex()

        print(f"    MHOD {i}: type={mhod_type:3d} ({type_name:15s}) hdr={mhod_hdr_len} total={mhod_total}{string_info}")
        print(f"           hex: {hex_preview[:64]}")
        if len(hex_preview) > 64:
            print(f"                {hex_preview[64:]}")

        offset += mhod_total


def compare_mhit_headers(clean_item, test_item):
    """Compare MHIT header fields."""
    c_hdr = struct.unpack('<I', clean_item[4:8])[0]
    t_hdr = struct.unpack('<I', test_item[4:8])[0]

    print(f"\n  MHIT header comparison (clean_hdr={c_hdr}, test_hdr={t_hdr}):")

    # Compare all 4-byte chunks
    max_off = min(c_hdr, t_hdr)
    diff_count = 0
    for off in range(0, max_off, 4):
        c_val = clean_item[off:off + 4]
        t_val = test_item[off:off + 4]
        if c_val != t_val:
            c_int = struct.unpack('<I', c_val)[0]
            t_int = struct.unpack('<I', t_val)[0]
            print(f"    0x{off:03X}: clean=0x{c_int:08X} ({c_int:10d})  test=0x{t_int:08X} ({t_int:10d})")
            diff_count += 1
    print(f"  Total diffs: {diff_count}")


def compare_mhyp_structure(clean_item, test_item):
    """Compare playlist structure."""
    c_hdr = struct.unpack('<I', clean_item[4:8])[0]
    c_total = struct.unpack('<I', clean_item[8:12])[0]
    c_mhods = struct.unpack('<I', clean_item[12:16])[0]
    c_items = struct.unpack('<I', clean_item[16:20])[0]

    t_hdr = struct.unpack('<I', test_item[4:8])[0]
    t_total = struct.unpack('<I', test_item[8:12])[0]
    t_mhods = struct.unpack('<I', test_item[12:16])[0]
    t_items = struct.unpack('<I', test_item[16:20])[0]

    print(f"\n  MHYP comparison:")
    print(f"    Clean: hdr={c_hdr} total={c_total} mhods={c_mhods} items={c_items}")
    print(f"    Test:  hdr={t_hdr} total={t_total} mhods={t_mhods} items={t_items}")

    # Compare header fields
    max_off = min(c_hdr, t_hdr)
    for off in range(0, max_off, 4):
        c_val = clean_item[off:off + 4]
        t_val = test_item[off:off + 4]
        if c_val != t_val:
            c_int = struct.unpack('<I', c_val)[0]
            t_int = struct.unpack('<I', t_val)[0]
            print(f"    0x{off:03X}: clean=0x{c_int:08X}  test=0x{t_int:08X}")


def main():
    clean = CLEAN_DB.read_bytes()
    test = TEST_DB.read_bytes()

    clean_mhsds = extract_mhsds(clean)
    test_mhsds = extract_mhsds(test)

    # === Compare first MHIT ===
    print("=" * 70)
    print("FIRST MHIT + MHODs COMPARISON")
    print("=" * 70)

    c_mhit = find_first_item(clean_mhsds[1], b'mhit')
    t_mhit = find_first_item(test_mhsds[1], b'mhit')

    if c_mhit and t_mhit:
        compare_mhit_headers(c_mhit, t_mhit)
        dump_mhods("Clean", c_mhit)
        dump_mhods("Test", t_mhit)

    # === Compare first MHYP (playlist) ===
    print("\n" + "=" * 70)
    print("FIRST MHYP (MASTER PLAYLIST) COMPARISON")
    print("=" * 70)

    c_mhyp = find_first_item(clean_mhsds[2], b'mhyp')
    t_mhyp = find_first_item(test_mhsds[2], b'mhyp')

    if c_mhyp and t_mhyp:
        compare_mhyp_structure(c_mhyp, t_mhyp)
        dump_mhods("Clean", c_mhyp)
        dump_mhods("Test", t_mhyp)

    # === Compare first MHIA (album) ===
    print("\n" + "=" * 70)
    print("FIRST MHIA (ALBUM) COMPARISON")
    print("=" * 70)

    c_mhia = find_first_item(clean_mhsds[4], b'mhia')
    t_mhia = find_first_item(test_mhsds[4], b'mhia')

    if c_mhia and t_mhia:
        c_hdr = struct.unpack('<I', c_mhia[4:8])[0]
        t_hdr = struct.unpack('<I', t_mhia[4:8])[0]
        c_total = struct.unpack('<I', c_mhia[8:12])[0]
        t_total = struct.unpack('<I', t_mhia[8:12])[0]
        print(f"\n  Clean MHIA: hdr={c_hdr} total={c_total}")
        print(f"  Test MHIA:  hdr={t_hdr} total={t_total}")

        # Compare headers
        max_off = min(c_hdr, t_hdr)
        for off in range(0, max_off, 4):
            c_val = c_mhia[off:off + 4]
            t_val = t_mhia[off:off + 4]
            if c_val != t_val:
                c_int = struct.unpack('<I', c_val)[0]
                t_int = struct.unpack('<I', t_val)[0]
                print(f"    0x{off:03X}: clean=0x{c_int:08X}  test=0x{t_int:08X}")

        dump_mhods("Clean", c_mhia)
        dump_mhods("Test", t_mhia)

    # === Check clean MHSD type 3 vs type 2 ===
    print("\n" + "=" * 70)
    print("CLEAN: TYPE 3 vs TYPE 2 (are they identical?)")
    print("=" * 70)
    if clean_mhsds[3] == clean_mhsds[2]:
        print("  YES - Clean type 3 (podcasts) is IDENTICAL to type 2 (playlists)")
    else:
        c2 = clean_mhsds[2]
        c3 = clean_mhsds[3]
        # Check if only MHSD type byte differs
        c2_mod = bytearray(c2)
        c2_mod[12:16] = struct.pack('<I', 3)
        if bytes(c2_mod) == c3:
            print("  They differ ONLY in the MHSD type field (2 vs 3)")
        else:
            print(f"  Different: type2={len(c2)} bytes, type3={len(c3)} bytes")


if __name__ == "__main__":
    main()
