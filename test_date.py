
import struct
import time
from iTunesDB_Writer.mhit_writer import TrackInfo, write_mhit
from iTunesDB_Parser.mhit_parser import _parse_mhit_header
from iTunesDB_Shared.mhit_defs import MHIT_HEADER_SIZE

# Mock track
track = TrackInfo(
    title="Test Track",
    location=":iPod_Control:Music:F00:TEST.mp3",
    date_released=1700000000, # 2023-11-14
    year=2023
)

# Write
print(f"Track date_released: {track.date_released}")
data = write_mhit(track, track_id=1, id_0x24=123)

# Inspect raw bytes at 0x8C
raw_val = struct.unpack_from("<I", data, 0x8C)[0]
print(f"Raw at 0x8C: {raw_val} (dec), {hex(raw_val)} (hex)")

# Expected Mac time: 1700000000 + 2082844800 = 3782844800
expected = 1700000000 + 2082844800
print(f"Expected: {expected}")

if raw_val == expected:
    print("Writer IS writing correct Mac timestamp.")
else:
    print("Writer FAIL.")

# Parse back
parsed = _parse_mhit_header(data, 0, MHIT_HEADER_SIZE)
parsed_date = parsed.get("date_released")
print(f"Parsed back: {parsed_date}")

if parsed_date == 1700000000:
    print("Round trip SUCCESS.")
else:
    print("Round trip FAIL.")
