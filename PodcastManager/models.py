"""Data models for podcast feeds and episodes.

All models are plain dataclasses with to_dict/from_dict for JSON
serialization.  They carry no framework dependencies so the backend
can be tested without PyQt6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Episode status constants ────────────────────────────────────────────────
STATUS_NOT_DOWNLOADED = "not_downloaded"
STATUS_DOWNLOADING = "downloading"
STATUS_DOWNLOADED = "downloaded"
STATUS_ON_IPOD = "on_ipod"


@dataclass
class PodcastEpisode:
    """A single podcast episode within a feed."""

    guid: str                          # Unique episode identifier from RSS
    title: str = ""
    description: str = ""
    audio_url: str = ""                # Enclosure URL
    pub_date: float = 0.0              # Unix timestamp
    duration_seconds: int = 0          # Parsed from itunes:duration
    size_bytes: int = 0                # From enclosure length attribute
    episode_number: Optional[int] = None
    season_number: Optional[int] = None

    # Local state (not from RSS — managed by the app)
    status: str = STATUS_NOT_DOWNLOADED
    downloaded_path: str = ""          # Absolute path on disk when downloaded
    ipod_db_id: int = 0                 # iTunesDB db_id when synced to iPod

    def to_dict(self) -> dict:
        return {
            "guid": self.guid,
            "title": self.title,
            "description": self.description,
            "audio_url": self.audio_url,
            "pub_date": self.pub_date,
            "duration_seconds": self.duration_seconds,
            "size_bytes": self.size_bytes,
            "episode_number": self.episode_number,
            "season_number": self.season_number,
            "status": self.status,
            "downloaded_path": self.downloaded_path,
            "ipod_db_id": self.ipod_db_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PodcastEpisode:
        return cls(
            guid=d["guid"],
            title=d.get("title", ""),
            description=d.get("description", ""),
            audio_url=d.get("audio_url", ""),
            pub_date=d.get("pub_date", 0.0),
            duration_seconds=d.get("duration_seconds", 0),
            size_bytes=d.get("size_bytes", 0),
            episode_number=d.get("episode_number"),
            season_number=d.get("season_number"),
            status=d.get("status", STATUS_NOT_DOWNLOADED),
            downloaded_path=d.get("downloaded_path", ""),
            ipod_db_id=d.get("ipod_db_id", 0),
        )


@dataclass
class PodcastFeed:
    """A podcast feed (show) with its episodes."""

    feed_url: str                      # RSS/Atom feed URL
    title: str = ""
    author: str = ""
    description: str = ""
    artwork_url: str = ""              # Remote artwork URL from feed
    artwork_path: str = ""             # Local cached artwork path
    category: str = ""
    language: str = ""
    last_refreshed: float = 0.0        # Unix timestamp of last refresh

    episodes: list[PodcastEpisode] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "feed_url": self.feed_url,
            "title": self.title,
            "author": self.author,
            "description": self.description,
            "artwork_url": self.artwork_url,
            "artwork_path": self.artwork_path,
            "category": self.category,
            "language": self.language,
            "last_refreshed": self.last_refreshed,
            "episodes": [ep.to_dict() for ep in self.episodes],
        }

    @classmethod
    def from_dict(cls, d: dict) -> PodcastFeed:
        episodes = [PodcastEpisode.from_dict(e) for e in d.get("episodes", [])]
        return cls(
            feed_url=d["feed_url"],
            title=d.get("title", ""),
            author=d.get("author", ""),
            description=d.get("description", ""),
            artwork_url=d.get("artwork_url", ""),
            artwork_path=d.get("artwork_path", ""),
            category=d.get("category", ""),
            language=d.get("language", ""),
            last_refreshed=d.get("last_refreshed", 0.0),
            episodes=episodes,
        )

    @property
    def downloaded_count(self) -> int:
        return sum(1 for e in self.episodes
                   if e.status in (STATUS_DOWNLOADED, STATUS_ON_IPOD))

    @property
    def on_ipod_count(self) -> int:
        return sum(1 for e in self.episodes if e.status == STATUS_ON_IPOD)


@dataclass
class SearchResult:
    """A single result from the iTunes Search API."""

    title: str
    artist: str
    feed_url: str
    artwork_url: str = ""              # 600×600 artwork
    artwork_url_small: str = ""        # 100×100 artwork (for search results)
    genre: str = ""
    track_count: int = 0               # Number of episodes

    @classmethod
    def from_itunes(cls, entry: dict) -> SearchResult:
        """Build from an iTunes Search API result entry."""
        return cls(
            title=entry.get("collectionName", ""),
            artist=entry.get("artistName", ""),
            feed_url=entry.get("feedUrl", ""),
            artwork_url=(
                entry.get("artworkUrl600", "")
                or entry.get("artworkUrl100", "")
            ),
            artwork_url_small=entry.get("artworkUrl100", ""),
            genre=entry.get("primaryGenreName", ""),
            track_count=entry.get("trackCount", 0),
        )
