from __future__ import annotations

import struct

import pytest

from iopenpod.gui.widgets.itunesdbForensics import ITunesDBForensicsDialog
from iopenpod.itunesdb_parser.byte_walk import (
    hex_interpretations,
    index_byte_walk_json,
    load_indexed_chunk,
)
from iopenpod.itunesdb_parser.forensics import export_forensic_json
from iopenpod.itunesdb_writer.mhbd_writer import write_mhbd
from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo


def _phase_byte_walk(tmp_path):
    source = tmp_path / "iTunesDB"
    database = bytearray(write_mhbd([], playlists_type2=[PlaylistInfo(name="Phase Music")]))
    phase_title = "Phase Music".encode("utf-16-le")
    title_offset = database.find(phase_title)
    playlist_offset = database.rfind(b"mhyp", 0, title_offset)
    struct.pack_into("<H", database, playlist_offset + 0x52, 0x19)
    source.write_bytes(database)
    output = tmp_path / "phase.byte-walk.json"
    export_forensic_json(source, output)
    return output


def test_byte_walk_index_loads_one_phase_chunk_without_loading_the_document(tmp_path) -> None:
    output = _phase_byte_walk(tmp_path)

    entries = index_byte_walk_json(output)
    phase = next(entry for entry in entries if entry.caption == "Playlist: Phase Music")
    chunk = load_indexed_chunk(output, phase)
    marker = next(entry for entry in chunk["bytes"] if entry.get("field") == "phase_game_flag")

    assert len(entries) > 1
    assert chunk["caption"] == "Playlist: Phase Music"
    assert marker["hex"] == "19 00"
    assert marker["value"] == 25


def test_hex_interpretations_accept_hexdump_punctuation_and_reports_encodings() -> None:
    values = hex_interpretations("0x19:00")

    assert values["Byte count"] == "2"
    assert values["Unsigned 16-bit LE"] == "25"
    assert values["Unsigned 16-bit BE"] == "6400"
    assert "UTF-16 LE" in values


def test_hex_interpretations_rejects_malformed_input() -> None:
    with pytest.raises(ValueError, match="odd number"):
        hex_interpretations("123")


def test_inspector_renders_selected_span_and_its_hex_decodings(qtbot, tmp_path) -> None:
    output = _phase_byte_walk(tmp_path)
    entries = index_byte_walk_json(output)
    phase = next(entry for entry in entries if entry.caption == "Playlist: Phase Music")
    chunk = load_indexed_chunk(output, phase)
    dialog = ITunesDBForensicsDialog()
    qtbot.addWidget(dialog)

    dialog._entries = entries
    dialog.search_input.setText("Phase Music")
    assert dialog.results_tree.topLevelItemCount() == 2
    first_result = dialog.results_tree.topLevelItem(0)
    assert first_result is not None
    assert first_result.text(1) == "Playlist: Phase Music"

    dialog._on_chunk_complete(chunk)
    root = dialog.chunk_tree.topLevelItem(0)
    assert root is not None
    marker_item = next(
        child
        for index in range(root.childCount())
        if (child := root.child(index)) is not None
        and child.text(2) == "phase_game_flag"
    )
    dialog.chunk_tree.setCurrentItem(marker_item)

    assert dialog.hex_input.toPlainText() == "19 00"
    interpretation_values = []
    for index in range(dialog.interpretation_tree.topLevelItemCount()):
        item = dialog.interpretation_tree.topLevelItem(index)
        if item is not None:
            interpretation_values.append(item.text(1))
    assert "25" in interpretation_values
