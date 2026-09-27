"""Immutable podcast records shared by controllers and presentation adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SubscriptionSource(StrEnum):
    """How a subscription first became part of this iPod's catalog."""

    USER = "user"
    DEVICE = "device"


class PodcastIssueCode(StrEnum):
    """Stable failure vocabulary suitable for translation at the GUI edge."""

    SUBSCRIPTIONS_UNREADABLE = "subscriptions_unreadable"
    HISTORY_UNREADABLE = "history_unreadable"
    PERSISTENCE_FAILED = "persistence_failed"
    FEED_REFRESH_FAILED = "feed_refresh_failed"


class PodcastFillMode(StrEnum):
    NEWEST = "newest"
    NEXT = "next"


class PodcastClearAge(StrEnum):
    IMMEDIATE = "immediate"
    DAY = "1_day"
    THREE_DAYS = "3_days"
    WEEK = "1_week"
    TWO_WEEKS = "2_weeks"
    MONTH = "1_month"
    TWO_MONTHS = "2_months"
    THREE_MONTHS = "3_months"
    NEVER = "never"

    @property
    def seconds(self) -> int | None:
        """Elapsed time on the iPod, independent of publication time."""
        days = {
            PodcastClearAge.IMMEDIATE: 0,
            PodcastClearAge.DAY: 1,
            PodcastClearAge.THREE_DAYS: 3,
            PodcastClearAge.WEEK: 7,
            PodcastClearAge.TWO_WEEKS: 14,
            PodcastClearAge.MONTH: 30,
            PodcastClearAge.TWO_MONTHS: 60,
            PodcastClearAge.THREE_MONTHS: 90,
        }
        value = days.get(self)
        return None if value is None else value * 86_400


class PodcastClearMethod(StrEnum):
    REMOVE = "remove"
    REPLACE = "replace"


@dataclass(frozen=True, slots=True)
class PodcastSyncSettings:
    """Per-show retention policy matching the Original iOpenPod controls."""

    episode_slots: int = 3
    fill_mode: PodcastFillMode = PodcastFillMode.NEWEST
    clear_when_listened: bool = True
    clear_older_than: PodcastClearAge = PodcastClearAge.NEVER
    clear_method: PodcastClearMethod = PodcastClearMethod.REMOVE

    def __post_init__(self) -> None:
        if type(self.episode_slots) is not int:
            raise ValueError("Podcast episode slots must be an integer")
        if not 1 <= self.episode_slots <= 50:
            raise ValueError("Podcast episode slots must be between 1 and 50")
        if type(self.fill_mode) is not PodcastFillMode:
            raise ValueError("Podcast fill mode must be a supported value")
        if type(self.clear_when_listened) is not bool:
            raise ValueError("Podcast clear-when-listened must be true or false")
        if type(self.clear_older_than) is not PodcastClearAge:
            raise ValueError("Podcast clear age must be a supported value")
        if type(self.clear_method) is not PodcastClearMethod:
            raise ValueError("Podcast clear method must be a supported value")


@dataclass(frozen=True, slots=True)
class PodcastIssue:
    code: PodcastIssueCode
    message: str
    subject: str = ""


@dataclass(frozen=True, slots=True)
class PodcastEpisode:
    """One episode plus state projected from the currently Active iPod."""

    episode_id: str
    guid: str = ""
    title: str = ""
    description: str = ""
    enclosure_url: str = ""
    published_at: int = 0
    duration_seconds: int = 0
    size_bytes: int = 0
    episode_number: int | None = None
    season_number: int | None = None
    on_device: bool = False
    track_id: int | None = None
    listened: bool = False
    listened_override: bool | None = None
    play_count: int = 0
    last_played: int = 0
    automatically_cleared: bool = False

    def __post_init__(self) -> None:
        if not self.episode_id.strip():
            raise ValueError("A Podcast Episode ID must not be empty")
        for name, value in (
            ("published_at", self.published_at),
            ("duration_seconds", self.duration_seconds),
            ("size_bytes", self.size_bytes),
            ("play_count", self.play_count),
            ("last_played", self.last_played),
        ):
            if value < 0:
                raise ValueError(f"Podcast Episode {name} must not be negative")
        if self.track_id is not None and self.track_id == 0:
            raise ValueError("An on-device Podcast Track ID must not be zero")
        if self.on_device != (self.track_id is not None):
            raise ValueError("Podcast on-device state and Track ID must agree")
        if type(self.automatically_cleared) is not bool:
            raise ValueError("Podcast automatic-clear state must be true or false")


