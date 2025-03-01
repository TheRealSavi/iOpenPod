import struct

def parse_albumItem(data, offset, header_length, chunk_length) -> dict:    
    from .chunk_parser import parse_chunk
    from .constants import mhod_type_map

    childCount = struct.unpack("<I", data[offset+12:offset+16])[0]
    unk = struct.unpack("<H", data[offset+16:offset+18])[0] #prev long length 4 possible album id
    album_id_for_track = struct.unpack("<H", data[offset+18:offset+20])[0] #0x18+ prev long length 4
    unk2 = struct.unpack("<Q", data[offset+20:offset+28])[0] #timestamp? 0x18+ 
    unk3 = struct.unpack("<I", data[offset+28:offset+32])[0]  #always 2 0x18+
    
    album = {}

    #Parse Children
    next_offset = offset+header_length
    for i in range(childCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]

        albumData = response["result"]
        album[mhod_type_map[albumData["mhodType"]]] = albumData["string"]

    return {"nextOffset": offset+chunk_length, "result": album}