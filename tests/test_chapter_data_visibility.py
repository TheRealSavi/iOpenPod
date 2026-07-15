from __future__ import annotations

from io import BytesIO

from iopenpod.itunesdb_parser import parse_itunesdb
from iopenpod.itunesdb_parser.mhod_parser import parse_mhod
from iopenpod.itunesdb_shared.extraction import extract_track_extras
from iopenpod.itunesdb_shared.mhod_defs import MHOD_HEADER_SIZE
from iopenpod.itunesdb_writer.mhbd_writer import write_mhbd
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.itunesdb_writer.mhod_writer import write_mhod_chapter_data
from iopenpod.sync._track_conversion import track_dict_to_info
from iopenpod.sync.sync_executor import SyncExecutor


def _chapter_data() -> dict[str, object]:
    return {
        "unk024": 1,
        "unk028": 2,
        "unk032": 3,
        "chapters": [
            {"startpos": 0, "title": "Intro"},
            {"startpos": 65_000, "title": "Part One"},
            {"startpos": 125_000, "title": "Part Two"},
            {"startpos": 190_000, "title": "Credits"},
        ],
    }


def test_chapter_mhod_round_trips_through_writer_and_parser() -> None:
    source = _chapter_data()

    blob = write_mhod_chapter_data(
        source["chapters"],  # type: ignore[arg-type]
        unk024=source["unk024"],  # type: ignore[arg-type]
        unk028=source["unk028"],  # type: ignore[arg-type]
        unk032=source["unk032"],  # type: ignore[arg-type]
    )
    parsed = parse_mhod(blob, 0, MHOD_HEADER_SIZE, len(blob))["data"]

    assert parsed["mhod_type"] == 17
    assert parsed["data"] == source


def test_chapter_mhod_clamps_invalid_unsigned_fields() -> None:
    blob = write_mhod_chapter_data(
        [
            {"startpos": -10, "title": "Before"},
            {"startpos": 2**40, "title": "After"},
        ],
        unk024=-1,
        unk028=2**40,
        unk032="bad",  # type: ignore[arg-type]
    )

    parsed = parse_mhod(blob, 0, MHOD_HEADER_SIZE, len(blob))["data"]["data"]

    assert parsed["unk024"] == 0
    assert parsed["unk028"] == 0xFFFFFFFF
    assert parsed["unk032"] == 0
    assert parsed["chapters"] == [
        {"startpos": 0, "title": "Before"},
        {"startpos": 0xFFFFFFFF, "title": "After"},
    ]


def test_extract_track_extras_preserves_only_chapter_data() -> None:
    chapter_data = _chapter_data()
    children = [{"data": {"mhod_type": 17, "data": chapter_data}}]

    extras = extract_track_extras(children)

    assert extras == {"chapter_data": chapter_data}


def test_extract_track_extras_preserves_empty_chapter_data() -> None:
    children = [{"data": {"mhod_type": 17, "data": {"chapters": []}}}]

    assert extract_track_extras(children) == {"chapter_data": {"chapters": []}}


def test_track_dict_to_info_preserves_chapter_data() -> None:
    chapter_data = _chapter_data()

    info = track_dict_to_info(
        {
            "Title": "Chaptered Album",
            "Location": ":iPod_Control:Music:F00:ALBM.m4a",
            "filetype": "AAC audio file",
            "chapter_data": chapter_data,
        }
    )

    assert info.chapter_data == chapter_data


def test_track_dict_to_info_preserves_chapter_data_for_mp3() -> None:
    chapter_data = _chapter_data()

    info = track_dict_to_info(
        {
            "Title": "Chaptered MP3",
            "Location": ":iPod_Control:Music:F00:ALBM.mp3",
            "filetype": "MPEG audio file",
            "chapter_data": chapter_data,
        }
    )

    assert info.filetype == "mp3"
    assert info.chapter_data == chapter_data


def test_sync_executor_can_apply_chapter_data_metadata_updates() -> None:
    assert SyncExecutor._META_FIELD_MAP["chapter_data"] == ("chapter_data", None)


def test_track_writer_skips_implausible_chapter_data() -> None:
    data = write_mhbd(
        [
            TrackInfo(
                "Bad Chapters",
                ":iPod_Control:Music:F00:BAD.m4a",
                chapter_data={
                    "chapters": [
                        {"startpos": 0xFFFFFFFF, "title": "One"},
                        {"startpos": 0xFFFFFFFF, "title": "Two"},
                    ],
                },
            )
        ]
    )
    db = parse_itunesdb(BytesIO(data))
    track_dataset = next(
        child["data"]
        for child in db["children"]
        if child["chunk_type"] == "mhsd" and child["data"]["dataset_type"] == 1
    )
    track = track_dataset["children"][0]["data"][0]["data"]

    assert all(child["data"]["mhod_type"] != 17 for child in track["children"])
