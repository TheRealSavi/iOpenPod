import struct

def parse_mhod(data, offset, header_length, chunk_length) -> dict:    
    mhod_type = struct.unpack("<I", data[offset+12:offset+16])[0]
    string_length = struct.unpack("<I", data[offset+28:offset+32])[0]
    encoding_flag = struct.unpack("<I", data[offset+32:offset+36])[0]  # Encoding hint (not always reliable)
    string_data = data[offset+40:offset+40+string_length]

    #guess encoding based on the presence of a null byte
    #its in every utf16 but very rare in utf8
    string_decode = ""
    if b'\x00' in string_data:
        string_decode = string_data.decode("utf-16-le")
    else:
        string_decode = string_data.decode("utf-8")

    return {"nextOffset": offset+chunk_length, "result": {"mhodType": mhod_type, "string": string_decode}}
