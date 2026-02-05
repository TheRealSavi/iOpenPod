import struct


def parse_mhsd(data, offset, header_length, chunk_length) -> dict:
    from .chunk_parser import parse_chunk

    datasetType = struct.unpack("<I", data[offset + 12:offset + 16])[0]

    # Parse Child
    next_offset = offset + header_length
    childResult = parse_chunk(data, next_offset)
    # Extract the actual result from the wrapper
    result = childResult.get("result", childResult)
    return {"datasetType": datasetType, "result": result, "nextOffset": offset + chunk_length}
