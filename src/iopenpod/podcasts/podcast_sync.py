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
from typing import TYPE_CHECKING, Any

from .models import (
    STATUS_DOWNLOADED,
    STATUS_DOWNLOADING,
    STATUS_NOT_DOWNLOADED,
    STATUS_ON_IPOD,
    PodcastEpisode,
    PodcastFeed,
)

if TYPE_CHECKING:
    from iopenpod.sync.contracts import SyncItem, SyncPlan
    from iopenpod.sync.pc_library import PCTrack

log = logging.getLogger(__name__)


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _track_play_count(track: dict | None) -> int:
    if not track:
        return 0
    return max(
        _coerce_int(track.get("play_count_1")),
        _coerce_int(track.get("recent_playcount")),
    )


def _track_recent_play_count(track: dict | None) -> int:
    if not track:
        return 0
    return _coerce_int(track.get("recent_playcount"))


def _track_last_played(track: dict | None) -> int:
    if not track:
        return 0
    return _coerce_int(track.get("last_played"))


def _episode_play_count(episode: PodcastEpisode) -> int:
    return _coerce_int(getattr(episode, "play_count", 0))


def _episode_listened_override(episode: PodcastEpisode) -> bool | None:
    override = getattr(episode, "listened_override", None)
    if override is None:
        return None
    return bool(override)


def _episode_was_listened(
    episode: PodcastEpisode,
    ipod_track: dict | None = None,
) -> bool:
    override = _episode_listened_override(episode)
    if override is not None:
        return override
    return _episode_play_count(episode) > 0 or _track_play_count(ipod_track) > 0


def _update_episode_playback_from_track(
    episode: PodcastEpisode,
    ipod_track: dict,
) -> bool:
    """Persist playback state observed on the iPod into an episode."""
    changed = False
    if _track_recent_play_count(ipod_track) > 0 and (
        _episode_listened_override(episode) is False
    ):
        episode.listened_override = None
        changed = True

    if _episode_listened_override(episode) is False:
        return changed

    play_count = _track_play_count(ipod_track)
    if play_count > _episode_play_count(episode):
        episode.play_count = play_count
        changed = True

    last_played = _track_last_played(ipod_track)
    if last_played > _coerce_int(getattr(episode, "last_played", 0)):
        episode.last_played = last_played
        changed = True

    return changed


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
                if _update_episode_playback_from_track(ep, matched_track):
                    changed = True
                new_db_track_id = matched_track.get("db_track_id", matched_track.get("db_id", 0))
                if ep.ipod_db_track_id != new_db_track_id or ep.status != STATUS_ON_IPOD:
                    ep.ipod_db_track_id = new_db_track_id
                    ep.status = STATUS_ON_IPOD
                    changed = True
                continue

            # No longer present on iPod: clear stale db link and derive local status.
            if ep.ipod_db_track_id != 0:
                ep.ipod_db_track_id = 0
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
    store: object | None = None,
) -> PCTrack:
    """Convert a podcast episode into a PCTrack for the sync pipeline.

    Works for both downloaded and not-yet-downloaded episodes.  For
    episodes without a local file, RSS metadata is used and the file
    will be downloaded during sync execution.

    The returned PCTrack is fully compatible with SyncExecutor's
    ``_pc_track_to_info()`` — which detects ``is_podcast=True`` and sets
    media_type=PODCAST, podcast_flag, skip_when_shuffling, etc.

    Args:
        episode: Episode (may or may not have a downloaded_path).
        feed: Parent feed (for show-level metadata).
        store: Optional SubscriptionStore (for predicting download path).

    Returns:
        A PCTrack ready for use in a SyncItem.
    """
    from iopenpod.sync.pc_library import PCTrack

    path = episode.downloaded_path or ""
    has_file = bool(path and os.path.exists(path))

    # If not downloaded, predict the download path from the audio URL
    if not has_file and episode.audio_url:
        if store is not None:
            from iopenpod.podcasts.subscription_store import SubscriptionStore
            if isinstance(store, SubscriptionStore):
                dest_dir = store.feed_dir(feed)
                from .downloader import _safe_filename
                path = os.path.join(dest_dir, _safe_filename(episode))
                if os.path.exists(path):
                    has_file = True
                    episode.downloaded_path = path
                    if episode.status != STATUS_ON_IPOD:
                        episode.status = STATUS_DOWNLOADED

    # Derive extension from path or audio URL
    if path:
        ext = Path(path).suffix.lower()
    elif episode.audio_url:
        url_path = episode.audio_url.split("?")[0]
        ext = Path(url_path).suffix.lower()
        if ext not in (".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus",
                       ".flac", ".wav", ".wma"):
            ext = ".mp3"  # safe default
    else:
        ext = ".mp3"

    # Read real audio metadata from the downloaded file
    bitrate: int | None = None
    sample_rate: int | None = 44100
    duration_ms = episode.duration_seconds * 1000
    vbr = False

    if has_file:
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

    if has_file:
        file_size = Path(path).stat().st_size
    else:
        file_size = episode.size_bytes

    art_hash: str | None = None
    if has_file:
        try:
            from iopenpod.artworkdb_writer import art_extractor

            art_bytes = art_extractor.extract_art_with_folder(path)
            if art_bytes:
                art_hash = art_extractor.art_hash(art_bytes)
        except Exception as exc:
            log.debug("Could not read artwork hash for %s: %s", path, exc)

    # iPod-native formats
    native = {".mp3", ".m4a", ".m4b", ".aac", ".wav", ".aif", ".aiff"}

    # Extract chapter markers from the downloaded file
    chapters = None
    if has_file:
        try:
            from .downloader import extract_chapters
            chapters = extract_chapters(path)
        except Exception as exc:
            log.debug("Could not extract chapters from %s: %s", path, exc)

    source = Path(path) if path else Path("pending_download" + ext)

    return PCTrack(
        path=path,
        relative_path=source.name,
        filename=source.name,
        extension=ext,
        mtime=source.stat().st_mtime if has_file else 0.0,
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
        art_hash=art_hash,
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
    store: object | None = None,
) -> SyncPlan:
    """Build a SyncPlan for podcast episodes to add to iPod.

    Filters out episodes already on iPod (matched by enclosure URL or
    title+album), and creates ADD_TO_IPOD SyncItems for the rest.

    Works for both downloaded and not-yet-downloaded episodes.  For
    pending episodes, the actual download happens during sync execution
    (see ``SyncExecutor._download_podcast_episodes``).

    Args:
        episodes: List of (episode, feed) tuples.
        ipod_tracks: Parsed track dicts from iTunesDBCache.get_tracks().
        store: Optional SubscriptionStore (for predicting download paths).

    Returns:
        A SyncPlan ready for the SyncReview widget.
    """
    from iopenpod.sync.contracts import StorageSummary, SyncAction, SyncItem, SyncPlan

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

        pc_track = episode_to_pc_track(episode, feed, store)
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


