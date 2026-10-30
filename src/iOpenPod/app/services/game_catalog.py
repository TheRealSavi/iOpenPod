"""Read the bundled, self-contained game offering for one device family."""

from __future__ import annotations

import base64
import binascii
import json
from importlib.resources import files
from typing import TYPE_CHECKING, cast

from iOpenPod.app.services.game_library import InstalledGame

if TYPE_CHECKING:
    from device_registry import DeviceProfile


def catalog_games(profile: DeviceProfile) -> tuple[InstalledGame, ...]:
    """Filter Video-only entries before exposing any artwork or display records."""
    if not profile.capabilities.supports_games:
        return ()
    data = files("iOpenPod").joinpath("assets/games/game-catalog.json").read_bytes()
    return parse_catalog(
        data,
        video_only=profile.family == "iPod"
        and profile.generation in {"5th Gen", "5.5th Gen"},
    )


def parse_catalog(data: bytes, *, video_only: bool) -> tuple[InstalledGame, ...]:
    """Validate the application resource without accessing a device filesystem."""
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("Game catalog exceeds the supported size.")
    decoded: object = json.loads(data)
    if not isinstance(decoded, list):
        raise ValueError("Invalid game catalog entries.")
    rows = cast("list[object]", decoded)
    if len(rows) > 512:
        raise ValueError("Invalid game catalog entries.")
    result: list[InstalledGame] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in rows:
        if not isinstance(entry, dict):
            raise ValueError("Invalid game catalog record.")
        row = cast("dict[str, object]", entry)
        name, version, guid = row.get("Name"), row.get("Version"), row.get("GUID")
        compatibility = row.get("Compatibility")
        if (
            not all(
                isinstance(value, str) and 0 < len(value) <= 1024
                for value in (name, version, guid)
            )
            or not isinstance(compatibility, str)
            or compatibility not in {"All", "VideoOnly"}
        ):
            raise ValueError("Invalid game catalog metadata.")
        # Explicit narrowing also keeps strict editor checking on the resource.
        assert (
            isinstance(name, str) and isinstance(version, str) and isinstance(guid, str)
        )
        assert isinstance(compatibility, str)
        key = (guid, version, compatibility)
        if key in seen:
            raise ValueError("Duplicate game catalog identity.")
        seen.add(key)
        if compatibility == "VideoOnly" and not video_only:
            continue
        encoded = row.get("ArtworkBase64")
        if (
            row.get("ArtworkMimeType") != "image/jpeg"
            or not isinstance(encoded, str)
            or len(encoded) > 4 * 1024 * 1024
        ):
            raise ValueError("Invalid game catalog artwork.")
        try:
            artwork = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("Invalid game catalog artwork encoding.") from error
        result.append(InstalledGame(guid, name, version, artwork, guid))
    return tuple(result)
