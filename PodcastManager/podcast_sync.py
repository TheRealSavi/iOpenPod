"""Bridge between downloaded podcast episodes and the iPod sync pipeline.

Converts PodcastEpisode + PodcastFeed models into PCTrack objects that
flow through the standard sync pipeline (SyncPlan → SyncReview →
SyncExecutor → write_itunesdb).  The SyncExecutor's _pc_track_to_info()
detects podcasts via ``is_podcast=True`` and sets the correct media_type,
podcast_flag, etc.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .models import (
    PodcastEpisode,
    PodcastFeed,
    STATUS_DOWNLOADED,
    STATUS_DOWNLOADING,
    STATUS_NOT_DOWNLOADED,
    STATUS_ON_IPOD,
)

if TYPE_CHECKING:
    from SyncEngine.pc_library import PCTrack
    from SyncEngine.fingerprint_diff_engine import SyncPlan

log = logging.getLogger(__name__)


class PodcastTrackMatcher:
    """Fast matcher for resolving podcast episodes against iPod tracks.

    The matcher pre-indexes iPod podcast tracks once, then can reconcile
    many feeds without rebuilding lookup maps for each feed.
    """

    def __init__(self, ipod_tracks: list[dict]):
        self._by_enclosure: dict[str, dict] = {}
        self._by_title_album: dict[tuple[str, str], dict] = {}

        for track in ipod_tracks:
            media_type = track.get("media_type", 0)
            if not (media_type & 0x04):
                continue

            enc_url = track.get("Podcast Enclosure URL", "")
            if enc_url:
                self._by_enclosure[enc_url] = track

            title = track.get("Title", "")
            album = track.get("Album", "")
            if title and album:
                self._by_title_album[(title.lower(), album.lower())] = track

    def match_feed(self, feed: PodcastFeed) -> bool:
        """Reconcile one feed against indexed iPod tracks.

        Returns:
            True if any episode state changed, else False.
        """
        changed = False

        for ep in feed.episodes:
            matched_track = None
            if ep.audio_url:
                matched_track = self._by_enclosure.get(ep.audio_url)
            if not matched_track and ep.title and feed.title:
                matched_track = self._by_title_album.get(
                    (ep.title.lower(), feed.title.lower())
                )

            if matched_track:
                new_db_id = matched_track.get("db_id", 0)
                if ep.ipod_db_id != new_db_id or ep.status != STATUS_ON_IPOD:
                    ep.ipod_db_id = new_db_id
                    ep.status = STATUS_ON_IPOD
                    changed = True
                continue

            # No longer present on iPod: clear stale db link and derive local status.
            if ep.ipod_db_id != 0:
                ep.ipod_db_id = 0
                changed = True

            # Keep transient download state if a transfer is currently running.
            if ep.status == STATUS_DOWNLOADING:
                continue

            has_local_file = bool(ep.downloaded_path and os.path.exists(ep.downloaded_path))
            if not has_local_file and ep.downloaded_path:
                ep.downloaded_path = ""
                changed = True

            next_status = STATUS_DOWNLOADED if has_local_file else STATUS_NOT_DOWNLOADED
            if ep.status != next_status:
                ep.status = next_status
                changed = True

        return changed


def episode_to_pc_track(
    episode: PodcastEpisode,
    feed: PodcastFeed,
) -> 'PCTrack':
    """Convert a downloaded episode into a PCTrack for the sync pipeline.

    The returned PCTrack is fully compatible with SyncExecutor's
    ``_pc_track_to_info()`` — which detects ``is_podcast=True`` and sets
    media_type=PODCAST, podcast_flag, skip_when_shuffling, etc.

    Args:
        episode: Episode with a valid downloaded_path.
        feed: Parent feed (for show-level metadata).

    Returns:
        A PCTrack ready for use in a SyncItem.
    """
    from SyncEngine.pc_library import PCTrack

    path = episode.downloaded_path
    source = Path(path)
    ext = source.suffix.lower()

    # Read real audio metadata from the downloaded file
    bitrate: Optional[int] = None
    sample_rate: Optional[int] = 44100
    duration_ms = episode.duration_seconds * 1000
    vbr = False

    if path and os.path.exists(path):
        try:
            from mutagen import File as MutagenFile  # type: ignore[import-untyped]
            audio = MutagenFile(path)
            if audio and audio.info:
                if hasattr(audio.info, 'bitrate') and audio.info.bitrate:
                    bitrate = int(audio.info.bitrate / 1000)
                if hasattr(audio.info, 'sample_rate') and audio.info.sample_rate:
                    sample_rate = audio.info.sample_rate
                if hasattr(audio.info, 'length') and audio.info.length:
                    duration_ms = int(audio.info.length * 1000)
                if hasattr(audio.info, 'bitrate_mode'):
                    from mutagen.mp3 import BitrateMode  # type: ignore[import-untyped]
                    vbr = audio.info.bitrate_mode == BitrateMode.VBR
        except Exception as exc:
            log.debug("Could not read audio metadata for %s: %s", path, exc)

    file_size = source.stat().st_size if source.exists() else episode.size_bytes

    # iPod-native formats
    native = {".mp3", ".m4a", ".m4b", ".aac", ".wav", ".aif", ".aiff"}

    # Extract chapter markers from the downloaded file
    chapters = None
    if path and os.path.exists(path):
        try:
            from .downloader import extract_chapters
            chapters = extract_chapters(path)
        except Exception as exc:
            log.debug("Could not extract chapters from %s: %s", path, exc)

    return PCTrack(
        path=path,
        relative_path=source.name,
        filename=source.name,
        extension=ext,
        mtime=source.stat().st_mtime if source.exists() else 0.0,
        size=file_size,
        title=episode.title or "Untitled Episode",
        artist=feed.author or feed.title,
        album=feed.title,
        album_artist=feed.author or None,
        genre=feed.category or "Podcast",
        year=(int(time.strftime("%Y", time.localtime(episode.pub_date)))
              if episode.pub_date else None),
        track_number=episode.episode_number,
        track_total=None,
        disc_number=episode.season_number,
        disc_total=None,
        duration_ms=duration_ms,
        bitrate=bitrate,
        sample_rate=sample_rate,
        rating=None,
        vbr=vbr,
        date_released=int(episode.pub_date) if episode.pub_date else 0,
        description=episode.description[:255] if episode.description else None,
        episode_number=episode.episode_number,
        season_number=episode.season_number,
        is_podcast=True,
        show_name=feed.title or None,
        category=feed.category or None,
        podcast_url=feed.feed_url or None,
        podcast_enclosure_url=episode.audio_url or None,
        needs_transcoding=ext not in native,
        chapters=chapters,
    )


def build_podcast_sync_plan(
    episodes: list[tuple[PodcastEpisode, PodcastFeed]],
    ipod_tracks: list[dict],
) -> 'SyncPlan':
    """Build a SyncPlan for podcast episodes to add to iPod.

    Filters out episodes already on iPod (matched by enclosure URL or
    title+album), and creates ADD_TO_IPOD SyncItems for the rest.

    Args:
        episodes: List of (episode, feed) tuples for downloaded episodes.
        ipod_tracks: Parsed track dicts from iTunesDBCache.get_tracks().

    Returns:
        A SyncPlan ready for the SyncReview widget.
    """
    from SyncEngine.fingerprint_diff_engine import SyncPlan, SyncItem, SyncAction, StorageSummary

    # Build lookup of existing podcast tracks on iPod
    by_enclosure: dict[str, dict] = {}
    by_title_album: dict[tuple[str, str], dict] = {}
    for t in ipod_tracks:
        media_type = t.get("media_type", 0)
        if not (media_type & 0x04):
            continue
        enc_url = t.get("Podcast Enclosure URL", "")
        if enc_url:
            by_enclosure[enc_url] = t
        title = t.get("Title", "")
        album = t.get("Album", "")
        if title and album:
            by_title_album[(title.lower(), album.lower())] = t

    to_add: list[SyncItem] = []
    bytes_to_add = 0

    for episode, feed in episodes:
        # Skip if already on iPod
        already_on_ipod = False
        if episode.audio_url and episode.audio_url in by_enclosure:
            already_on_ipod = True
        elif episode.title and feed.title:
            key = (episode.title.lower(), feed.title.lower())
            if key in by_title_album:
                already_on_ipod = True

        if already_on_ipod:
            continue

        pc_track = episode_to_pc_track(episode, feed)
        to_add.append(SyncItem(
            action=SyncAction.ADD_TO_IPOD,
            pc_track=pc_track,
            description=f"🎙 {feed.title} — {episode.title}",
        ))
        bytes_to_add += pc_track.size

    return SyncPlan(
        to_add=to_add,
        storage=StorageSummary(bytes_to_add=bytes_to_add),
    )


def needs_transcode(episode: PodcastEpisode) -> bool:
    """Check if an episode's audio format needs transcoding for iPod."""
    if not episode.downloaded_path:
        return False
    ext = Path(episode.downloaded_path).suffix.lower()
    native = {".mp3", ".m4a", ".m4b", ".aac", ".wav", ".aif", ".aiff"}
    return ext not in native


def match_ipod_tracks(
    feed: PodcastFeed,
    ipod_tracks: list[dict],
) -> bool:
    """Match existing iPod tracks to feed episodes.

    Scans the iPod's parsed track list for podcast tracks matching this
    feed (by enclosure URL or title+album).  Updates episode.ipod_db_id
    and episode.status for matched episodes.

    Args:
        feed: A PodcastFeed with episodes.
        ipod_tracks: Parsed track dicts from iTunesDBCache.get_tracks().

    Returns:
        True if any episode state changed, otherwise False.
    """
    matcher = PodcastTrackMatcher(ipod_tracks)
    return matcher.match_feed(feed)