# ── Age threshold helpers ─────────────────────────────────────────────────────

_AGE_THRESHOLDS: dict[str, int] = {
    "immediate": 0,
    "1_day": 86400,
    "3_days": 86400 * 3,
    "1_week": 86400 * 7,
    "2_weeks": 86400 * 14,
    "1_month": 86400 * 30,
    "2_months": 86400 * 60,
    "3_months": 86400 * 90,
}


def _should_clear_episode(
    ipod_track: dict,
    feed: PodcastFeed,
    now: float,
) -> bool:
    """Decide whether an on-iPod episode should be cleared from its slot.

    Returns True if the episode matches any of the feed's clear criteria.
    """
    # Clear when listened: play_count > 0
    if feed.clear_when_listened:
        if _track_play_count(ipod_track) > 0:
            return True

    # Clear when older than threshold (by date added to iPod)
    max_age = _AGE_THRESHOLDS.get(feed.clear_older_than)
    if max_age is not None:
        date_added = ipod_track.get("date_added", 0)
        if date_added and (now - date_added) > max_age:
            return True

    return False


def _pick_candidates(
    feed: PodcastFeed,
    on_ipod_guids: set[str],
    count: int,
    *,
    restart_when_no_newer: bool = True,
) -> list[PodcastEpisode]:
    """Pick episodes to fill empty slots based on fill_mode.

    Args:
        feed: The feed with a full episode catalog (after RSS refresh).
        on_ipod_guids: GUIDs of episodes currently used as the on-iPod
            position when choosing the next episode.
        count: Number of slots to fill.
        restart_when_no_newer: In ``next`` mode, fall back to the oldest
            available episode when nothing newer exists. Replacement clears
            disable this so older episodes are not treated as replacements.

    Returns:
        List of episodes to add, up to *count*.
    """
    if count <= 0:
        return []

    # Consider any episode not already on iPod (download happens at sync time)
    available = [
        ep for ep in feed.episodes
        if ep.status != STATUS_ON_IPOD
        and ep.guid not in on_ipod_guids
        and not (
            feed.clear_when_listened
            and _episode_was_listened(ep)
        )
        and ep.audio_url  # must have a download URL
    ]

    if not available:
        return []

    if feed.fill_mode == "next":
        # "next" mode: pick the next unheard episodes after the latest
        # one on the iPod.  Sort by pub_date ascending, then take from
        # the episode after the newest on-iPod one.
        available.sort(key=lambda e: e.pub_date)

        # Find the pub_date of the newest episode currently on iPod
        on_ipod_eps = [
            ep for ep in feed.episodes
            if ep.guid in on_ipod_guids
        ]
        if on_ipod_eps:
            latest_on_ipod = max(ep.pub_date for ep in on_ipod_eps)
            # Take episodes published after the newest on-iPod episode
            after = [ep for ep in available if ep.pub_date > latest_on_ipod]
            if after:
                return after[:count]
            if not restart_when_no_newer:
                return []

        # No on-iPod episodes or none newer: start from the oldest available
        return available[:count]

    # Default: "newest" — most recently published first
    available.sort(key=lambda e: e.pub_date, reverse=True)
    return available[:count]


