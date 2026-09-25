"""Reserve short, firmware-compatible Track paths without filesystem access."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from secrets import randbelow
from threading import Lock
from typing import TYPE_CHECKING

from storage import DevicePath

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

_NAMES_PER_DIRECTORY = 26**4
_TRACK_PATH = re.compile(
    r"ipod_control/music/f([0-9]{2,})/([a-z]{4})(?:\.[^/]+)?", re.ASCII
)
_EXTENSIONS = frozenset({"mp3", "m4a", "m4b", "m4v", "mp4", "wav", "aif", "aiff"})


class MusicPathAllocator:
    """Reserve four-letter names across the Device Profile's music directories.

    Reserve stems regardless of extension, including paths scheduled for removal:
    old files must survive until the new Library is safely published. The optional
    existence check is supplied by Storage's caller and runs serially. Storage must
    still enforce an absence precondition at commit to catch later external writes.
    """

    def __init__(
        self,
        directory_count: int,
        occupied_paths: Iterable[str] = (),
        *,
        exists: Callable[[DevicePath], bool] | None = None,
    ) -> None:
        if directory_count < 1:
            raise ValueError("Track filenames require at least one music directory.")
        self._directory_count = directory_count
        self._capacity = directory_count * _NAMES_PER_DIRECTORY
        self._cursor = randbelow(self._capacity)
        self._reserved: set[int] = set()
        self._exists = exists
        self._lock = Lock()
        for path in occupied_paths:
            normalized = (
                PurePosixPath(path.replace("\\", "/").replace(":", "/"))
                .as_posix()
                .lstrip("/")
                .casefold()
            )
            match = _TRACK_PATH.fullmatch(normalized)
            if match is None:
                continue
            directory = int(match[1])
            if directory >= directory_count or match[1] != f"{directory:02d}":
                continue
            name = 0
            for letter in match[2]:
                name = name * 26 + ord(letter) - ord("a")
            if name < _NAMES_PER_DIRECTORY:
                self._reserved.add(name * directory_count + directory)

    def allocate(
        self, extension: str, *, checkpoint: Callable[[], None] | None = None
    ) -> str:
        """Select and reserve one unused name; collisions never lengthen it."""
        extension = extension.casefold()
        if extension not in _EXTENSIONS:
            raise ValueError("Choose a supported iPod media filename extension.")
        with self._lock:
            while len(self._reserved) < self._capacity:
                if checkpoint is not None:
                    checkpoint()
                slot = self._cursor
                self._cursor = (slot + 1) % self._capacity
                if slot in self._reserved:
                    continue
                self._reserved.add(slot)
                name, directory = divmod(slot, self._directory_count)
                letters: list[str] = []
                for _ in range(4):
                    name, digit = divmod(name, 26)
                    letters.append(chr(ord("A") + digit))
                stem = "".join(reversed(letters))
                path = f"iPod_Control/Music/F{directory:02d}/{stem}.{extension}"
                if self._exists is None or not self._exists(DevicePath(path)):
                    return path
        raise ValueError(
            "No unused four-letter Track filenames remain on this iPod. "
            "Remove unwanted Tracks in a separate saved operation, then rescan "
            "and retry. Existing files were preserved."
        )
