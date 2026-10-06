"""Write semantic Library metadata and artwork into exported Host media files."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Protocol, cast

import mutagen.id3 as id3_frames
from mutagen import MutagenError
from mutagen.aiff import AIFF
from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.wave import WAVE
from PIL import Image, ImageChops

if TYPE_CHECKING:
    from iPodDB.library import Track
    from storage import HostPath

_ID3_EXTENSIONS = frozenset((".mp3", ".wav", ".wave", ".aif", ".aiff", ".aifc"))
_RAW_AAC_EXTENSIONS = frozenset((".aac", ".adif", ".adts"))
_MP4_EXTENSIONS = frozenset((".m4a", ".m4b", ".m4v", ".mp4", ".mov"))
_ID3_FRAMES: Any = id3_frames
_ID3_TAG: Any = ID3
_MP4_COVER: Any = MP4Cover


class _MutagenFile(Protocol):
    tags: Any

    def add_tags(self) -> None: ...

    def save(self, *args: Any, **kwargs: Any) -> None: ...


class _MutagenFactory(Protocol):
    def __call__(
        self, filething: str | os.PathLike[str] | BinaryIO
    ) -> _MutagenFile: ...


class _Artwork(Protocol):
    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...

    @property
    def rgb888(self) -> bytes: ...


class ExportMediaTagger:
    """Apply common tags without transcoding or replacing unknown metadata."""

    def require_supported(
        self, destination: HostPath, *, file_name: str | None = None
    ) -> None:
        suffix = Path(file_name or os.fspath(destination)).suffix.casefold()
        if suffix not in _ID3_EXTENSIONS | _RAW_AAC_EXTENSIONS | _MP4_EXTENSIONS:
            raise ValueError(
                f"iOpenPod cannot embed Library metadata into {suffix or 'this file type'}."
            )

    def prepare(
        self,
        destination: HostPath,
        track: Track,
        artwork: _Artwork | None,
        *,
        preserve_artwork: bool = False,
        file_name: str | None = None,
    ) -> None:
        path = Path(os.fspath(destination))
        self._prepare(
            path,
            file_name or path.name,
            track,
            artwork,
            preserve_artwork=preserve_artwork,
        )

    def prepare_bytes(
        self,
        data: bytes,
        file_name: str,
        track: Track,
        artwork: _Artwork | None = None,
        *,
        preserve_artwork: bool = False,
    ) -> bytes:
        """Materialize Rockbox metadata on private bytes with complete tag read-back.

        Storage owns reading and publishing these bytes. This method never opens a
        path, and leaves the caller's original source unchanged on failure.
        """
        buffer = io.BytesIO(data)
        self.prepare_stream(
            buffer, file_name, track, artwork, preserve_artwork=preserve_artwork
        )
        return buffer.getvalue()

    def prepare_stream(
        self,
        buffer: BinaryIO,
        file_name: str,
        track: Track,
        artwork: _Artwork | None = None,
        *,
        preserve_artwork: bool = False,
    ) -> None:
        """Retag and verify one private seekable Storage capture, with bounded memory."""
        try:
            self._prepare(
                buffer, file_name, track, artwork, preserve_artwork=preserve_artwork
            )
        except MutagenError as error:
            raise ValueError(
                f"Could not prepare file tags for {file_name}: {error}"
            ) from error

    def _prepare(
        self,
        buffer: Path | BinaryIO,
        file_name: str,
        track: Track,
        artwork: _Artwork | None,
        *,
        preserve_artwork: bool,
    ) -> None:
        suffix = Path(file_name).suffix.casefold()
        if suffix not in _ID3_EXTENSIONS | _RAW_AAC_EXTENSIONS | _MP4_EXTENSIONS:
            raise ValueError(
                f"Rockbox metadata is unsupported for {suffix or 'this file type'}."
            )
        cover = _jpeg_cover(artwork) if artwork is not None else None
        if suffix in _MP4_EXTENSIONS:
            expected = _tag_mp4(buffer, track, cover, preserve_artwork=preserve_artwork)
            factory: _MutagenFactory = cast("_MutagenFactory", MP4)
        elif suffix in _RAW_AAC_EXTENSIONS:
            expected = _tag_raw_aac(
                buffer, track, cover, preserve_artwork=preserve_artwork
            )
            if not isinstance(buffer, Path):
                buffer.seek(0)
            checked = _ID3_TAG(buffer)
            if _tag_signature(checked) != expected:
                raise ValueError(
                    "Rockbox metadata failed read-back verification; this item was not changed."
                )
            return
        else:
            expected = _tag_id3_container(
                buffer, suffix, track, cover, preserve_artwork=preserve_artwork
            )
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
        if not isinstance(buffer, Path):
            buffer.seek(0)
        checked = factory(buffer)
        if _tag_signature(checked.tags) != expected:
            raise ValueError(
                "Rockbox metadata failed read-back verification; this item was not changed."
            )


def _tag_id3_container(
    path: Path | BinaryIO,
    suffix: str,
    track: Track,
    cover: bytes | None,
    *,
    preserve_artwork: bool = False,
) -> tuple[tuple[str, str], ...]:
    factory = MP3 if suffix == ".mp3" else WAVE if suffix in (".wav", ".wave") else AIFF
    audio = cast("_MutagenFactory", factory)(path)
    if audio.tags is None:
        audio.add_tags()
    if not isinstance(audio.tags, ID3):
        raise ValueError(f"The exported {suffix} file does not support ID3 metadata.")
    tags: Any = audio.tags

    _apply_id3_tags(tags, track, cover, preserve_artwork=preserve_artwork)
    audio.save(path, **({"padding": _no_padding} if not isinstance(path, Path) else {}))
    return _tag_signature(audio.tags)


def _tag_raw_aac(
    path: Path | BinaryIO,
    track: Track,
    cover: bytes | None,
    *,
    preserve_artwork: bool = False,
) -> tuple[tuple[str, str], ...]:
    """Write an ID3 prefix because Mutagen's AAC wrapper is read-only for tags."""
    try:
        tags = _ID3_TAG(path)
    except ID3NoHeaderError:
        tags = _ID3_TAG()
    _apply_id3_tags(tags, track, cover, preserve_artwork=preserve_artwork)
    tags.save(path, **({"padding": _no_padding} if not isinstance(path, Path) else {}))
    return _tag_signature(tags)