def _plan_newest_mode(
    feed: PodcastFeed,
    on_ipod: list[tuple[PodcastEpisode, dict]],
    store: object | None,
) -> tuple[list[SyncItem], list[SyncItem]]:
    """Plan add/remove actions for ``fill_mode="newest"`` using set-diff.

    The iPod should hold the top-N newest eligible episodes. Episodes that
    are already on the iPod *and* still in the top-N stay put — they
    are not torn down and re-added. Only episodes that have actually
    fallen out of the top-N (because newer ones were published, because
    the user reduced the slot count, or because ``clear_when_listened``
    skipped them) get removed; the gap is filled with the corresponding
    newest-not-yet-on-iPod episodes.

    ``clear_older_than`` is intentionally inert in this mode: the set-diff
    handles "rotate when a newer episode is available" automatically,
    which is what users reaching for ``immediate`` actually want. Per-feed
    age-based forcing is a ``next`` mode concept.
    """
    from iopenpod.sync.contracts import SyncAction, SyncItem

    eligible = sorted(
        (ep for ep in feed.episodes if ep.audio_url),
        key=lambda e: e.pub_date,
        reverse=True,
    )

    on_ipod_track_by_guid = {ep.guid: track for ep, track in on_ipod}

    wanted: list[PodcastEpisode] = []
    seen_guids: set[str] = set()
    for ep in eligible:
        if len(wanted) >= feed.episode_slots:
            break
        if ep.guid in seen_guids:
            continue
        seen_guids.add(ep.guid)
        if feed.clear_when_listened:
            track = on_ipod_track_by_guid.get(ep.guid)
            if _episode_was_listened(ep, track):
                continue
        wanted.append(ep)

    wanted_guids = {ep.guid for ep in wanted}
    on_ipod_guids = {ep.guid for ep, _ in on_ipod}

    to_remove_eps = [(ep, t) for ep, t in on_ipod if ep.guid not in wanted_guids]
    to_add_eps = [ep for ep in wanted if ep.guid not in on_ipod_guids]

    if feed.clear_method == "replace":
        paired = min(len(to_remove_eps), len(to_add_eps))
        free_slots = max(0, feed.episode_slots - len(on_ipod))
        extra_adds = min(len(to_add_eps) - paired, free_slots)
        # If on-iPod already exceeds the slot count (e.g. the user reduced
        # episode_slots), force removes until we fit. Without this the
        # "replace only with a partner" rule would let the iPod stay
        # permanently over budget.
        final_count_after_pairing = len(on_ipod) + extra_adds
        overflow = max(0, final_count_after_pairing - feed.episode_slots)
        extra_removes = min(len(to_remove_eps) - paired, overflow)

        remove_list = to_remove_eps[:paired + extra_removes]
        add_list = to_add_eps[:paired + extra_adds]
        removed_suffix = " (replaced)"
    else:
        remove_list = to_remove_eps
        add_list = to_add_eps
        removed_suffix = " (cleared)"

    feed_removes: list[SyncItem] = []
    feed_adds: list[SyncItem] = []
    for ep, track in remove_list:
        feed_removes.append(SyncItem(
            action=SyncAction.REMOVE_FROM_IPOD,
            db_track_id=ep.ipod_db_track_id,
            ipod_track=track,
            description=(
                f"\U0001f399 {feed.title} \u2014 {ep.title}{removed_suffix}"
            ),
        ))
    for ep in add_list:
        pc_track = episode_to_pc_track(ep, feed, store)
        feed_adds.append(SyncItem(
            action=SyncAction.ADD_TO_IPOD,
            pc_track=pc_track,
            description=(
                f"\U0001f399 {feed.title} \u2014 {ep.title}"
            ),
        ))

    return feed_removes, feed_adds


