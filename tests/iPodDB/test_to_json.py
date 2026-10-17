import json
import struct

from tests.iPodDB.binary_fixtures import parse_mhod

from iPodDB.shared.to_json import chunk_to_json


def _smart_rule(field_id: int, action_id: int, data: bytes) -> bytes:
    return (
        struct.pack(">III", field_id, action_id, 0)
        + bytes(40)
        + struct.pack(">I", len(data))
        + data
    )


def test_chunk_to_json_serializes_smart_playlist_rules() -> None:
    body = (
        b"SLst"
        + struct.pack(">III", 0x00010001, 1, 0)
        + bytes(120)
        + _smart_rule(0x04, 0x01000002, "Miles".encode("utf-16-be"))
    )

    document = json.loads(chunk_to_json(parse_mhod(51, body)))

    (rule,) = document["payload"]["rules"]
    assert rule["field_id"] == 0x04
    assert rule["action_id"] == 0x01000002
    assert rule["data"]["value"] == "Miles"
