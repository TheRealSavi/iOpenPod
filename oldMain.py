import json
import dearpygui.dearpygui as dpg
import struct

#Debug UI
dpg.create_context()

with dpg.font_registry():
    large_font = dpg.add_font("C:/Windows/Fonts/arial.ttf", 24)
dpg.bind_font(large_font)

with dpg.window(label="iOpenPod iTunesDB Parser", width=600, height=600):
    logWindowParse = dpg.add_text("Logs:\n")
    
def log_message(message):
    dpg.set_value(logWindowParse, f"{dpg.get_value(logWindowParse)}\n{message}")

#maps the id provided in the db header chunk to the actual chunk identifier
chunk_type_map = {
    1: "mhlt", #track list chunk
    2: "mhlp", #playlist list chunk
    3: "mhlp", #podcast list, same identifer as playlist, but has slight differnce
    4: "mhla", #Album Lists (iTunes 7.1>)
    5: "mhsp", #Smart playlist list (iTunes 7.3>)
}

#maps the chunk identifier to a readable name
#the identifier appears to be backward, I estimate that it should read something like DataBaseHeaderMarker(DBHM) and DataStructureHeaderMarker(DSHM) and TrackListHeaderMarker(TLHM)...
identifier_readable_map = {
    "mhbd": "Database",
    "mhsd": "Generic List Holder",
    "mhlt": "Track List",
    "mhlp": "Playlist or Podcast List",
    "mhla": "Album List",
    "mhsp": "Smart Playlist List",
    "mhia": "Album Item",
    "mhit": "Track Item",
    "mhyp": "Playlist Item",
    "mhod": "Data Object",
    "mhip": "Playlist Entry Item",
}

#maps the mhod type to a readable name
mhod_type_map = {
    1: "Track Title",
    2: "Location",
    3: "Album",
    4: "Artist",
    5: "Genre",
    6: "Filetype",
    7: "EQ Setting",
    8: "Comment",
    9: "Category",
    12: "Composer",
    13: "Grouping",
    14: "Description Text",
    15: "Podcast Enclosure URL",
    16: "Podcast RSS URL",
    17: "Chapter Data",
    18: "Subtitle",
    19: "Show",
    20: "Episode",
    21: "TV Network",
    22: "Album Artist",
    23: "Sort Artist",
    24: "Track Keywords",
    25: "Show Locale",
    27: "Sort Title",
    28: "Sort Album",
    29: "Sort Album Artist",
    30: "Sort Composer",
    31: "Sort Show",
    32: "Unknown for Video Track",
    50: "Smart Playlist Data",
    51: "Smart Playlist Rules",
    52: "Library Playlist Index",
    53: "Unknown similar to MHOD52",
    100: "Column Size or Playlist Order",
    200: "Album (Used by Album Item)",
    201: "Artist (Used by Album Item)",
    202: "Sort Artist (Used by Album Item)",
    203: "Podcast URL (Used by Album Item)",
    204: "Show (Used by Album Item)"
}

parseContainer = {}

