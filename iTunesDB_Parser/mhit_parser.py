import struct

def parse_trackItem(data, offset, header_length, chunk_length) -> dict:    
    from .chunk_parser import parse_chunk
    from .constants import mhod_type_map

    childCount = struct.unpack("<I", data[offset+12:offset+16])[0]
    track_id  = struct.unpack("<I", data[offset+16:offset+20])[0]

    #much much more data...
    #TODO: Finish implementing track data

    track = {}

    #Parse Children
    next_offset = offset+header_length
    for i in range(childCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]

        trackData = response["result"]
        track[mhod_type_map[trackData["mhodType"]]] = trackData["string"]

    return {"nextOffset": offset+chunk_length, "result": track}