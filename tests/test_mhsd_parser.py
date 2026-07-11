from __future__ import annotations

import struct

from iopenpod.itunesdb_parser.mhsd_parser import parse_dataset
from iopenpod.itunesdb_shared.extraction import extract_datasets
from iopenpod.itunesdb_shared.mhsd_defs import MHSD_HEADER_SIZE


def test_mhsd_type9_genius_cuid_is_raw_payload_not_child_chunk() -> None:
    cuid = b"41bac68ce330182aeedfdc61bdb677e8"
    chunk = bytearray(MHSD_HEADER_SIZE + len(cuid))
    struct.pack_into("<4sII", chunk, 0, b"mhsd", MHSD_HEADER_SIZE, len(chunk))
    struct.pack_into("<I", chunk, 0x0C, 9)
    chunk[MHSD_HEADER_SIZE:] = cuid

    parsed = parse_dataset(chunk, 0, MHSD_HEADER_SIZE, len(chunk))["data"]

    assert parsed["children"] == []
    assert parsed["raw_payload"] == cuid
    assert parsed["genius_cuid"] == cuid.decode("ascii")


def test_extract_datasets_exposes_mhsd_type9_genius_cuid() -> None:
    raw = {
        "children": [
            {
                "data": {
                    "dataset_type": 9,
                    "raw_payload": b"41bac68ce330182aeedfdc61bdb677e8",
                    "genius_cuid": "41bac68ce330182aeedfdc61bdb677e8",
                    "children": [],
                }
            }
        ]
    }

    assert extract_datasets(raw)["mhsd_type_9"] == {
        "raw_payload_hex": "3431626163363863653333303138326165656466646336316264623637376538",
        "genius_cuid": "41bac68ce330182aeedfdc61bdb677e8",
    }
