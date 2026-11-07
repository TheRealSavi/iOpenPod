"""Versioned, lossless serialization of observed stream choices."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, fields
from fractions import Fraction
from typing import cast

from iOpenPod.app.media.models import MediaStream, MediaTag, StreamKind
from iOpenPod.app.media.stream_selection import MediaStreamSelection
from iOpenPod.app.media.subtitles import supports


def selection_document(selection: MediaStreamSelection) -> dict[str, object]:
    document: dict[str, object] = {
        "version": 1 if selection.alternate_audio is None else 2,
        "video": _stream_document(selection.video),
        "audio": _stream_document(selection.audio),
        "subtitles": [_stream_document(s) for s in selection.subtitles],
        "captions": [_stream_document(s) for s in selection.captions],
    }
    if selection.alternate_audio is not None:
        document["alternate_audio"] = _stream_document(selection.alternate_audio)
    return document


def selection_digest(selection: MediaStreamSelection | None) -> str | None:
    if selection is None:
        return None
    document = selection_document(selection)
    if any(
        supports(stream.codec) and stream.codec not in {"mov_text", "tx3g"}
        for stream in selection.subtitles
    ):
        # Revision 1 fixed layout; revision 2 also bounds the movie clock.
        # Reprepare older saved text-conversion choices once for the Classic.
        # Saved choices themselves retain their existing serialization format.
        document["text_subtitle_layout"] = 2
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def selection_from_document(value: object) -> MediaStreamSelection:
    row = _object(value)
    version = row.get("version")
    expected = {"version", "video", "audio", "subtitles", "captions"}
    if type(version) is int and version == 2:
        expected.add("alternate_audio")
    if (
        type(version) is not int
        or version not in (1, 2)
        or set(row) != expected
        or (version == 2 and row["alternate_audio"] is None)
    ):
        raise ValueError("Unsupported stream selection format")

    def streams(key: str) -> tuple[MediaStream, ...]:
        values = row[key]
        if not isinstance(values, list):
            raise ValueError("Expected a stream list")
        result = tuple(_stream_from_document(s) for s in cast("list[object]", values))
        if any(s is None for s in result):
            raise ValueError("A subtitle or caption cannot be absent")
        return cast("tuple[MediaStream, ...]", result)

    return MediaStreamSelection(
        _stream_from_document(row["video"]),
        _stream_from_document(row["audio"]),
        streams("subtitles"),
        streams("captions"),
        _stream_from_document(row["alternate_audio"]) if version == 2 else None,
    )


def _stream_document(stream: MediaStream | None) -> dict[str, object] | None:
    if stream is None:
        return None
    return {
        key: str(value) if isinstance(value, Fraction) else value
        for key, value in asdict(stream).items()
    }


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected a stream selection object")
    if any(not isinstance(k, str) for k in cast("dict[object, object]", value)):
        raise ValueError("Expected a stream selection object")
    return cast("dict[str, object]", value)


def _stream_from_document(value: object) -> MediaStream | None:
    if value is None:
        return None
    row = _object(value)
    if set(row) != {f.name for f in fields(MediaStream)}:
        raise ValueError("Invalid saved stream fields")

    def text(key: str) -> str:
        value = row[key]
        if not isinstance(value, str):
            raise ValueError("Expected stream text")
        return value

    def integer(key: str) -> int | None:
        value = row[key]
        if value is not None and type(value) is not int:
            raise ValueError("Expected a stream integer")
        return value

    def fraction(key: str) -> Fraction | None:
        try:
            return None if row[key] is None else Fraction(text(key))
        except ZeroDivisionError as error:
            raise ValueError("Invalid saved stream timing") from error

    def boolean(key: str) -> bool | None:
        value = row[key]
        if value is not None and type(value) is not bool:
            raise ValueError("Expected a stream boolean")
        return value

    index = integer("index")
    if index is None or index < 0:
        raise ValueError("Invalid stream index")
    dispositions = row["dispositions"]
    tags = row["tags"]
    if not isinstance(dispositions, list):
        raise ValueError("Invalid stream dispositions")
    parsed_dispositions: list[str] = []
    for disposition in cast("list[object]", dispositions):
        if not isinstance(disposition, str):
            raise ValueError("Invalid stream dispositions")
        parsed_dispositions.append(disposition)
    if not isinstance(tags, list):
        raise ValueError("Invalid stream tags")
    parsed_tags: list[MediaTag] = []
    for tag in cast("list[object]", tags):
        entry = _object(tag)
        if (
            set(entry) != {"name", "value"}
            or not isinstance(entry["name"], str)
            or not isinstance(entry["value"], str)
        ):
            raise ValueError("Invalid stream tag")
        parsed_tags.append(MediaTag(entry["name"], entry["value"]))
    return MediaStream(
        index=index,
        kind=StreamKind(text("kind")),
        codec=text("codec"),
        codec_tag=text("codec_tag"),
        profile=text("profile"),
        level=integer("level"),
        duration_seconds=fraction("duration_seconds"),
        start_seconds=fraction("start_seconds"),
        time_base=fraction("time_base"),
        duration_ticks=integer("duration_ticks"),
        bitrate_bps=integer("bitrate_bps"),
        sample_rate_hz=integer("sample_rate_hz"),
        channels=integer("channels"),
        channel_layout=text("channel_layout"),
        bits_per_sample=integer("bits_per_sample"),
        bits_per_raw_sample=integer("bits_per_raw_sample"),
        width=integer("width"),
        height=integer("height"),
        pixel_format=text("pixel_format"),
        frame_rate=fraction("frame_rate"),
        nominal_frame_rate=fraction("nominal_frame_rate"),
        sample_aspect_ratio=fraction("sample_aspect_ratio"),
        attached_picture=boolean("attached_picture"),
        default=boolean("default"),
        dispositions=tuple(parsed_dispositions),
        tags=tuple(parsed_tags),
    )
