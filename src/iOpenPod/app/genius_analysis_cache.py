"""Disposable, bounded Host storage for compact Genius acoustic profiles."""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import TYPE_CHECKING, cast

from iOpenPod.app.genius_audio import GENIUS_AUDIO_PROFILE_VERSION, GeniusAudioProfile

if TYPE_CHECKING:
    from collections.abc import Callable

    from storage import AtomicHostFile


_MAX_RECORDS = 50_000
_MAX_BYTES = 64 * 1024 * 1024
_CHECKPOINT_SECONDS = 30.0
_ENVELOPE_RESERVE = 1024


class GeniusProfileCache:
    """Successful analysis only; cached values never authorize media writes."""

    def __init__(self, file: AtomicHostFile | None = None) -> None:
        self._file = file
        self._records: dict[str, tuple[GeniusAudioProfile, bytes]] = {}
        self._size = 0
        self._dirty = False
        self._loaded = False
        self._revision: tuple[int, int, int, int] | None = None
        self._last_save = time.monotonic()

    def load(self, checkpoint: Callable[[], None]) -> None:
        if self._file is None:
            return
        revision = self._file.revision()
        if self._loaded and revision == self._revision:
            return
        self._records.clear()
        self._size = 0
        self._dirty = False
        self._loaded = False
        payload = self._file.read_bytes(max_bytes=_MAX_BYTES)
        if self._file.revision() != revision:
            raise ValueError("The Genius acoustic cache changed while being read")
        if payload is not None:
            try:
                document: object = json.loads(payload, object_pairs_hook=_pairs)
                rows = _records(document)
                decoded: dict[str, tuple[GeniusAudioProfile, bytes]] = {}
                for row in rows:
                    checkpoint()
                    key, profile = _decode(row)
                    if key in decoded:
                        raise ValueError("Duplicate Genius acoustic cache key")
                    decoded[key] = (profile, _json(row))
            except RecursionError as error:
                raise ValueError(
                    "The Genius acoustic cache is nested too deeply"
                ) from error
            self._records = decoded
            self._size = sum(len(row) + 1 for _, row in decoded.values())
        self._revision = revision
        self._loaded = True

    def get(self, key: str) -> GeniusAudioProfile | None:
        record = self._records.get(key)
        return None if record is None else record[0]

    def remember(self, key: str, profile: GeniusAudioProfile) -> None:
        # Run the same validation for freshly produced and restored profiles.
        row: list[object] = [
            key,
            profile.duration_seconds,
            profile.intro,
            profile.body,
            profile.outro,
        ]
        encoded = _json(row)
        _decode(json.loads(encoded))
        if self._records.get(key) == (profile, encoded):
            return
        previous = self._records.pop(key, None)
        if previous is not None:
            self._size -= len(previous[1]) + 1
        required = len(encoded) + 1
        while self._records and (
            len(self._records) >= _MAX_RECORDS
            or self._size + required > _MAX_BYTES - _ENVELOPE_RESERVE
        ):
            _, removed = self._records.pop(next(iter(self._records)))
            self._size -= len(removed) + 1
        if _MAX_RECORDS <= 0 or required > _MAX_BYTES - _ENVELOPE_RESERVE:
            return
        self._records[key] = (profile, encoded)
        self._size += required
        self._dirty = True

    def save(self, checkpoint: Callable[[], None], *, force: bool = False) -> None:
        if (
            self._file is None
            or not self._dirty
            or (not force and time.monotonic() - self._last_save < _CHECKPOINT_SECONDS)
        ):
            return
        checkpoint()
        rows = b"[" + b",".join(row for _, row in self._records.values()) + b"]"
        payload = (
            b'{"version":1,"analysis_version":'
            + str(GENIUS_AUDIO_PROFILE_VERSION).encode("ascii")
            + b',"records":'
            + rows
            + b',"sha256":"'
            + hashlib.sha256(rows).hexdigest().encode("ascii")
            + b'"}'
        )
        if len(payload) > _MAX_BYTES:
            raise ValueError("The Genius acoustic cache exceeds its byte limit")
        checkpoint()
        self._file.replace_bytes(payload)
        self._revision = self._file.revision()
        self._loaded = True
        self._dirty = False
        self._last_save = time.monotonic()


def _records(value: object) -> list[object]:
    if not isinstance(value, dict):
        raise ValueError("The Genius acoustic cache must be an object")
    fields = cast("dict[object, object]", value)
    if set(fields) != {"version", "analysis_version", "records", "sha256"}:
        raise ValueError("The Genius acoustic cache fields are invalid")
    if type(fields["version"]) is not int or fields["version"] != 1:
        raise ValueError("Unsupported Genius acoustic cache format")
    if (
        type(fields["analysis_version"]) is not int
        or fields["analysis_version"] != GENIUS_AUDIO_PROFILE_VERSION
    ):
        raise ValueError("The Genius acoustic analysis version changed")
    raw_rows = fields["records"]
    if not isinstance(raw_rows, list):
        raise ValueError("The Genius acoustic cache records are invalid")
    rows = cast("list[object]", raw_rows)
    if len(rows) > _MAX_RECORDS:
        raise ValueError("Too many Genius acoustic cache records")
    if hashlib.sha256(_json(rows)).hexdigest() != fields["sha256"]:
        raise ValueError("The Genius acoustic cache checksum does not match")
    return rows


def _decode(value: object) -> tuple[str, GeniusAudioProfile]:
    if not isinstance(value, list):
        raise ValueError("Invalid Genius acoustic cache record")
    fields = cast("list[object]", value)
    if len(fields) != 5:
        raise ValueError("Invalid Genius acoustic cache record")
    key, duration, intro, body, outro = fields
    if (
        not isinstance(key, str)
        or len(key) != 64
        or any(character not in "0123456789abcdef" for character in key)
    ):
        raise ValueError("Invalid Genius acoustic cache key")
    duration_seconds = _number(duration)
    if duration_seconds <= 0:
        raise ValueError("Invalid Genius acoustic duration")
    intro_profile = None if intro is None else _segment(intro)
    outro_profile = None if outro is None else _segment(outro)
    if (duration_seconds <= 40) != (intro_profile is None and outro_profile is None):
        raise ValueError("Genius acoustic segments disagree with their duration")
    if (intro_profile is None) != (outro_profile is None):
        raise ValueError("Genius acoustic ending segments must occur together")
    return key, GeniusAudioProfile(
        duration_seconds, intro_profile, _segment(body), outro_profile
    )


def _segment(value: object) -> tuple[float, ...]:
    if not isinstance(value, list):
        raise ValueError("Invalid Genius acoustic segment")
    values = cast("list[object]", value)
    if len(values) != 29:
        raise ValueError("A Genius acoustic segment requires 29 features")
    return tuple(_number(item) for item in values)


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Genius acoustic features must be numeric")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError("Genius acoustic features must be finite") from error
    if not math.isfinite(number):
        raise ValueError("Genius acoustic features must be finite")
    return number


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise ValueError("Duplicate Genius acoustic cache field")
        result[key] = value
    return result


def _json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")
