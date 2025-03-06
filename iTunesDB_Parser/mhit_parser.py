import struct

def parse_trackItem(data, offset, header_length, chunk_length) -> dict:    
    from .chunk_parser import parse_chunk
    from .constants import mhod_type_map

    childCount = struct.unpack("<I", data[offset+12:offset+16])[0]
    track_id  = struct.unpack("<I", data[offset+16:offset+20])[0]
    #used for playlists
    
    dbid = struct.unpack("<Q", data[offset+112:offset+120])[0]
    #the unique identifier
    
    albumid = struct.unpack("<H", data[offset+314:offset+316])[0]
    #the album identifier
    
    mhii_link = struct.unpack("<I", data[offset+352:offset+356])[0]
    #the link to the album art

    #much much more data...
    #TODO: Finish implementing track data

    track = {}
    
    track["trackID"] = track_id
    track["dbid"] = dbid
    track["albumID"] = albumid
    track["mhiiLink"] = mhii_link

    #Parse Children
    next_offset = offset+header_length
    for i in range(childCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]

        trackData = response["result"]
        track[mhod_type_map[trackData["mhodType"]]] = trackData["string"]

    return {"nextOffset": offset+chunk_length, "result": track}