#Entry point for parser, checks for an mhbd identifier in the first 4 bytes of file, and then iterates entire file.
def parse_itunesdb_header(file_path):
    log_message("Opening file...")
    
    with open(file_path, "rb") as f:
        data = f.read()

    chunk_type = data[0:4].decode("utf-8")

    if chunk_type != "mhbd":
        log_message("Invalid iTunesDB header")
        return
    log_message("Valid iTunesDB header detected.")

    header_length = struct.unpack("<I", data[4:8])[0]
    log_message(f"Header Length: {header_length} bytes")

    total_legnth = struct.unpack("<I", data[8:12])[0]
    log_message(f"Total Length:  {total_legnth} bytes")

    unknown_1 = struct.unpack("<I", data[12:16])[0] #always 1?

    version_number = struct.unpack("<I", data[16:20])[0]
    version_hex = hex(version_number)
    log_message(f"DB Version: {version_number} As Hex: {version_hex}")

    num_of_childs = struct.unpack("<I", data[20:24])[0]
    log_message(f"Child count: {num_of_childs}")

    db_id = struct.unpack("<Q", data[24:32])[0]
    log_message(f"DB ID: {db_id}")

    unknown_2 = struct.unpack("<H", data[32:34])[0] #always 2?


    padding = data[34:38] #nothing in docs for this


    unknown_3 = struct.unpack("<Q", data[38:46])[0] #version 0x11> unknown use


    padding_2 = data[46:48] #nothing in docs for this


    unknown_4 = struct.unpack("<H", data[48:50])[0] #version 0x19> must be 0x01 same as obscure_hash


    unknown_5 = data[50:70] #version 0x19> unknown meaning

    language_bytes = struct.unpack("<2s", data[70:72])[0] #version 0x13>
    language = language_bytes.decode("utf-8")


    lib_persist_id = struct.unpack("<Q", data[72:80]) #version 0x14>

    padding_3 = data[80:88] #nothin in docs

    obscure_hash = data[88:108] #version 0x19> 

    parseContainer["Header"] = {
        "Version": version_hex,
        "Lang": language,
        "Databse_id": db_id,
        "Library_id": lib_persist_id,
    }

    next_offset = header_length
    for i in range(num_of_childs):
        response = parse_chunk(data, next_offset)
        next_offset = response["next_offset"]
        parseContainer[identifier_readable_map[response["chunk_type"]]] = response["result"]
    log_message("Done parsing")
    with open("data.json", "w") as f:
        json.dump(parseContainer, f, indent=2)
    log_message("Data dumped")

    
    
def parse_chunk(data, offset):
    chunk_type = data[offset:offset+4].decode("utf-8")
    header_length = struct.unpack("<I", data[offset+4:offset+8])[0]
    chunk_length = struct.unpack("<I", data[offset+8:offset+12])[0]
    
    log_message(f"Parsing Chunk Type: {identifier_readable_map[chunk_type]}")
    log_message(f"Header length: {header_length} bytes")
    log_message(f"Chunk length: {chunk_length} bytes")

    data_type = struct.unpack("<I", data[offset+12:offset+16])[0]
    contain_chunk_type = chunk_type_map.get(data_type)

    log_message(f"Contains Chunk of type: {identifier_readable_map[contain_chunk_type]}")

    response = 0

    match contain_chunk_type:
        case "mhla":
            response = parse_album_list(data, offset+header_length)
            
        case "mhlt":
            response = parse_track_list(data, offset+header_length)
        
        case "mhlp":
            response = parse_plylstorpodcast(data, offset+header_length)
        
        case "mhsp":
            response = parse_smartplylst(data, offset+header_length)

    log_message(f"returning from: {identifier_readable_map[contain_chunk_type]} to head chunk")
    return {"next_offset": offset+chunk_length, "result": response, "chunk_type": contain_chunk_type}

def parse_album_list(data, offset):
    identifier = data[offset:offset+4].decode("UTF-8")
    log_message(f"Parsing: {identifier_readable_map[identifier]}")

    header_length = struct.unpack("<I", data[offset+4:offset+8])[0]
    num_of_albums = struct.unpack("<I", data[offset+8:offset+12])[0]

    log_message(f"Header length: {header_length} bytes")
    log_message(f"Contains {num_of_albums} Albums")

    albumList = []

    next_offset = offset+header_length
    for i in range(num_of_albums):
        response = parse_album_item(data, next_offset)
        next_offset = response["next_offset"]
        albumList.append(response["result"])

    return albumList
    



def parse_album_item(data, offset):
    identifier = data[offset:offset+4].decode("UTF-8")
    log_message(f"Parsing: {identifier_readable_map[identifier]}")

    header_length = struct.unpack("<I", data[offset+4:offset+8])[0]
    total_length = struct.unpack("<I", data[offset+8:offset+12])[0]

    num_of_mhod = struct.unpack("<I", data[offset+12:offset+16])[0]

    unknown = struct.unpack("<H", data[offset+16:offset+18])[0] #prev long length 4 possible album id
    album_id_for_track = struct.unpack("<H", data[offset+18:offset+20])[0] #v 0x18 prev long length 4
    
    unknown_2 = struct.unpack("<Q", data[offset+20:offset+28])[0] #timestamp>? v 0x18 
    unknown_3 = struct.unpack("<I", data[offset+28:offset+32])[0]  #always 2 v 0x18
    
    log_message(f"Header length: {header_length} bytes")
    log_message(f"Contains {num_of_mhod} Children")

    album = {}

    next_offset = offset+header_length
    for i in range(num_of_mhod):
        response = parse_mhod(data, next_offset)
        next_offset = response["next_offset"]

        albumData = response["result"]
        album[mhod_type_map[albumData["mhodType"]]] = albumData["string"]


    return {"next_offset": offset+total_length, "result": album}