def _plan_next_mode(
    feed: PodcastFeed,
    on_ipod: list[tuple[PodcastEpisode, dict]],
    now: float,
    store: object | None,
) -> tuple[list[SyncItem], list[SyncItem]]:
    """Plan add/remove actions for ``fill_mode="next"``.

    Clears episodes that match ``clear_when_listened`` /
    ``clear_older_than`` and fills the freed slots with the next unheard
    episode after the latest one currently on the iPod.
    """
    from iopenpod.sync.contracts import SyncAction, SyncItem

    # ── Clear phase: identify episodes to remove ──────────────────
    to_clear: list[tuple[PodcastEpisode, dict]] = []
    staying: list[tuple[PodcastEpisode, dict]] = []
    for ep, track in on_ipod:
        if _should_clear_episode(track, feed, now):
            to_clear.append((ep, track))
        else:
            staying.append((ep, track))

    staying_guids = {ep.guid for ep, _ in staying}
    # In replace mode, "next" should be measured from the current iPod
    # position, including episodes marked for clearing. Otherwise an
    # older unplayed episode can be mistaken for a replacement.
    current_on_ipod_guids = {ep.guid for ep, _ in on_ipod}

    # ── Fill phase: pick episodes for empty slots ─────────────────
    slots_after_clear = len(staying)
    slots_to_fill = max(0, feed.episode_slots - slots_after_clear)

    # In "replace" mode we also need candidates to swap with cleared
    # episodes, even when slots are full (no empty slots).
    candidate_count = slots_to_fill
    if feed.clear_method == "replace" and len(to_clear) > candidate_count:
        candidate_count = len(to_clear)
    candidates = _pick_candidates(
        feed,
        current_on_ipod_guids if feed.clear_method == "replace" else staying_guids,
        candidate_count,
        restart_when_no_newer=feed.clear_method != "replace",
    )

    # ── Apply clear method ────────────────────────────────────────
    # "remove"  → remove cleared episodes unconditionally
    # "replace" → only remove if we have a replacement to add
    feed_removes: list[SyncItem] = []
    feed_adds: list[SyncItem] = []

    if feed.clear_method == "replace":
        paired = min(len(to_clear), len(candidates))
        for i in range(paired):
            ep, track = to_clear[i]
            feed_removes.append(SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                db_track_id=ep.ipod_db_track_id,
                ipod_track=track,
                description=(
                    f"\U0001f399 {feed.title} \u2014 {ep.title} (replaced)"
                ),
            ))
        on_ipod_after = len(on_ipod) - paired
        extra_room = max(0, feed.episode_slots - on_ipod_after)
        add_count = paired + extra_room
        for candidate in candidates[:add_count]:
            pc_track = episode_to_pc_track(candidate, feed, store)
            feed_adds.append(SyncItem(
                action=SyncAction.ADD_TO_IPOD,
                pc_track=pc_track,
                description=(
                    f"\U0001f399 {feed.title} \u2014 {candidate.title}"
                ),
            ))
    else:
        for ep, track in to_clear:
            feed_removes.append(SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                db_track_id=ep.ipod_db_track_id,
                ipod_track=track,
                description=(
                    f"\U0001f399 {feed.title} \u2014 {ep.title} (cleared)"
                ),
            ))
        total_after = len(staying)
        fill_count = max(0, feed.episode_slots - total_after)
        for candidate in candidates[:fill_count]:
            pc_track = episode_to_pc_track(candidate, feed, store)
            feed_adds.append(SyncItem(
                action=SyncAction.ADD_TO_IPOD,
                pc_track=pc_track,
                description=(
                    f"\U0001f399 {feed.title} \u2014 {candidate.title}"
                ),
            ))

    return feed_removes, feed_adds


