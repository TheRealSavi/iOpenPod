"""Config file loading for iopenpod-sync CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

DEFAULT_CONFIG_PATH = Path("~/.config/iopenpodcli/config.yaml").expanduser()


@dataclass
class PodcastConfig:
    url: str
    keep_episodes: int = 5


@dataclass
class SyncConfig:
    # Music source — directory to scan for audio files
    music_path: str = "~/Music"
    # M3U / folder-based playlist files to sync; relative paths resolve from music_path
    playlists: list[str] = field(default_factory=list)
    # Podcast feeds
    podcasts: list[PodcastConfig] = field(default_factory=list)
    # Pull ratings from iPod back to local file tags (via mutagen)
    pull_ratings: bool = True
    # Pull play counts from iPod back to local file tags
    pull_playcounts: bool = True
    # "ipod_wins" | "pc_wins" | "higher_wins"
    rating_strategy: str = "ipod_wins"


def load_config(path: Path | str | None = None) -> SyncConfig:
    config_path = Path(path).expanduser() if path else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        return SyncConfig()

    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to read the config file. Install it with: pip install pyyaml"
        )

    raw: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}

    podcasts = [
        PodcastConfig(
            url=p["url"] if isinstance(p, dict) else str(p),
            keep_episodes=int(p.get("keep_episodes", 5)) if isinstance(p, dict) else 5,
        )
        for p in raw.get("podcasts", [])
    ]

    return SyncConfig(
        music_path=str(raw.get("music_path", "~/Music")),
        playlists=[str(p) for p in raw.get("playlists", [])],
        podcasts=podcasts,
        pull_ratings=bool(raw.get("pull_ratings", True)),
        pull_playcounts=bool(raw.get("pull_playcounts", True)),
        rating_strategy=str(raw.get("rating_strategy", "ipod_wins")),
    )