def parse_track_list(data, offset):
    identifier = data[offset:offset+4].decode("UTF-8")
    log_message(f"Parsing: {identifier_readable_map[identifier]}")

    header_length = struct.unpack("<I", data[offset+4:offset+8])[0]
    num_of_track = struct.unpack("<I", data[offset+8:offset+12])[0]
    
    log_message(f"Header length: {header_length} bytes")
    log_message(f"Contains {num_of_track} Tracks")

    trackList = []

    next_offset = offset+header_length
    for i in range(num_of_track):
        response = parse_track_item(data, next_offset)
        next_offset = response["next_offset"]
        trackList.append(response["result"])
    
    return trackList

#TODO: Implement rest of track list data

def parse_track_item(data, offset):
    identifier = data[offset:offset+4].decode("UTF-8")
    log_message(f"Parsing: {identifier_readable_map[identifier]}")

    header_length = struct.unpack("<I", data[offset+4:offset+8])[0]
    total_length = struct.unpack("<I", data[offset+8:offset+12])[0]   

    num_of_mhod = struct.unpack("<I", data[offset+12:offset+16])[0]

    track_id  = struct.unpack("<I", data[offset+16:offset+20])[0]

    #much much more data...
    
    log_message(f"Header length: {header_length} bytes")
    log_message(f"Contains {num_of_mhod} Children")

    track = {}

    next_offset = offset+header_length
    for i in range(num_of_mhod):
        response = parse_mhod(data, next_offset)
        next_offset = response["next_offset"]
        trackData = response["result"]
        #TODO: parse track data into track
        track[mhod_type_map[trackData["mhodType"]]] = trackData["string"]

    return {"next_offset":offset+total_length, "result": track}


def parse_plylstorpodcast(data, offset):
    log_message("implement")
    return {}

def parse_smartplylst(data, offset):
    log_message("implement")
    return {}

#TODO: Implement the rest of mhods features
def parse_mhod(data, offset):
    identifier = data[offset:offset+4].decode("UTF-8")
    log_message(f"Parsing: {identifier_readable_map[identifier]}")

    header_length = struct.unpack("<I", data[offset+4:offset+8])[0]
    total_length = struct.unpack("<I", data[offset+8:offset+12])[0]

    mhod_type = struct.unpack("<I", data[offset+12:offset+16])[0]
    log_message(f"MHOD Type: {mhod_type_map[mhod_type]}")

    log_message(f"Header length: {header_length} bytes")
    log_message(f"Total length: {total_length} bytes")

    string_length = struct.unpack("<I", data[offset+28:offset+32])[0]
    encoding_flag = struct.unpack("<I", data[offset+32:offset+36])[0]  # Encoding hint (not always reliable)

    string_data = data[offset+40:offset+40+string_length]

    #guess encoding based on the presence of a null byte; its in every utf16 but very rare in utf8
    string_decode = ""
    if b'\x00' in string_data:
        string_decode = string_data.decode("utf-16-le")
    else:
        string_decode = string_data.decode("utf-8")

    log_message(f"Contains String: {string_decode}")


    return {"next_offset": offset+total_length, "result": {"mhodType": mhod_type, "string": string_decode}}


   

def start_parsing():
    parse_itunesdb_header(r"C:\Users\JohnG\Documents\Coding Projects\iOpenPod\iOpenPod\iTunes\iTunesDB")

#UI
with dpg.window(label="Controls", pos=(10, 450)):
    dpg.add_button(label="Start Parsing", callback=start_parsing)

dpg.create_viewport(title="iOpenPod", width=650, height=650)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()