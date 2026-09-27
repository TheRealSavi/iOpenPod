"""Typed Podcast fixtures shared by catalog, controller, and Sync tests."""

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iPodDB.library import LibrarySnapshot, MediaType, Track, TrackMetadata
from storage import FileFingerprint


def active_ipod() -> ActiveIPod:
    profile = next(
        profile
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        if profile.model_number == "MB565"
    )
    candidate = DeviceCandidate(
        DeviceCandidateId("podcast-test"),
        "Test iPod",
        "USB iPod",
        "usb",
        IdentificationStatus.EXACT,
        DeviceReadiness.READY,
        profile,
        80_000_000_000,
        40_000_000_000,
    )
    return ActiveIPod(
        candidate,
        profile,
        LibrarySnapshot(),
        "iTunesDB",
        FileFingerprint(1, 0, 0, 0, "0" * 64),
    )


def device_episode(
    *,
    play_count: int = 0,
    feed_url: str = "HTTPS://EXAMPLE.test:443/feed.xml#fragment",
) -> Track:
    return Track(
        41,
        "The First Episode",
        "Example Network",
        "A Good Podcast",
        3_660_000,
        size_bytes=42_000_000,
        artwork_id=77,
        play_count=play_count,
        media_types=(MediaType.PODCAST,),
        episode="guid-1",
        episode_number=7,
        metadata=TrackMetadata(
            podcast=True,
            podcast_rss_url=feed_url,
            podcast_enclosure_url="https://cdn.example.test/episode-1.mp3",
            release_date=1_700_000_000,
            last_played=1_710_000_000 if play_count else 0,
        ),
    )