def _apply_id3_tags(
    tags: Any,
    track: Track,
    cover: bytes | None,
    *,
    preserve_artwork: bool,
) -> None:
    keys = (
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
    )
    for key in keys:
        tags.delall(key)
    if not preserve_artwork:
        tags.delall("APIC")
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


def _tag_mp4(
    path: Path | BinaryIO,
    track: Track,
    cover: bytes | None,
    *,
    preserve_artwork: bool = False,
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
        "cpil": metadata.compilation,
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
    }
    if cover is not None:
        values["covr"] = [_MP4_COVER(cover, imageformat=_MP4_COVER.FORMAT_JPEG)]
    elif not preserve_artwork:
        values["covr"] = None
    for key, value in values.items():
        if value is None:
            tags.pop(key, None)
        else:
            tags[key] = value
    audio.save(path, **({"padding": _no_padding} if not isinstance(path, Path) else {}))
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


def _jpeg_cover(artwork: _Artwork) -> bytes:
    with Image.frombytes(
        "RGB", (artwork.width, artwork.height), artwork.rgb888
    ) as image:
        channels = image.split()
        try:
            grayscale = (
                ImageChops.difference(channels[0], channels[1]).getbbox() is None
                and ImageChops.difference(channels[0], channels[2]).getbbox() is None
            )
        finally:
            for channel in channels:
                channel.close()
        output = io.BytesIO()
        if grayscale:
            with image.convert("L") as compact:
                compact.save(output, format="JPEG", quality=70, optimize=True)
        else:
            image.save(output, format="JPEG", quality=92, optimize=True)
        return output.getvalue()


def _number_pair(number: int, total: int) -> str:
    if number <= 0:
        return ""
    return f"{number}/{total}" if total > 0 else str(number)


__all__ = ["ExportMediaTagger"]
