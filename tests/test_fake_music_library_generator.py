from __future__ import annotations

from scripts.generate_fake_music_library import _serial_chroma_signature


def test_track_signatures_are_unique_by_design():
    signatures = {
        _serial_chroma_signature(track_serial, 8)
        for track_serial in range(200)
    }
    assert len(signatures) == 200
