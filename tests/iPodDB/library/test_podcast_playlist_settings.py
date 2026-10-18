"""Finder-compatible settings through public Podcast Library preparation."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.library.test_finder_podcasts import finder_source
from tests.iPodDB.library.test_playlist_datasets import rows
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.cdb import compress_iTunesCDB, decompress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.settings_mhod import (
    MhodSettingsField,
    MhodSettingsPayload,
)
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, WriteResources, WriteTarget

WRITTEN_AT = 1_800_000_000


@pytest.mark.parametrize("mirrored", (False, True))
def test_new_podcasts_playlist_has_finder_settings(mirrored: bool) -> None:
    source = library(mirrored=mirrored)
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(track, metadata=replace(track.metadata, podcast=True))
            for track in source.snapshot.tracks
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(playlist_timestamp=WRITTEN_AT),
    )
    assert result.prepared is not None, result.issues
    document = parse_iTunesDB(result.prepared.itunes)
    for kind in (2, 3):
        playlist = next(
            row.chunk
            for row in rows(document, kind)
            if row.chunk.header.playlist_kind_flags & 1
        )
        assert {
            "sort_order": playlist.header.sort_order,
            "timestamp_present": bool(playlist.header.timestamp),
            "timestamp_2_present": bool(playlist.header.timestamp_2),
            "settings_present": any(
                isinstance(child.header, MhodHeader) and child.header.mhod_type == 102
                for child in playlist.children
            ),
        } == {
            "sort_order": 3,
            "timestamp_present": True,
            "timestamp_2_present": True,
            "settings_present": True,
        }
        assert playlist.header.timestamp == WRITTEN_AT + 2_082_844_800
        assert playlist.header.timestamp_2 == playlist.header.timestamp
        settings = next(
            child.payload
            for child in playlist.children
            if isinstance(child.payload, MhodSettingsPayload)
        )
        fixture = json.loads(
            (
                Path(__file__).parents[2]
                / "fixtures/writing/podcast-playlist-finder.json"
            ).read_text(encoding="utf-8")
        )
        assert settings.data.hex() == fixture["settings_hex"]


@pytest.mark.parametrize("compressed", (False, True))
@pytest.mark.parametrize("retained", (False, True))
def test_affected_podcasts_preserve_settings_and_creation_date(
    compressed: bool, retained: bool
) -> None:
    document = parse_iTunesDB(finder_source().serialize().itunes)
    document = replace(
        document, header=replace(document.header, timezone_offset=-18000)
    )
    custom = MhodSettingsPayload(
        bytes(340) + b"\xab",
        (MhodSettingsField(0, 7), MhodSettingsField(336, 99)),
        b"\xab",
    )
    created = WRITTEN_AT + 2_082_844_800 - 18000 - 600
    for kind in (2, 3):
        row = rows(document, kind)[1]
        if retained:
            document = document.replace_chunk(
                row,
                replace(
                    row.chunk,
                    header=replace(
                        row.chunk.header,
                        sort_order=7,
                        timestamp=created,
                        timestamp_2=created + 60,
                    ),
                    children=(
                        new_itunes_chunk(
                            MHOD, MhodHeader(mhod_type=102), payload=custom
                        ),
                        *row.chunk.children,
                    ),
                ),
            )
    data = write_iTunesDB(document)
    data = compress_iTunesCDB(data) if compressed else data
    source = IPodLibrary(data)
    target = WriteTarget(compressed_database=compressed)
    resources = WriteResources(
        playlist_timestamp=WRITTEN_AT, pending_playback_sidecars=False
    )
    noop = source.prepare(source.analyze(source.begin_draft(), target), resources)
    assert noop.prepared is not None, noop.issues
    assert noop.prepared.itunes == data
    first, *others = source.snapshot.tracks
    desired = replace(
        source.snapshot, tracks=(replace(first, album="Renamed show"), *others)
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target), resources
    )
    assert result.prepared is not None, result.issues
    output = result.prepared.itunes
    checked = parse_iTunesDB(
        decompress_iTunesCDB(output).logical_bytes if compressed else output
    )
    for kind in (2, 3):
        playlist = rows(checked, kind)[1].chunk
        assert playlist.header.sort_order == (7 if retained else 3)
        assert playlist.header.timestamp == (
            created if retained else WRITTEN_AT + 2_082_844_800 - 18000
        )
        assert playlist.header.timestamp_2 == WRITTEN_AT + 2_082_844_800 - 18000
        settings = [
            child.payload
            for child in playlist.children
            if isinstance(child.payload, MhodSettingsPayload)
        ]
        assert len(settings) == 1
        if retained:
            assert settings[0].nonzero_fields == custom.nonzero_fields
            assert settings[0].trailing_data == b"\xab"
    reloaded = IPodLibrary(output)
    unchanged = reloaded.prepare(
        reloaded.analyze(reloaded.begin_draft(), target),
        replace(resources, playlist_timestamp=WRITTEN_AT + 3600),
    )
    assert unchanged.prepared is not None, unchanged.issues
    assert unchanged.prepared.itunes == output
