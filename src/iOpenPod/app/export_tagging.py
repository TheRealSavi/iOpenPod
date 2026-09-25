"""Write semantic Library metadata and artwork into exported Host media files."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

import mutagen.id3 as id3_frames
from mutagen.aiff import AIFF
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.wave import WAVE
from PIL import Image

if TYPE_CHECKING:
    from iOpenPod.app.models.artwork import ArtworkImage
    from iPodDB.library import Track
    from storage import HostPath

_ID3_EXTENSIONS = frozenset((".mp3", ".wav", ".wave", ".aif", ".aiff", ".aifc"))
_MP4_EXTENSIONS = frozenset((".m4a", ".m4b", ".m4v", ".mp4", ".mov"))
_ID3_FRAMES: Any = id3_frames
_MP4_COVER: Any = MP4Cover


class _MutagenFile(Protocol):
    tags: Any

    def add_tags(self) -> None: ...

    def save(self, *args: Any, **kwargs: Any) -> None: ...


class _MutagenFactory(Protocol):
    def __call__(
        self, filething: str | os.PathLike[str] | io.BytesIO
    ) -> _MutagenFile: ...


class ExportMediaTagger:
    """Apply common tags without transcoding or replacing unknown metadata."""

    def require_supported(self, destination: HostPath) -> None:
        suffix = Path(os.fspath(destination)).suffix.casefold()
        if suffix not in _ID3_EXTENSIONS | _MP4_EXTENSIONS:
            raise ValueError(
                f"iOpenPod cannot embed Library metadata into {suffix or 'this file type'}."
            )

    def prepare(
        self,
        destination: HostPath,
        track: Track,
        artwork: ArtworkImage | None,
    ) -> None:
        self.require_supported(destination)
        path = Path(os.fspath(destination))
        suffix = path.suffix.casefold()
        cover = _jpeg_cover(artwork) if artwork is not None else None
        if suffix in _MP4_EXTENSIONS:
            _tag_mp4(path, track, cover)
        else:
            _tag_id3_container(path, suffix, track, cover)

    def prepare_bytes(
        self,
        data: bytes,
        file_name: str,
        track: Track,
        artwork: ArtworkImage | None = None,
    ) -> bytes:
        """Materialize Rockbox metadata on private bytes with complete tag read-back.

        Storage owns reading and publishing these bytes. This method never opens a
        path, and leaves the caller's original source unchanged on failure.
        """
        suffix = Path(file_name).suffix.casefold()
        if suffix not in _ID3_EXTENSIONS | _MP4_EXTENSIONS:
            raise ValueError(
                f"Rockbox metadata is unsupported for {suffix or 'this file type'}."
            )
        buffer = io.BytesIO(data)
        cover = _jpeg_cover(artwork) if artwork is not None else None
        if suffix in _MP4_EXTENSIONS:
            expected = _tag_mp4(buffer, track, cover)
            factory: _MutagenFactory = cast("_MutagenFactory", MP4)
        else:
            expected = _tag_id3_container(buffer, suffix, track, cover)
            factory = cast(
                "_MutagenFactory",
                (
                    MP3
                    if suffix == ".mp3"
                    else WAVE
                    if suffix in (".wav", ".wave")
                    else AIFF
                ),
            )
        output = buffer.getvalue()
        checked = factory(io.BytesIO(output))
        if _tag_signature(checked.tags) != expected:
            raise ValueError(
                "Rockbox metadata failed read-back verification; this item was not changed."
            )
        return output


def _tag_id3_container(
    path: Path | io.BytesIO,
    suffix: str,
    track: Track,
    cover: bytes | None,
) -> tuple[tuple[str, str], ...]:
    factory = MP3 if suffix == ".mp3" else WAVE if suffix in (".wav", ".wave") else AIFF
    audio = cast("_MutagenFactory", factory)(path)
    if audio.tags is None:
        audio.add_tags()
    if not isinstance(audio.tags, ID3):
        raise ValueError(f"The exported {suffix} file does not support ID3 metadata.")
    tags: Any = audio.tags

    for key in (
        "APIC",
        "COMM",
        "TALB",
        "TBPM",
        "TCMP",
        "TCOM",
        "TCON",
        "TDRC",
        "TIT1",
        "TIT2",
        "TPE1",
        "TPE2",
        "TPOS",
        "TRCK",
        "TSO2",
        "TSOA",
        "TSOC",
        "TSOP",
        "TSOT",
        "TXXX:ITUNESADVISORY",
        "USLT",
    ):
        tags.delall(key)
    metadata = track.metadata
    frame_values = (
        (_ID3_FRAMES.TIT2, track.title),
        (_ID3_FRAMES.TPE1, track.artist),
        (_ID3_FRAMES.TALB, track.album),
        (_ID3_FRAMES.TPE2, track.album_artist),
        (_ID3_FRAMES.TCON, track.genre),
        (_ID3_FRAMES.TDRC, str(track.year) if track.year > 0 else ""),
        (
            _ID3_FRAMES.TRCK,
            _number_pair(track.track_number, metadata.total_tracks),
        ),
        (
            _ID3_FRAMES.TPOS,
            _number_pair(metadata.disc_number, metadata.total_discs),
        ),
        (_ID3_FRAMES.TCOM, metadata.composer),
        (_ID3_FRAMES.TIT1, metadata.grouping),
        (_ID3_FRAMES.TBPM, str(metadata.bpm) if metadata.bpm > 0 else ""),
        (_ID3_FRAMES.TCMP, "1" if metadata.compilation else "0"),
        (_ID3_FRAMES.TSOT, metadata.sort_title),
        (_ID3_FRAMES.TSOP, metadata.sort_artist),
        (_ID3_FRAMES.TSOA, metadata.sort_album),
        (_ID3_FRAMES.TSO2, metadata.sort_album_artist),
        (_ID3_FRAMES.TSOC, metadata.sort_composer),
    )
    for factory, value in frame_values:
        if value:
            tags.add(factory(encoding=3, text=value))
    if metadata.comment:
        tags.add(
            _ID3_FRAMES.COMM(encoding=3, lang="eng", desc="", text=metadata.comment)
        )
    if metadata.lyrics:
        tags.add(
            _ID3_FRAMES.USLT(encoding=3, lang="eng", desc="", text=metadata.lyrics)
        )
    if metadata.content_advisory.value != "unspecified":
        tags.add(
            _ID3_FRAMES.TXXX(
                encoding=3,
                desc="ITUNESADVISORY",
                text="1" if metadata.content_advisory.value == "explicit" else "2",
            )
        )
    if cover is not None:
        tags.add(
            _ID3_FRAMES.APIC(
                encoding=3,
                mime="image/jpeg",
                type=_ID3_FRAMES.PictureType.COVER_FRONT,
                desc="Cover",
                data=cover,
            )
        )
    audio.save(
        path, **({"padding": _no_padding} if isinstance(path, io.BytesIO) else {})
    )
    return _tag_signature(audio.tags)


def _tag_mp4(
    path: Path | io.BytesIO, track: Track, cover: bytes | None
) -> tuple[tuple[str, str], ...]:
    audio = cast("_MutagenFactory", MP4)(path)
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    if tags is None:
        raise ValueError("The exported MP4 file does not support metadata.")
    metadata = track.metadata
    values: dict[str, object | None] = {
        "\xa9nam": [track.title] if track.title else None,
        "\xa9ART": [track.artist] if track.artist else None,
        "\xa9alb": [track.album] if track.album else None,
        "aART": [track.album_artist] if track.album_artist else None,
        "\xa9gen": [track.genre] if track.genre else None,
        "\xa9day": [str(track.year)] if track.year > 0 else None,
        "trkn": [(track.track_number, metadata.total_tracks)]
        if track.track_number > 0
        else None,
        "disk": [(metadata.disc_number, metadata.total_discs)]
        if metadata.disc_number > 0
        else None,
        "\xa9wrt": [metadata.composer] if metadata.composer else None,
        "\xa9grp": [metadata.grouping] if metadata.grouping else None,
        "\xa9cmt": [metadata.comment] if metadata.comment else None,
        "tmpo": [metadata.bpm] if metadata.bpm > 0 else None,
        "cpil": [metadata.compilation],
        "\xa9lyr": [metadata.lyrics] if metadata.lyrics else None,
        "sonm": [metadata.sort_title] if metadata.sort_title else None,
        "soar": [metadata.sort_artist] if metadata.sort_artist else None,
        "soal": [metadata.sort_album] if metadata.sort_album else None,
        "soaa": [metadata.sort_album_artist] if metadata.sort_album_artist else None,
        "soco": [metadata.sort_composer] if metadata.sort_composer else None,
        "rtng": [
            1
            if metadata.content_advisory.value == "explicit"
            else 2
            if metadata.content_advisory.value == "clean"
            else 0
        ],
        "covr": [_MP4_COVER(cover, imageformat=_MP4_COVER.FORMAT_JPEG)]
        if cover is not None
        else None,
    }
    for key, value in values.items():
        if value is None:
            tags.pop(key, None)
        else:
            tags[key] = value
    audio.save(
        path, **({"padding": _no_padding} if isinstance(path, io.BytesIO) else {})
    )
    return _tag_signature(audio.tags)


def _tag_signature(tags: Any) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                str(key),
                str(
                    cast("list[object]", value)[0]
                    if key == "cpil" and isinstance(value, list)
                    else value
                ),
            )
            for key, value in tags.items()
        )
    )


def _no_padding(_info: object) -> int:
    return 0


def _jpeg_cover(artwork: ArtworkImage) -> bytes:
    with Image.frombytes(
        "RGB", (artwork.width, artwork.height), artwork.rgb888
    ) as image:
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=92, optimize=True)
        return output.getvalue()


def _number_pair(number: int, total: int) -> str:
    if number <= 0:
        return ""
    return f"{number}/{total}" if total > 0 else str(number)


__all__ = ["ExportMediaTagger"]