@dataclass(frozen=True, slots=True)
class PodcastSubscription:
    """One subscribed show and its current runtime episode catalog."""

    subscription_id: str
    feed_url: str
    title: str
    source: SubscriptionSource
    author: str = ""
    description: str = ""
    artwork_url: str = ""
    artwork_id: int = 0
    category: str = ""
    language: str = ""
    last_refreshed: int = 0
    episodes: tuple[PodcastEpisode, ...] = ()
    sync_settings: PodcastSyncSettings = PodcastSyncSettings()

    def __post_init__(self) -> None:
        if not self.subscription_id.strip():
            raise ValueError("A Podcast Subscription ID must not be empty")
        if not self.title.strip():
            raise ValueError("A Podcast Subscription title must not be empty")
        if self.last_refreshed < 0:
            raise ValueError("A Podcast refresh time must not be negative")
        if self.artwork_id < 0:
            raise ValueError("A Podcast Artwork ID must not be negative")
        episode_ids = tuple(episode.episode_id for episode in self.episodes)
        if len(episode_ids) != len(set(episode_ids)):
            raise ValueError("Podcast Episode IDs must be unique within a subscription")

    @property
    def on_device_count(self) -> int:
        return sum(episode.on_device for episode in self.episodes)

    @property
    def listened_count(self) -> int:
        return sum(episode.listened for episode in self.episodes)


@dataclass(frozen=True, slots=True)
class ListeningRecord:
    """Durable listening and automatic-clear state independent of membership."""

    subscription_id: str
    episode_id: str
    guid: str = ""
    enclosure_url: str = ""
    title: str = ""
    listened_override: bool | None = None
    observed_play_count: int = 0
    last_played: int = 0
    published_at: int = 0
    episode_number: int | None = None
    automatically_cleared: bool = False

    def __post_init__(self) -> None:
        if not self.subscription_id.strip() or not self.episode_id.strip():
            raise ValueError("Listening records require subscription and episode IDs")
        if self.observed_play_count < 0 or self.last_played < 0:
            raise ValueError("Listening history values must not be negative")
        if type(self.published_at) is not int or self.published_at < 0:
            raise ValueError("Podcast publication time must be a non-negative integer")
        if self.episode_number is not None and (
            type(self.episode_number) is not int or self.episode_number < 0
        ):
            raise ValueError(
                "Podcast episode number must be a non-negative integer or null"
            )
        if type(self.automatically_cleared) is not bool:
            raise ValueError("Podcast automatic-clear state must be true or false")

    @property
    def listened(self) -> bool:
        if self.listened_override is not None:
            return self.listened_override
        return self.observed_play_count > 0 or self.last_played > 0


@dataclass(frozen=True, slots=True)
class PodcastSnapshot:
    """Complete replacement snapshot published by the Podcast Controller."""

    subscriptions: tuple[PodcastSubscription, ...] = ()
    history: tuple[ListeningRecord, ...] = ()
    issues: tuple[PodcastIssue, ...] = ()
    writable: bool = False

    def __post_init__(self) -> None:
        subscription_ids = tuple(item.subscription_id for item in self.subscriptions)
        if len(subscription_ids) != len(set(subscription_ids)):
            raise ValueError("Podcast Subscription IDs must be unique")
        history_ids = tuple(
            (item.subscription_id, item.episode_id) for item in self.history
        )
        if len(history_ids) != len(set(history_ids)):
            raise ValueError("Podcast listening-history identities must be unique")

    def subscription(self, subscription_id: str) -> PodcastSubscription | None:
        return next(
            (
                subscription
                for subscription in self.subscriptions
                if subscription.subscription_id == subscription_id
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class PodcastSearchResult:
    """Textual directory discovery metadata, excluding promotional image assets."""

    title: str
    author: str
    feed_url: str
    category: str = ""
    episode_count: int = 0


@dataclass(frozen=True, slots=True)
class PodcastArtworkRequest:
    """Ask for one remote Podcast cover near a display-size target."""

    source_url: str
    target_px: int

    def __post_init__(self) -> None:
        if not self.source_url.strip():
            raise ValueError("A Podcast Artwork Request requires a source URL")
        if self.target_px <= 0:
            raise ValueError("A Podcast Artwork Request requires a positive target")


@dataclass(frozen=True, slots=True)
class PodcastArtworkImage:
    """Owned square RGB888 pixels decoded from one remote Podcast cover."""

    cache_key: str
    source_url: str
    width: int
    height: int
    rgb888: bytes

    def __post_init__(self) -> None:
        if not self.cache_key or not self.source_url.strip():
            raise ValueError("Podcast Artwork requires a cache key and source URL")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Podcast Artwork dimensions must be positive")
        expected = self.width * self.height * 3
        if len(self.rgb888) != expected:
            raise ValueError(
                f"Podcast Artwork has {len(self.rgb888)} RGB bytes; expected {expected}"
            )

    @property
    def byte_count(self) -> int:
        return len(self.rgb888)
