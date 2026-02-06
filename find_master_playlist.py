"""
Find master playlist specifically in MHSD type 2 (not podcasts).
"""

import struct

CLEAN_ITDB = r"C:\Users\JohnG\Music\cleanipod\iPod_Control\iTunes\iTunesDB"
TEST_ITDB = r"C:\Users\JohnG\Music\testing\iPod_Control\iTunes\iTunesDB"


def find_master_playlist(itdb_path: str, label: str):
    """Find the master playlist (first MHYP in MHSD type 2)."""
    with open(itdb_path, 'rb') as f:
        data = f.read()

    print(f"\n{'=' * 70}")
    print(f"{label}: Looking for Master Playlist in MHSD type 2")
    print('=' * 70)

    # First, find all MHSDs and locate type 2
    if data[0:4] != b'mhbd':
        print("ERROR: Not a valid iTunesDB!")
        return

    mhbd_header_len = struct.unpack_from('<I', data, 4)[0]

    # Find MHSD type 2
    offset = mhbd_header_len
    mhsd_type2_start = None
    mhsd_type2_end = None

    while offset < len(data) - 4:
        if data[offset:offset + 4] == b'mhsd':
            mhsd_header_len = struct.unpack_from('<I', data, offset + 4)[0]
            mhsd_total_len = struct.unpack_from('<I', data, offset + 8)[0]
            mhsd_type = struct.unpack_from('<I', data, offset + 12)[0]

            print(f"Found MHSD type {mhsd_type} at 0x{offset:X} (total_len={mhsd_total_len})")

            if mhsd_type == 2:
                mhsd_type2_start = offset
                mhsd_type2_end = offset + mhsd_total_len
                print(f"  -> This is MHSD type 2 (playlists)!")

            offset += mhsd_total_len
        else:
            break

    if mhsd_type2_start is None:
        print("ERROR: Could not find MHSD type 2!")
        return

    # Now find MHYP within MHSD type 2
    # The mhlp header should come right after the mhsd header
    mhsd_header_len = struct.unpack_from('<I', data, mhsd_type2_start + 4)[0]
    mhlp_offset = mhsd_type2_start + mhsd_header_len

    if data[mhlp_offset:mhlp_offset + 4] != b'mhlp':
        print(f"ERROR: Expected mhlp at 0x{mhlp_offset:X}")
        return

    mhlp_header_len = struct.unpack_from('<I', data, mhlp_offset + 4)[0]
    mhlp_count = struct.unpack_from('<I', data, mhlp_offset + 8)[0]

    print(f"\nMHLP at 0x{mhlp_offset:X}:")
    print(f"  header_len: {mhlp_header_len}")
    print(f"  playlist_count: {mhlp_count}")

    # Find first MHYP (master playlist)
    mhyp_offset = mhlp_offset + mhlp_header_len

    if data[mhyp_offset:mhyp_offset + 4] != b'mhyp':
        print(f"ERROR: Expected mhyp at 0x{mhyp_offset:X}, found {data[mhyp_offset:mhyp_offset + 4]}")
        return

    print(f"\nFirst MHYP (Master Playlist) at 0x{mhyp_offset:X}:")

    # Read MHYP header
    header_len = struct.unpack_from('<I', data, mhyp_offset + 4)[0]
    total_len = struct.unpack_from('<I', data, mhyp_offset + 8)[0]
    num_mhod = struct.unpack_from('<I', data, mhyp_offset + 0x0C)[0]
    num_items = struct.unpack_from('<I', data, mhyp_offset + 0x10)[0]
    hidden = struct.unpack_from('<I', data, mhyp_offset + 0x14)[0]
    timestamp = struct.unpack_from('<I', data, mhyp_offset + 0x18)[0]
    playlist_id = struct.unpack_from('<Q', data, mhyp_offset + 0x1C)[0]
    str_mhod_cnt = struct.unpack_from('<H', data, mhyp_offset + 0x28)[0]
    podcast_flag = struct.unpack_from('<H', data, mhyp_offset + 0x2A)[0]
    sort_order = struct.unpack_from('<I', data, mhyp_offset + 0x2C)[0]
    pl_type = data[mhyp_offset + 0x30]

    print(f"  header_len: {header_len}")
    print(f"  total_len: {total_len}")
    print(f"  num_mhod: {num_mhod}")
    print(f"  num_items: {num_items}")
    print(f"  hidden: {hidden}")
    print(f"  timestamp: {timestamp}")
    print(f"  playlist_id: 0x{playlist_id:016X}")
    print(f"  str_mhod_count: {str_mhod_cnt}")
    print(f"  podcast_flag: {podcast_flag}")
    print(f"  sort_order: {sort_order}")
    print(f"  playlist_type: {pl_type}")

    # Now iterate through MHODs
    mhod_offset = mhyp_offset + header_len
    mhod_count = 0

    print(f"\n  MHODs:")

    while mhod_count < num_mhod and mhod_offset < mhsd_type2_end:
        if data[mhod_offset:mhod_offset + 4] != b'mhod':
            print(f"    WARNING: Expected MHOD at 0x{mhod_offset:X}, found {data[mhod_offset:mhod_offset + 4]}")
            break

        mhod_header_len = struct.unpack_from('<I', data, mhod_offset + 4)[0]
        mhod_total_len = struct.unpack_from('<I', data, mhod_offset + 8)[0]
        mhod_type = struct.unpack_from('<I', data, mhod_offset + 12)[0]

        type_name = {
            1: "TITLE",
            50: "SPLPREF",
            51: "SPLRULES",
            52: "LIBPLAYLISTINDEX",
            53: "LIBPLAYLISTJUMPTABLE",
            100: "PLAYLIST",
            102: "ALBUM_ALBUM",
        }.get(mhod_type, f"UNKNOWN")

        extra = ""
        if mhod_type in (52, 53):
            sort_type = struct.unpack_from('<I', data, mhod_offset + 24)[0]
            sort_names = {3: "TITLE", 4: "ALBUM", 5: "ARTIST", 7: "GENRE", 0x12: "COMPOSER", 29: "SERIES", 30: "SERIES_SEASON", 31: "SERIES_EPISODE", 35: "UNK35", 36: "UNK36"}
            extra = f" sort={sort_names.get(sort_type, sort_type)}"

        print(f"    #{mhod_count + 1}: type {mhod_type:3d} ({type_name}){extra} total_len={mhod_total_len}")

        mhod_offset += mhod_total_len
        mhod_count += 1


if __name__ == "__main__":
    find_master_playlist(CLEAN_ITDB, "CLEAN")
    find_master_playlist(TEST_ITDB, "TEST")
