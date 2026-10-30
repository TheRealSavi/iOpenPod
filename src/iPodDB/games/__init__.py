"""Public game metadata and Phase companion codecs; no filesystem access."""

import plistlib
from dataclasses import dataclass
from typing import cast
from xml.parsers.expat import ExpatError

from iPodDB.games.phase import PhaseBeat, PhaseChart, PhaseTransient
from iPodDB.games.phase import (
    PhaseLibrary as PhaseLibrary,
)
from iPodDB.games.phase import (
    PhaseTrack as PhaseTrack,
)
from iPodDB.games.phase import (
    analysis_relative_path as phase_analysis_relative_path,
)
from iPodDB.games.phase import build_analysis as build_phase_analysis
from iPodDB.games.phase import (
    build_library as build_phase_library,
)
from iPodDB.games.phase import (
    parse_library as parse_phase_library,
)
from iPodDB.games.phase import (
    placeholder_analysis as build_phase_placeholder_analysis,
)
from iPodDB.games.phase import read_playlist_id as read_phase_playlist_id

__all__ = [
    "GameMetadata",
    "PhaseBeat",
    "PhaseChart",
    "PhaseLibrary",
    "PhaseTrack",
    "PhaseTransient",
    "build_phase_analysis",
    "build_phase_library",
    "build_phase_placeholder_analysis",
    "parse_game_manifest",
    "parse_phase_library",
    "phase_analysis_relative_path",
    "read_phase_playlist_id",
]


@dataclass(frozen=True, slots=True)
class GameMetadata:
    title: str
    version: str
    identifier: str


def parse_game_manifest(data: bytes) -> GameMetadata:
    """Read display fields once per game, independently of executable platforms."""
    if not data or len(data) > 1024 * 1024:
        raise ValueError("Game manifest exceeds its supported byte bounds.")
    try:
        decoded: object = plistlib.loads(data)
    except (
        ValueError,
        TypeError,
        OverflowError,
        ExpatError,
        RecursionError,
        plistlib.InvalidFileException,
    ) as error:
        raise ValueError("Invalid game manifest.") from error
    if not isinstance(decoded, dict):
        raise ValueError("Game manifest must be a dictionary.")
    fields = cast("dict[str, object]", decoded)

    def text(key: str) -> str:
        value = fields.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 1024:
            raise ValueError(f"Game manifest has an invalid {key} field.")
        return value.strip()

    return GameMetadata(text("Name"), text("Version"), text("GUID"))
