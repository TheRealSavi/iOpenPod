import struct


def parse_mhod(data, offset, header_length, chunk_length) -> dict:
    from .constants import mhod_type_map
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

    match mhod_type_map[dataObject["mhodType"]]["type"]:
        case "String":
            content_offset = offset + header_length

            stringByteLength = struct.unpack(
                "<I", data[content_offset: content_offset + 4])[0]

            # Encoding byte at content_offset+4 (ArtworkDB_MhodHeaderString.encoding)
            # Per libgpod db-itunes-parser.h: 0,1 = UTF-8; 2 = UTF-16-LE
            encoding = data[content_offset + 4]

            # content_offset+8: unknown (always 0)

            stringContent = data[
                content_offset + 12: content_offset + 12 + stringByteLength]

            # padding would be offset+stringByteLength:offset+paddingLength
            # but for the purposes of parsing it is not needed.

            if encoding == 2:
                string_decode = stringContent.decode("utf-16-le", errors="replace")
            else:
                string_decode = stringContent.decode("utf-8", errors="replace")

            dataObject[mhod_type_map[dataObject["mhodType"]]
                       ["name"]] = string_decode

            return {"nextOffset": offset + chunk_length, "result": dataObject}
        case "Container":

            # parse children (MHNI)
            next_offset = offset + header_length
            childResult = parse_chunk(data, next_offset)

            dataObject[mhod_type_map[dataObject["mhodType"]]
                       ["name"]] = childResult

            return {"nextOffset": offset + chunk_length, "result": dataObject}

        case _:
            return {
                "nextOffset": offset + chunk_length,
                "result": {"mhodType": "ERROR"},
            }
