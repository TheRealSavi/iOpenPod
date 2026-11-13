"""Compare the Host implementation with independent original-firmware output."""

import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.alarm_fixtures import (
    named_playlist_chunk,
    playlist_dataset,
    playlist_library,
    track_dataset,
)
from tests.iPodDB.library.test_classic_alarm_playlists import LAYOUTS

from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import MhodStringPrefix
from iPodDB.library import AlarmPlaylistLayout
from iPodDB.library._alarm_names import native_alarm_name

FIXTURE = Path(__file__).parents[2] / "fixtures/alarms/native_name_import.json"


def test_original_composition_pairs_sequences_and_cache_limits() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(fixture["composition_pairs"]) == 917
    for first, second, composed in fixture["composition_pairs"]:
        assert native_alarm_name(chr(first) + chr(second), compose=True) == chr(
            composed
        )
    for case in fixture["composition_cases"]:
        expected = case["composed"].encode("utf-16-le", errors="surrogatepass")[:510]
        assert (
            native_alarm_name(case["source"], compose=True).encode(
                "utf-16-le", errors="surrogatepass"
            )
            == expected
        )
    for case in fixture["cache_copy_cases"]:
        assert (
            len(native_alarm_name("x" * case["source_units"], compose=False))
            == case["copied_units"]
        )


@pytest.mark.parametrize("encoding,name,compose", ((2, "ABC", False), (1, "", True)))
@pytest.mark.parametrize("layout", LAYOUTS)
def test_native_undefined_name_import_cannot_qualify_selector(
    encoding: int, name: str, compose: bool, layout: AlarmPlaylistLayout
) -> None:
    row = named_playlist_chunk(20, name)
    title = row.children[0]
    assert isinstance(title.prefix, MhodStringPrefix)
    title = replace(
        title,
        prefix=replace(
            title.prefix,
            encoding_indicator=encoding,
            bypass_pair_composition=int(not compose),
        ),
    )
    row = replace(row, children=(title, *row.children[1:]))
    catalog = playlist_library(
        track_dataset(),
        playlist_dataset(2, (named_playlist_chunk(100, "Library", master=True), row)),
    ).alarm_playlists(layout)
    assert not catalog.complete and catalog.issues


def test_utf16_cache_counts_units_and_keeps_embedded_nul() -> None:
    value = "a" * 254 + "\U0001f600" + "end"
    result = native_alarm_name(value, compose=False)
    units = result.encode("utf-16-le", errors="surrogatepass")
    assert len(units) == 510 and struct.unpack("<H", units[-2:])[0] == 0xD83D
    assert native_alarm_name("a\0b", compose=False) == "a\0b"
