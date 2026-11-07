"""Game discovery through virtual, read-only Storage sessions."""

import plistlib
from pathlib import Path

import pytest

from iOpenPod.app.services.game_library import read_game_catalog
from storage import Storage
from storage.testing import VirtualStoragePlatform


def test_catalog_uses_manifests_one_card_per_folder_and_never_writes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "device"
    games = root / "iPod_Control/Games_RO"
    for folder, name, version in [
        ("1D000", "Phase", "1.0.0"),
        ("123", "A Game", "1.2"),
    ]:
        game = games / folder
        game.mkdir(parents=True)
        (game / "Manifest.plist").write_bytes(
            plistlib.dumps(
                {
                    "Name": name,
                    "Version": version,
                    "GUID": f"id-{folder}",
                    "Platforms": [{}, {}, {}],
                }
            )
        )
        (game / "iTunesArtwork").write_bytes(b"image bytes")
    (games / "11016/CustomCardbacks").mkdir(parents=True)
    (games / "bad").mkdir()
    (games / "bad/Manifest.plist").write_bytes(b"invalid")
    before = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    with storage.open_session(storage.discover().volumes[0]) as session:
        catalog = read_game_catalog(session, lambda: None)
    assert [game.title for game in catalog.games] == ["A Game", "bad", "Phase"]
    assert catalog.games[2].version == "1.0.0"
    assert catalog.games[2].artwork == b"image bytes"
    assert catalog.games[2].directory == "1D000"
    assert catalog.games[2].identifier == "id-1D000"
    assert catalog.games[1].identifier == ""
    assert len(catalog.issues) == 1
    assert before == {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


def test_missing_games_directory_is_empty_and_cancellation_propagates(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)

    def cancelled() -> None:
        raise RuntimeError("cancelled")

    with storage.open_session(storage.discover().volumes[0]) as session:
        assert not read_game_catalog(session, lambda: None).games
        with pytest.raises(RuntimeError, match="cancelled"):
            read_game_catalog(session, cancelled)
