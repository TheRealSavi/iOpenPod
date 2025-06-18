def parse_itunesdb(file) -> dict:
    from .chunk_parser import parse_chunk

    if isinstance(file, str):  # If it's a file path, open the file
        with open(file, "rb") as f:
            data = f.read()
    elif hasattr(file, "read"):  # If it's a file-like object, read it directly
        data = file.read()
    else:
        raise TypeError("file must be a path (str) or a file-like object")

    result = parse_chunk(data, 0)

    return result
