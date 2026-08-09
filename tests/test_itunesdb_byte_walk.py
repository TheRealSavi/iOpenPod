from __future__ import annotations

import struct
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHeaderView

from iopenpod.gui.widgets.itunesdbForensics import ITunesDBForensicsDialog
from iopenpod.itunesdb_parser.byte_walk import (
    ByteWalkChunkCache,
    ByteWalkChunkIndexEntry,
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


def test_chunk_cache_reuses_the_selected_chunk(tmp_path, monkeypatch) -> None:
    output = _phase_byte_walk(tmp_path)
    phase = next(entry for entry in index_byte_walk_json(output) if entry.caption == "Playlist: Phase Music")
    cache = ByteWalkChunkCache()
    calls = 0
    original_loader = load_indexed_chunk

    def count_loads(path, entry):
        nonlocal calls
        calls += 1
        return original_loader(path, entry)

    monkeypatch.setattr("iopenpod.itunesdb_parser.byte_walk.load_indexed_chunk", count_loads)

    first = cache.load(output, phase)
    second = cache.load(output, phase)

    assert first.chunk == second.chunk
    assert first.was_cached is False
    assert second.was_cached is True
    assert calls == 1


def test_chunk_cache_coalesces_simultaneous_loads(tmp_path, monkeypatch) -> None:
    output = _phase_byte_walk(tmp_path)
    phase = next(entry for entry in index_byte_walk_json(output) if entry.caption == "Playlist: Phase Music")
    cache = ByteWalkChunkCache()
    started = Event()
    release = Event()
    start_together = Barrier(2)
    count_lock = Lock()
    calls = 0
    original_loader = load_indexed_chunk

    def delayed_load(path, entry):
        nonlocal calls
        with count_lock:
            calls += 1
        started.set()
        assert release.wait(timeout=5)
        return original_loader(path, entry)

    def concurrent_load():
        start_together.wait(timeout=5)
        return cache.load(output, phase)

    monkeypatch.setattr("iopenpod.itunesdb_parser.byte_walk.load_indexed_chunk", delayed_load)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(concurrent_load)
        second_future = executor.submit(concurrent_load)
        assert started.wait(timeout=5)
        release.set()
        first = first_future.result(timeout=5)
        second = second_future.result(timeout=5)

    assert first.chunk == second.chunk
    assert {first.was_cached, second.was_cached} == {False, True}
    assert calls == 1


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


def test_inspector_keeps_the_selected_tree_hierarchy_visible(qtbot) -> None:
    dialog = ITunesDBForensicsDialog()
    qtbot.addWidget(dialog)
    dialog._on_chunk_complete(
        {
            "chunk": "mhbd",
            "caption": "Database",
            "file_offset": "0x0",
            "byte_length": 1,
            "bytes": [
                {
                    "at": "0x0",
                    "byte_length": 1,
                    "chunk": {
                        "chunk": "mhsd",
                        "caption": "Track dataset",
                        "file_offset": "0x0",
                        "byte_length": 1,
                        "bytes": [],
                    },
                },
            ],
        },
    )

    root = dialog.chunk_tree.topLevelItem(0)
    assert root is not None
    nested = root.child(0)
    assert nested is not None
    dialog.chunk_tree.setCurrentItem(nested)

    assert dialog.hierarchy_path_label.text() == "mhbd — Database  ›  mhsd — Track dataset"


def test_inspector_lists_every_chunk_and_allows_selecting_the_mhbd_root(qtbot, tmp_path) -> None:
    output = _phase_byte_walk(tmp_path)
    entries = index_byte_walk_json(output)
    dialog = ITunesDBForensicsDialog()
    qtbot.addWidget(dialog)

    dialog._json_path = output
    dialog._entries = entries
    dialog._refresh_results()

    assert dialog.results_tree.topLevelItemCount() == len(entries)
    root_item = next(
        (
            item
            for index in range(dialog.results_tree.topLevelItemCount())
            if (item := dialog.results_tree.topLevelItem(index)) is not None
            and item.text(0) == "mhbd"
        ),
        None,
    )
    assert root_item is not None
    dialog.results_tree.setCurrentItem(root_item)

    qtbot.waitUntil(lambda: dialog.chunk_tree.topLevelItemCount() == 1)
    root = dialog.chunk_tree.topLevelItem(0)
    assert root is not None
    assert root.text(2).startswith("mhbd")


def test_inspector_renders_result_lists_larger_than_one_thousand(qtbot) -> None:
    dialog = ITunesDBForensicsDialog()
    qtbot.addWidget(dialog)
    dialog._entries = [
        ByteWalkChunkIndexEntry(
            json_offset=index,
            chunk_type="mhit",
            caption=f"Track {index}",
            file_offset=index,
            byte_length=64,
        )
        for index in range(1_001)
    ]

    dialog._refresh_results()

    qtbot.waitUntil(lambda: dialog.results_tree.topLevelItemCount() == 1_001)
    assert dialog.results_summary.text() == "1,001 matching chunks"


def test_inspector_batches_large_chunk_trees_without_blocking(qtbot) -> None:
    dialog = ITunesDBForensicsDialog()
    qtbot.addWidget(dialog)
    entries = [
        {
            "at": f"0x{index:X}",
            "byte_length": 1,
            "field": "byte",
            "value": index,
            "hex": "00",
        }
        for index in range(251)
    ]

    dialog._set_busy("Loading chunk…", "chunk")
    dialog._on_chunk_complete(
        {
            "chunk": "mhbd",
            "caption": "Database",
            "file_offset": "0x0",
            "byte_length": len(entries),
            "bytes": entries,
        },
    )

    root = dialog.chunk_tree.topLevelItem(0)
    assert root is not None
    assert root.childCount() == 250
    assert not dialog.loading_indicator.isHidden()

    qtbot.waitUntil(lambda: root.childCount() == len(entries))
    assert dialog.loading_indicator.isHidden()


def test_inspector_tables_allow_resizing_and_scroll_large_decoder_values(qtbot) -> None:
    dialog = ITunesDBForensicsDialog()
    qtbot.addWidget(dialog)

    long_value = "x" * 512
    dialog._on_chunk_complete(
        {
            "chunk": "mhit",
            "caption": "Track",
            "file_offset": "0x0",
            "byte_length": 1,
            "bytes": [{"at": "0x0", "byte_length": 1, "field": "title", "value": long_value, "hex": "00"}],
        },
    )
    root = dialog.chunk_tree.topLevelItem(0)
    assert root is not None
    item = root.child(0)
    assert item is not None
    assert item.text(3) == long_value

    chunk_header = dialog.chunk_tree.header()
    interpretation_header = dialog.interpretation_tree.header()
    assert chunk_header is not None
    assert interpretation_header is not None
    assert chunk_header.sectionResizeMode(3) == QHeaderView.ResizeMode.Interactive
    assert interpretation_header.sectionResizeMode(1) == QHeaderView.ResizeMode.Interactive
    assert dialog.chunk_tree.textElideMode() == Qt.TextElideMode.ElideNone
    assert dialog.interpretation_tree.textElideMode() == Qt.TextElideMode.ElideNone
    assert dialog.interpretation_tree.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert dialog.interpretation_tree.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded


def test_inspector_shows_an_explicit_loading_state(qtbot) -> None:
    dialog = ITunesDBForensicsDialog()
    qtbot.addWidget(dialog)

    dialog._set_busy("Generating byte-walk JSON; this can be large…", "export")
    dialog._set_busy("Loading Playlist byte spans…", "chunk")
    dialog._set_idle("Loaded Playlist.", "chunk")

    assert dialog.status_label.text().startswith("Generating byte-walk JSON")
    assert not dialog.loading_indicator.isHidden()
    assert not dialog.open_button.isEnabled()
    assert not dialog.generate_button.isEnabled()

    dialog._set_idle("Generated byte-walk JSON.", "export")

    assert dialog.loading_indicator.isHidden()
    assert dialog.open_button.isEnabled()
    assert dialog.generate_button.isEnabled()
