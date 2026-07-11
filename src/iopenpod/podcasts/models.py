"""Data models for podcast feeds and episodes.

All models are plain dataclasses with to_dict/from_dict for JSON
serialization.  They carry no framework dependencies so the backend
can be tested without PyQt6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

# ── Episode status constants ────────────────────────────────────────────────
STATUS_NOT_DOWNLOADED = "not_downloaded"
STATUS_DOWNLOADING = "downloading"
STATUS_DOWNLOADED = "downloaded"
STATUS_ON_IPOD = "on_ipod"

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp")


def normalize_artwork_url(url: str) -> str:
    """Normalize feed artwork URLs that use a stray extension-only query."""
    raw = (url or "").strip()
    if not raw or "?" not in raw:
        return raw

    parsed = urlsplit(raw)
    query = parsed.query.strip().lower()
    if not query:
        return raw

    normalized_ext = query if query.startswith(".") else f".{query}"
    if normalized_ext not in _IMAGE_EXTENSIONS:
        return raw

    if parsed.path.lower().endswith(_IMAGE_EXTENSIONS):
        return raw

    return urlunsplit((parsed.scheme, parsed.netloc, f"{parsed.path}{normalized_ext}", "", parsed.fragment))


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
    episode_number: int | None = None
    season_number: int | None = None

    # Local state (not from RSS — managed by the app)
    status: str = STATUS_NOT_DOWNLOADED
    downloaded_path: str = ""          # Absolute path on disk when downloaded
    ipod_db_track_id: int = 0           # MHIT db_track_id when synced to iPod
    play_count: int = 0                 # Cumulative completed plays observed on iPod
    last_played: int = 0                # Unix timestamp of last completed play
    listened_override: bool | None = None
    """Manual listened state. None means trust iPod/RSS-derived play history."""

    @property
    def ipod_db_id(self) -> int:
        """Backward-compatible alias for the stored iPod track ID."""
        return self.ipod_db_track_id

    @ipod_db_id.setter
    def ipod_db_id(self, value: int) -> None:
        self.ipod_db_track_id = value

    def to_dict(self) -> dict:
        """Full serialization — used for in-memory transfer and RSS merge."""
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
            "ipod_db_track_id": self.ipod_db_track_id,
            "play_count": self.play_count,
            "last_played": self.last_played,
            "listened_override": self.listened_override,
        }

    def to_dict_stored(self) -> dict:
        """Minimal serialization for on-iPod persistence.

        Only includes fields needed for identity, display when offline,
        playback history, and sync matching.  Full metadata comes from RSS
        on refresh.
        """
        return {
            "guid": self.guid,
            "title": self.title,
            "audio_url": self.audio_url,
            "pub_date": self.pub_date,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "downloaded_path": self.downloaded_path,
            "ipod_db_track_id": self.ipod_db_track_id,
            "play_count": self.play_count,
            "last_played": self.last_played,
            "listened_override": self.listened_override,
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
            ipod_db_track_id=d.get("ipod_db_track_id", d.get("ipod_db_id", 0)),
            play_count=d.get("play_count", 0),
            last_played=d.get("last_played", 0),
            listened_override=d.get("listened_override"),
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

    # ── Per-feed sync settings ───────────────────────────────────────────
    episode_slots: int = 3
    """Maximum number of episodes to keep on the iPod for this feed."""

    fill_mode: str = "newest"
    """How to fill available episode slots.

    ``"newest"``  — always pick the most recently published episode.
    ``"next"``    — pick the next unheard episode (oldest on iPod + 1;
                    if none on iPod, pick the oldest retrieved episode).
    """

    clear_when_listened: bool = True
    """Remove an episode from its slot after it has been marked played."""

    clear_older_than: str = "never"
    """Auto-clear episodes older than a threshold (by date added to iPod).

    One of: ``"immediate"``, ``"1_day"``, ``"3_days"``, ``"1_week"``,
    ``"2_weeks"``, ``"1_month"``, ``"2_months"``, ``"3_months"``,
    ``"never"``.
    """

    clear_method: str = "remove"
    """What to do when a slot is cleared.

    ``"remove"``  — delete the episode from the iPod immediately.
    ``"replace"`` — mark the slot for replacement on the next sync
                    (the episode stays on the iPod until a new one
                    fills its slot).
    """

    def to_dict(self) -> dict:
        """Serialize for on-iPod persistence.

        Only includes episodes that have meaningful local state
        (downloaded, on iPod, or known playback history).  Episodes with
        no local state are omitted — they come from RSS on refresh.  Feed
        description is also omitted (fetched from RSS).
        """
        stored_episodes = [
            ep.to_dict_stored()
            for ep in self.episodes
            if ep.status in (STATUS_DOWNLOADED, STATUS_DOWNLOADING,
                             STATUS_ON_IPOD)
            or ep.play_count > 0
            or ep.last_played > 0
            or ep.listened_override is not None
        ]
        return {
            "feed_url": self.feed_url,
            "title": self.title,
            "author": self.author,
            "artwork_url": self.artwork_url,
            "artwork_path": self.artwork_path,
            "category": self.category,
            "language": self.language,
            "last_refreshed": self.last_refreshed,
            "episodes": stored_episodes,
            "episode_slots": self.episode_slots,
            "fill_mode": self.fill_mode,
            "clear_when_listened": self.clear_when_listened,
            "clear_older_than": self.clear_older_than,
            "clear_method": self.clear_method,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PodcastFeed:
        """Deserialize from on-iPod JSON.

        Episodes loaded here are only those with local state (on iPod
        or downloaded).  The full catalog is populated when the RSS
        feed is refreshed and merged.
        """
        episodes = [PodcastEpisode.from_dict(e) for e in d.get("episodes", [])]
        return cls(
            feed_url=d["feed_url"],
            title=d.get("title", ""),
            author=d.get("author", ""),
            description=d.get("description", ""),
            artwork_url=normalize_artwork_url(d.get("artwork_url", "")),
            artwork_path=d.get("artwork_path", ""),
            category=d.get("category", ""),
            language=d.get("language", ""),
            last_refreshed=d.get("last_refreshed", 0.0),
            episodes=episodes,
            episode_slots=d.get("episode_slots", 3),
            fill_mode=d.get("fill_mode", "newest"),
            clear_when_listened=d.get("clear_when_listened", True),
            clear_older_than=d.get("clear_older_than", "never"),
            clear_method=d.get("clear_method", "remove"),
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
            artwork_url=normalize_artwork_url(
                entry.get("artworkUrl600", "")
                or entry.get("artworkUrl100", "")
            ),
            artwork_url_small=normalize_artwork_url(entry.get("artworkUrl100", "")),
            genre=entry.get("primaryGenreName", ""),
            track_count=entry.get("trackCount", 0),
        )
