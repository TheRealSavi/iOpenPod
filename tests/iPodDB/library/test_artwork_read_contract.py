"""Authoritative filename tokens select bounded artwork reads without guessing."""

from dataclasses import replace

import pytest

from iPodDB.ArtworkDB.shared.artwork_index import ArtworkItem, IthmbLocation
from iPodDB.library.artwork import CoverFormat, CoverPixelFormat, select_artwork

_FORMATS = (
    CoverFormat(1061, 55, 55, 112, CoverPixelFormat.RGB565_LE),
    CoverFormat(1060, 320, 320, 640, CoverPixelFormat.RGB565_LE),
)


def _location(name: str) -> IthmbLocation:
    return IthmbLocation(1061, name, 37, 6160, 55, 55)


def _item(*locations: IthmbLocation) -> ArtworkItem:
    return ArtworkItem(100, 7, 1000, locations)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (":F9999_7.ithmb", "iPod_Control/Artwork/F9999_7.ithmb"),
        ("résumé 表紙.ithmb", "iPod_Control/Artwork/résumé 表紙.ithmb"),
        (": cover.ITHMB", "iPod_Control/Artwork/ cover.ITHMB"),
        (":nested:cover.ithmb", "iPod_Control/Artwork/nested/cover.ithmb"),
        (":nested/cover.ithmb", "iPod_Control/Artwork/nested/cover.ithmb"),
        (
            ":iPod_Control:Artwork:chapters:episode.ithmb",
            "iPod_Control/Artwork/chapters/episode.ithmb",
        ),
        (
            "iPod_Control/Artwork/chapters/episode.ithmb",
            "iPod_Control/Artwork/chapters/episode.ithmb",
        ),
    ],
)
def test_reads_the_explicit_filename_without_inferring_format_or_shard(
    name: str, expected: str
) -> None:
    read = select_artwork(_item(_location(name)), _FORMATS, 55)

    assert read is not None
    assert (read.relative_path, read.format_id, read.offset, read.length) == (
        expected,
        1061,
        37,
        6160,
    )


@pytest.mark.parametrize(
    "name",
    [
        "",
        ":",
        "::cover.ithmb",
        ":..:F1061_1.ithmb",
        ":../F1061_1.ithmb",
        ":iPod_Control:Artwork:.:cover.ithmb",
        ":iPod_Control:Artwork::cover.ithmb",
        ":not-an-ithmb.bin",
        ":cover.ithmb\x00",
        "/tmp/cover.ithmb",
        "C:\\cover.ithmb",
        "iPod_Control/Other/cover.ithmb",
        "subdirectory/cover.ithmb",
    ],
)
def test_unresolvable_filename_never_falls_back_to_a_guessed_shard(name: str) -> None:
    item = _item(_location(name))

    assert select_artwork(item, _FORMATS, 55) is None
    assert item.locations[0].file_name == name


def test_skips_an_invalid_best_size_instead_of_hiding_a_valid_representation() -> None:
    invalid = _location(":..:cover.ithmb")
    valid = replace(
        _location(":alternative.ithmb"),
        format_id=1060,
        offset=123,
        byte_length=204800,
        width=320,
        height=320,
    )
    read = select_artwork(_item(invalid, valid), _FORMATS, 55)

    assert read is not None
    assert (read.relative_path, read.format_id, read.offset) == (
        "iPod_Control/Artwork/alternative.ithmb",
        1060,
        123,
    )


def test_filename_validation_keeps_explicit_time_group_selection() -> None:
    item = _item(
        _location(""),
        replace(_location(":later.ithmb"), display_time_ms=15000),
    )

    assert select_artwork(item, _FORMATS, 55, display_time_ms=0) is None
    later = select_artwork(item, _FORMATS, 55, display_time_ms=15000)
    assert later is not None
    assert later.relative_path == "iPod_Control/Artwork/later.ithmb"
