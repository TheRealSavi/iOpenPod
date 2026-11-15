"""Read embedded lyrics through bounded, identity-checked media access."""

from collections.abc import Callable

from iOpenPod.app.media.lyrics import embedded_lyrics
from iOpenPod.app.media.tag_reader import read_embedded_media
from iOpenPod.app.playback.backend import PlaybackSource


def read_embedded_lyrics(
    source: PlaybackSource, *, checkpoint: Callable[[], None]
) -> str:
    """Read native lyric tags without trusting the database presence flag."""
    return embedded_lyrics(read_embedded_media(source, checkpoint=checkpoint))
