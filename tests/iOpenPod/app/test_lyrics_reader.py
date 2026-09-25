"""Real tag parsing stays bounded and uses only the provided Playback Source."""

import pytest
from tests.iOpenPod.lyrics_test_support import WORDS, MemorySource, media

from iOpenPod.app.media.lyrics_reader import read_embedded_lyrics


def checkpoint() -> None:
    pass


@pytest.mark.parametrize("name", ["tone.mp3", "tone.m4a", "tone.wav", "tone.aiff"])
@pytest.mark.parametrize("words", [WORDS, ""])
def test_reads_native_lyrics_and_absent_tags(name: str, words: str) -> None:
    source = MemorySource(media(name, words), name)
    assert read_embedded_lyrics(source, checkpoint=checkpoint) == words
    assert source.reads
    assert all(0 < size <= 64 * 1024 for _, size in source.reads)


def test_does_not_materialize_a_large_media_payload() -> None:
    # A long MP3 can be inspected by reading its tag and a few audio frames.
    source = MemorySource(media() + bytes(20 * 1024 * 1024))
    assert read_embedded_lyrics(source, checkpoint=checkpoint) == WORDS
    assert sum(size for _, size in source.reads) < 64 * 1024


def test_oversized_tag_is_rejected_before_reading_its_payload() -> None:
    # ID3's synchsafe size declares a 32 MiB tag in a sparse 64 MiB source.
    class OversizedSource:
        file_name = "oversized.mp3"
        byte_count = 64 * 1024 * 1024

        def read_at(self, offset: int, length: int) -> bytes:
            assert length <= 64 * 1024
            header = b"ID3\x04\x00\x00\x10\x00\x00\x00"
            return (header[offset:] if offset < len(header) else b"").ljust(
                length, b"\x00"
            )

    with pytest.raises((ValueError, OSError), match="read limit"):
        read_embedded_lyrics(OversizedSource(), checkpoint=checkpoint)


def test_cancellation_stops_before_source_reads() -> None:
    source = MemorySource(media())

    def cancelled() -> None:
        raise ValueError("cancelled")

    with pytest.raises(ValueError, match="cancelled"):
        read_embedded_lyrics(source, checkpoint=cancelled)
    assert source.reads == []


def test_truncated_source_fails_instead_of_displaying_partial_lyrics() -> None:
    class TruncatedSource(MemorySource):
        def read_at(self, offset: int, length: int) -> bytes:
            return b""

    with pytest.raises(ValueError, match="changed"):
        read_embedded_lyrics(TruncatedSource(media()), checkpoint=checkpoint)
