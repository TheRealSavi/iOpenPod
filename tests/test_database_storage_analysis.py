import sqlite3
import struct

from iopenpod.application.database_storage import analyze_database_storage


def _chunk(tag: bytes, header: bytes, body: bytes = b"") -> bytes:
    header_length = len(header)
    total_length = header_length + len(body)
    return tag + struct.pack("<II", header_length, total_length) + header[12:] + body


def _list_chunk(tag: bytes, children: list[bytes]) -> bytes:
    return tag + struct.pack("<II", 12, len(children)) + b"".join(children)


def _mhod_string(mhod_type: int, text: str) -> bytes:
    payload = text.encode("utf-16-le")
    subheader = struct.pack("<IIII", 1, len(payload), 0, 0)
    header = b"mhod" + struct.pack("<IIIII", 24, 24 + len(subheader) + len(payload), mhod_type, 0, 0)
    return header + subheader + payload


def _mhit(children: list[bytes]) -> bytes:
    body = b"".join(children)
    total_length = 16 + len(body)
    return b"mhit" + struct.pack("<III", 16, total_length, len(children)) + body


def _mhsd(dataset_type: int, child: bytes) -> bytes:
    header = b"mhsd" + struct.pack("<III", 16, 16 + len(child), dataset_type)
    return header + child


def _mhbd(children: list[bytes]) -> bytes:
    body = b"".join(children)
    total_length = 24 + len(body)
    return (
        b"mhbd"
        + struct.pack("<IIIII", 24, total_length, 1, 0x19, len(children))
        + body
    )


def test_analyze_database_storage_nests_data_objects_under_container(
    tmp_path,
) -> None:
    db_path = tmp_path / "iTunesDB"
    lyrics = _mhod_string(10, "la " * 100)
    title = _mhod_string(1, "Small title")
    db_path.write_bytes(_mhbd([_mhsd(1, _list_chunk(b"mhlt", [_mhit([title, lyrics])]))]))

    report = analyze_database_storage(db_path, uses_sqlite_db=False)

    root = report.roots[0]
    track_item = report.find("Track Item")

    assert report.logical_bytes == db_path.stat().st_size
    assert "Data objects" not in [child.label for child in root.children]
    assert track_item is not None
    data_objects = next(
        child for child in track_item.children if child.label == "Data objects"
    )
    lyrics_node = data_objects.find("Lyrics")
    title_node = data_objects.find("Title")
    assert lyrics_node is not None
    assert title_node is not None
    assert lyrics_node.bytes_used > title_node.bytes_used


def test_analyze_database_storage_reports_sqlite_itdb_files(tmp_path) -> None:
    itlp = tmp_path / "iPod_Control" / "iTunes" / "iTunes Library.itlp"
    itlp.mkdir(parents=True)
    extras_path = itlp / "Extras.itdb"
    with sqlite3.connect(extras_path) as conn:
        conn.execute("CREATE TABLE lyrics (item_pid INTEGER, lyrics TEXT)")
        conn.execute("INSERT INTO lyrics VALUES (1, ?)", ("long lyric " * 50,))

    report = analyze_database_storage(
        tmp_path / "iPod_Control" / "iTunes" / "iTunesCDB",
        ipod_root=tmp_path,
        uses_sqlite_db=True,
    )

    extras_node = report.find("Extras.itdb")
    lyrics_node = report.find("lyrics")

    assert report.mode == "sqlite"
    assert extras_node is not None
    assert extras_node.bytes_used == extras_path.stat().st_size
    assert lyrics_node is not None
    assert "1 row" in lyrics_node.detail