def build_podcast_managed_plan(
    feeds: list[PodcastFeed],
    ipod_tracks: list[dict],
    store: object | None = None,
) -> SyncPlan:
    """Build a SyncPlan that applies per-feed podcast settings.

    Dispatches per feed on ``fill_mode``:

    - ``"newest"`` uses set-diff between the top-N newest eligible
      episodes and what's currently on the iPod (see
      ``_plan_newest_mode``). Already-on-iPod episodes that are still in
      the top-N stay put rather than being rotated out for older
      back-catalog episodes.
    - ``"next"`` uses the slot-based clear/fill pipeline (see
      ``_plan_next_mode``).

    After per-feed planning, a final overflow trim caps the on-iPod count
    at ``feed.episode_slots``. In practice this only fires for ``next``
    mode under a freshly reduced slot count; ``newest`` mode handles
    overflow internally.

    Args:
        feeds: All subscribed feeds (with full episode catalogs after
               RSS refresh).
        ipod_tracks: Parsed track dicts from iTunesDBCache.
        store: Optional SubscriptionStore for saving state changes.

    Returns:
        A SyncPlan with adds and removes ready for the SyncReview.
    """
    from iopenpod.sync.contracts import (
        StorageSummary,
        SyncAction,
        SyncItem,
        SyncPlan,
    )

    now = time.time()
    to_add: list[SyncItem] = []
    to_remove: list[SyncItem] = []
    bytes_to_add = 0
    bytes_to_remove = 0

    # Index all podcast tracks on iPod by enclosure URL and title+album
    by_enclosure: dict[str, dict] = {}
    by_title_album: dict[tuple[str, str], dict] = {}
    for t in ipod_tracks:
        if not (t.get("media_type", 0) & 0x04):
            continue
        enc = t.get("Podcast Enclosure URL", "")
        if enc:
            by_enclosure[enc] = t
        title = t.get("Title", "")
        album = t.get("Album", "")
        if title and album:
            by_title_album[(title.lower(), album.lower())] = t

    for feed in feeds:
        # Find this feed's episodes currently on the iPod
        on_ipod: list[tuple[PodcastEpisode, dict]] = []
        for ep in feed.episodes:
            if ep.status != STATUS_ON_IPOD or not ep.ipod_db_track_id:
                continue
            # Look up the iPod track dict for metadata (play count, date_added)
            ipod_track = None
            if ep.audio_url:
                ipod_track = by_enclosure.get(ep.audio_url)
            if not ipod_track and ep.title and feed.title:
                ipod_track = by_title_album.get(
                    (ep.title.lower(), feed.title.lower())
                )
            if ipod_track:
                on_ipod.append((ep, ipod_track))

        if feed.fill_mode == "newest":
            feed_removes, feed_adds = _plan_newest_mode(feed, on_ipod, store)
        else:
            feed_removes, feed_adds = _plan_next_mode(feed, on_ipod, now, store)

        # Cap total on-iPod count to episode_slots even if nothing was
        # cleared (e.g. user reduced slot count in "next" mode after an
        # initial sync). "newest" mode handles overflow internally, so
        # this trim is normally a no-op for it. Remove oldest-added
        # episodes among those staying to bring the feed back in budget.
        removed_db_ids = {item.db_track_id for item in feed_removes}
        staying = [
            (ep, t) for ep, t in on_ipod
            if ep.ipod_db_track_id not in removed_db_ids
        ]
        total_after = len(staying) + len(feed_adds)
        if total_after > feed.episode_slots:
            overflow = total_after - feed.episode_slots
            staying.sort(key=lambda x: x[1].get("date_added", 0))
            for ep, track in staying[:overflow]:
                feed_removes.append(SyncItem(
                    action=SyncAction.REMOVE_FROM_IPOD,
                    db_track_id=ep.ipod_db_track_id,
                    ipod_track=track,
                    description=(
                        f"\U0001f399 {feed.title} \u2014 {ep.title} "
                        f"(over slot limit)"
                    ),
                ))

        to_remove.extend(feed_removes)
        to_add.extend(feed_adds)
        bytes_to_remove += sum(
            item.ipod_track.get("size", 0)
            for item in feed_removes if item.ipod_track
        )
        bytes_to_add += sum(
            item.pc_track.size for item in feed_adds if item.pc_track
        )

        if feed_removes or feed_adds:
            log.info(
                "Podcast %s: %d to remove, %d to add (slots=%d, on_ipod=%d)",
                feed.title, len(feed_removes), len(feed_adds),
                feed.episode_slots, len(on_ipod),
            )

    return SyncPlan(
        to_add=to_add,
        to_remove=to_remove,
        storage=StorageSummary(
            bytes_to_add=bytes_to_add,
            bytes_to_remove=bytes_to_remove,
        ),
    )


def match_ipod_tracks(
    feed: PodcastFeed,
    ipod_tracks: list[dict],
) -> bool:
    """Match existing iPod tracks to feed episodes.

    Scans the iPod's parsed track list for podcast tracks matching this
    feed (by enclosure URL or title+album).  Updates episode.ipod_db_track_id
    and episode.status for matched episodes.

    Args:
        feed: A PodcastFeed with episodes.
        ipod_tracks: Parsed track dicts from iTunesDBCache.get_tracks().

    Returns:
        True if any episode state changed, otherwise False.
    """
    matcher = PodcastTrackMatcher(ipod_tracks)
    return matcher.match_feed(feed)
