"""Catalog filtering uses the selected marketed family, not available games."""

import base64
import json

import pytest

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.services.game_catalog import catalog_games, parse_catalog


@pytest.mark.parametrize(
    ("family", "generation", "count"),
    [
        ("iPod", "5th Gen", 56),
        ("iPod", "5.5th Gen", 56),
        ("iPod Classic", "6th Gen", 49),
        ("iPod Classic", "6.5th Gen", 49),
        ("iPod Classic", "7th Gen", 49),
        ("iPod Nano", "3rd Gen", 49),
        ("iPod Nano", "4th Gen", 49),
        ("iPod Nano", "5th Gen", 49),
        ("iPod Nano", "6th Gen", 0),
    ],
)
def test_shipped_catalog_is_filtered_for_video_family(
    family: str, generation: str, count: int
) -> None:
    profile = next(
        p
        for p in DEFAULT_DEVICE_REGISTRY.profiles
        if p.family == family and p.generation == generation
    )
    games = catalog_games(profile)
    assert len(games) == count
    assert all(game.artwork and game.title and game.version for game in games)
    assert any(game.title == "Vortex Demo" for game in games) is (count == 56)


def entry(compatibility: object = "All") -> dict[str, object]:
    return {
        "Name": "Game",
        "Version": "1.0",
        "GUID": "example",
        "Compatibility": compatibility,
        "ArtworkMimeType": "image/jpeg",
        "ArtworkBase64": base64.b64encode(b"image").decode("ascii"),
    }


@pytest.mark.parametrize("failure", ["duplicate", "base64", "compatibility", "root"])
def test_invalid_catalog_is_rejected(failure: str) -> None:
    row = entry()
    rows: object = [row]
    if failure == "duplicate":
        rows = [row, row]
    elif failure == "base64":
        row["ArtworkBase64"] = "invalid!"
    elif failure == "compatibility":
        row["Compatibility"] = []
    else:
        rows = {}
    with pytest.raises(ValueError):
        parse_catalog(json.dumps(rows).encode(), video_only=False)
