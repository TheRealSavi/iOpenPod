import logging
import struct

from iopenpod.artworkdb_writer import artwork_writer as aw
from iopenpod.itunesdb_parser.chunk_parser import (
    log_unknown_chunk_summary,
    parse_chunk,
    reset_unknown_chunk_summary,
)
from iopenpod.sync.sync_executor import SyncExecutor


def test_unknown_itunesdb_chunks_are_summarized(caplog) -> None:
    chunk = struct.pack("<4sII", b"4407", 12, 12)

    reset_unknown_chunk_summary()
    with caplog.at_level(logging.WARNING):
        parse_chunk(chunk, 0)
        parse_chunk(chunk, 0)

        assert "unknown iTunesDB chunk" not in caplog.text

        log_unknown_chunk_summary()

    assert "iTunesDB contained 2 unknown chunk(s)" in caplog.text
    assert "'4407' at 0x0" in caplog.text


def test_metadata_strip_successes_are_summarized_without_track_names(
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    executor = SyncExecutor(tmp_path)
    source_a = tmp_path / "Very Specific User Track A.mp3"
    source_b = tmp_path / "Very Specific User Track B.mp3"
    source_a.write_bytes(b"x" * 100)
    source_b.write_bytes(b"y" * 80)

    def fake_strip_metadata(path):
        path.write_bytes(path.read_bytes()[:20])
        return True

    def fake_copy_file_to_device(*_args, **_kwargs):
        return None

    monkeypatch.setattr("iopenpod.sync.sync_executor.strip_metadata", fake_strip_metadata)
    monkeypatch.setattr(executor, "_copy_file_to_device", fake_copy_file_to_device)

    with caplog.at_level(logging.DEBUG, logger="iopenpod.sync.sync_executor"):
        executor._reset_metadata_strip_summary()
        executor._copy_stripped_file_to_device(source_a, tmp_path / "out-a.mp3")
        executor._copy_stripped_file_to_device(source_b, tmp_path / "out-b.mp3")
        executor._log_metadata_strip_summary()

    assert "Stripped metadata from" not in caplog.text
    assert "Very Specific User Track" not in caplog.text
    assert "Metadata stripping: removed tags from 2 file(s)" in caplog.text


def test_metadata_strip_failures_are_summarized_without_track_names(
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    executor = SyncExecutor(tmp_path)
    source = tmp_path / "Very Specific User Track.mp3"
    source.write_bytes(b"x" * 100)

    def fake_strip_metadata(_path):
        return False

    def fake_copy_file_to_device(*_args, **_kwargs):
        return None

    monkeypatch.setattr("iopenpod.sync.sync_executor.strip_metadata", fake_strip_metadata)
    monkeypatch.setattr(executor, "_copy_file_to_device", fake_copy_file_to_device)

    with caplog.at_level(logging.WARNING, logger="iopenpod.sync.sync_executor"):
        executor._reset_metadata_strip_summary()
        executor._copy_stripped_file_to_device(source, tmp_path / "out.mp3")
        executor._log_metadata_strip_summary()

    assert "Very Specific User Track" not in caplog.text
    assert "Could not strip metadata from 1 file(s)" in caplog.text
    assert "By extension: .mp3=1" in caplog.text


def test_artwork_missing_art_debug_is_summarized_without_track_names(
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    source = tmp_path / "Very Specific User Track.mp3"
    source.write_bytes(b"audio")
    track = {
        "db_track_id": 101,
        "title": "Very Specific User Track",
    }

    monkeypatch.setattr(aw, "extract_art_with_folder", lambda _path: None)

    with caplog.at_level(logging.DEBUG, logger="iopenpod.artworkdb_writer.artwork_writer"):
        decisions, summary = aw._collect_track_artwork_decisions(
            [track],
            {101: str(source)},
            {},
        )

    assert decisions[101].kind == aw.ArtworkDecisionKind.CLEAR_ART
    assert summary.cleared == 1
    assert "ART: no art found for" not in caplog.text
    assert "Very Specific User Track" not in caplog.text
