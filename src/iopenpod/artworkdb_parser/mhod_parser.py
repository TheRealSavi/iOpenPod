import struct

from iopenpod.artworkdb_shared.mhod import decode_mhod_string_body, mhod_type_info


def parse_mhod(data, offset, header_length, chunk_length) -> dict:
    from .chunk_parser import parse_chunk

    dataObject = {}

    dataObject["mhodType"] = struct.unpack(
        "<H", data[offset + 12: offset + 14])[0]

    # unk0 = struct.unpack("<B", data[offset + 14: offset + 15])[0]  # always 0

    # paddingLength = struct.unpack("<B", data[offset + 15: offset + 16])[0]
    # all MHOD pad to be be a multiple of 4. the length will be 0,1,3

    # There is a bug in the iPod code that causes an MHBA to have an MHOD
    # of type 2 that is ont a container but is actually a string

    # MHOD type 2 contain a MHNI that cotains a MHOD type 3 with a thmbnl ref
    # MHOD type 5 contain a MHNI that cotains a MHOD type 3 with a fulrez ref

    type_info = mhod_type_info(dataObject["mhodType"])
    if type_info is None:
        return {
            "nextOffset": offset + chunk_length,
            "result": {"mhodType": dataObject["mhodType"], "_unknown": True},
        }

    match type_info["type"]:
        case "String":
            content_offset = offset + header_length

            string_decode = decode_mhod_string_body(
                data,
                content_offset,
                offset + chunk_length,
            ) or ""

            dataObject[type_info["name"]] = string_decode

            return {"nextOffset": offset + chunk_length, "result": dataObject}
        case "Container":

            # parse children (MHNI)
            next_offset = offset + header_length
            childResult = parse_chunk(data, next_offset)

            dataObject[type_info["name"]] = childResult

            return {"nextOffset": offset + chunk_length, "result": dataObject}

        case _:
            return {
                "nextOffset": offset + chunk_length,
                "result": {"mhodType": "ERROR"},
            }
