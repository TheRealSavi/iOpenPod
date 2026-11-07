"""Durable Host stream preferences, independent of disposable scan caches."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from iOpenPod.app.media.stream_selection_codec import (
    selection_document,
    selection_from_document,
)
from iOpenPod.app.sync_plan import host_path_identity

if TYPE_CHECKING:
    from iOpenPod.app.media.stream_selection import MediaStreamSelection
    from storage import AtomicHostFile

_MAX_FILE_BYTES = 64 * 1024 * 1024


class MediaStreamPreferences:
    """Save choices atomically before exposing them as accepted user intent.

    None provides an isolated in-memory store for tests. Production uses a Host
    configuration file. Missing sources are retained so temporarily unavailable
    folders and cancelled scans cannot erase preferences.
    """

    def __init__(self, host_file: AtomicHostFile | None = None) -> None:
        self._file = host_file
        self._choices: dict[str, MediaStreamSelection] = {}

    def load(self) -> dict[str, MediaStreamSelection]:
        if self._file is not None:
            payload = self._file.read_bytes(max_bytes=_MAX_FILE_BYTES)
            if payload is None:
                self._choices = {}
            else:
                document = json.loads(payload)
                if not isinstance(document, dict):
                    raise ValueError(
                        "Invalid saved stream preferences; the existing file was preserved"
                    )
                document = cast("dict[object, object]", document)
                if (
                    set(document) != {"version", "choices"}
                    or document["version"] != 1
                    or not isinstance(document["choices"], dict)
                ):
                    raise ValueError(
                        "Invalid saved stream preferences; the existing file was preserved"
                    )
                choices: dict[str, MediaStreamSelection] = {}
                for path, value in cast(
                    "dict[object, object]", document["choices"]
                ).items():
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("Invalid saved stream source")
                    identity = host_path_identity(path)
                    if identity in choices:
                        raise ValueError("Duplicate saved stream source")
                    choices[identity] = selection_from_document(value)
                self._choices = choices
        return self._choices.copy()

    def set(self, path: str, selection: MediaStreamSelection | None) -> None:
        # Merge current durable intent, never overwrite unreadable user choices.
        choices = self.load()
        identity = host_path_identity(path)
        if selection is None:
            choices.pop(identity, None)
        else:
            choices[identity] = selection
        if choices == self._choices:
            return
        if self._file is not None:
            payload = {
                "version": 1,
                "choices": {
                    p: selection_document(s) for p, s in sorted(choices.items())
                },
            }
            encoded = (
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            ).encode()
            if len(encoded) > _MAX_FILE_BYTES:
                raise ValueError(
                    "The saved stream preferences exceed the supported size"
                )
            self._file.replace_bytes(encoded)
        self._choices = choices
