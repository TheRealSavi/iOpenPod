"""Pure Podcast selection and retention, shared by every Sync entry point."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from iOpenPod.app.podcasts.identity import normalize_feed_url
from iOpenPod.app.podcasts.models import (
    PodcastClearMethod,
    PodcastEpisode,
    PodcastFillMode,
    PodcastSnapshot,
    PodcastSubscription,
)
from iPodDB.library import MediaKind, WriteIssue

if TYPE_CHECKING:
    from iOpenPod.app.podcasts.models import ListeningRecord
    from iPodDB.library import LibrarySnapshot, Track


@dataclass(frozen=True, slots=True)
class PodcastSyncRequest:
    """Captured catalog and explicit scope for a single Sync operation."""

    snapshot: PodcastSnapshot
    subscription_ids: tuple[str, ...] | None = None
    additions: tuple[tuple[str, str], ...] = ()
    removals: tuple[tuple[str, str], ...] = ()
    automatic: bool = True


@dataclass(frozen=True, slots=True)
class PodcastEpisodeAddition:
    subscription: PodcastSubscription
    episode: PodcastEpisode
    # The executor removes this Track only after this exact Episode prepares.
    # Unconditional clears and explicit removals belong to the plan's removals.
    replaces_track_id: int | None = None


@dataclass(frozen=True, slots=True)
class PodcastSyncPlan:
    additions: tuple[PodcastEpisodeAddition, ...] = ()
    removals: tuple[int, ...] = ()
    issues: tuple[WriteIssue, ...] = ()
    # Intent only: persist a cleared identity after its actual removal commits.
    automatic_removals: tuple[tuple[str, str], ...] = ()


def plan_podcast_sync(
    request: PodcastSyncRequest,
    library: LibrarySnapshot,
    *,
    now: int | None = None,
) -> PodcastSyncPlan:
    """Select Episodes without downloading, mutating devices, or saving state.

    Callers refresh the scoped feeds and reconcile the catalog against this
    Library before planning. Failed feed refreshes must be excluded from managed
    planning; their stale catalog cannot authorize retention removals.
    """
    if not request.snapshot.writable:
        return PodcastSyncPlan(
            issues=(_issue("read_only", "Podcast state is read-only."),)
        )
    timestamp = int(time.time()) if now is None else now
    if timestamp < 0:
        raise ValueError("Podcast Sync time must not be negative")
    subscriptions = {
        item.subscription_id: item for item in request.snapshot.subscriptions
    }
    scoped = (
        tuple(subscriptions)
        if request.subscription_ids is None
        else tuple(dict.fromkeys(request.subscription_ids))
    )
    unknown = tuple(identity for identity in scoped if identity not in subscriptions)
    if unknown:
        return PodcastSyncPlan(
            issues=(
                _issue(
                    "missing_subscription", "A selected Podcast is no longer available."
                ),
            )
        )
    tracks = {track.track_id: track for track in library.tracks}
    additions: list[PodcastEpisodeAddition] = []
    removals: list[int] = []
    issues: list[WriteIssue] = []
    automatic_removals: list[tuple[str, str]] = []
    if request.automatic:
        for identity in scoped:
            managed_subscription = subscriptions[identity]
            current = _current_episodes(managed_subscription, tracks)
            if current is None:
                issues.append(
                    _issue(
                        "stale_membership",
                        f"{managed_subscription.title}: Podcast membership changed; refresh before syncing.",
                    )
                )
                continue
            if _ambiguous_identity(managed_subscription, tracks):
                issues.append(
                    _issue(
                        "ambiguous_identity",
                        f"{managed_subscription.title}: Repeated Podcast identities prevent safe automatic Sync.",
                    )
                )
                continue
            policy_plan = _managed_plan(
                managed_subscription,
                current,
                tracks,
                timestamp,
                tuple(
                    record
                    for record in request.snapshot.history
                    if record.subscription_id == identity
                ),
            )
            additions.extend(policy_plan.additions)
            removals.extend(policy_plan.removals)
            automatic_removals.extend(policy_plan.automatic_removals)
    selected_adds = set(request.additions)
    if selected_adds.intersection(request.removals):
        return PodcastSyncPlan(
            issues=(
                _issue(
                    "conflicting_selection",
                    "An Episode cannot be added and removed in the same Sync.",
                ),
            )
        )
    for adding, selection in ((True, request.additions), (False, request.removals)):
        for subscription_id, episode_id in dict.fromkeys(selection):
            subscription = subscriptions.get(subscription_id)
            episode = (
                next(
                    (
                        item
                        for item in subscription.episodes
                        if item.episode_id == episode_id
                    ),
                    None,
                )
                if subscription is not None and subscription_id in scoped
                else None
            )
            if subscription is None or episode is None:
                issues.append(
                    _issue(
                        "missing_episode",
                        "A selected Podcast Episode is no longer available.",
                    )
                )
                continue
            if adding:
                if episode.on_device:
                    continue
                if _ambiguous_identity(subscription, tracks):
                    issues.append(
                        _issue(
                            "ambiguous_identity",
                            f"{subscription.title}: Repeated Podcast identities prevent safely adding this Episode.",
                        )
                    )
                    continue
                if not normalize_feed_url(episode.enclosure_url):
                    issues.append(
                        _issue(
                            "missing_media",
                            f"{episode.title}: This Episode has no usable HTTP(S) media URL.",
                        )
                    )
                    continue
                additions.append(PodcastEpisodeAddition(subscription, episode))
            elif episode.track_id is not None:
                track = tracks.get(episode.track_id)
                if track is None or not _is_podcast(track):
                    issues.append(
                        _issue(
                            "stale_membership",
                            f"{episode.title}: The iPod Episode changed; refresh before removing it.",
                        )
                    )
                    continue
                removals.append(track.track_id)
    unique_additions = {
        (item.subscription.subscription_id, item.episode.episode_id): item
        for item in additions
    }
    return PodcastSyncPlan(
        tuple(unique_additions.values()),
        tuple(dict.fromkeys(removals)),
        tuple(issues),
        tuple(dict.fromkeys(automatic_removals)),
    )


def _current_episodes(
    subscription: PodcastSubscription,
    tracks: dict[int, Track],
) -> tuple[PodcastEpisode, ...] | None:
    current = tuple(item for item in subscription.episodes if item.on_device)
    identities = tuple(item.track_id for item in current)
    if len(identities) != len(set(identities)):
        return None
    for identity in identities:
        track = tracks.get(identity) if identity is not None else None
        if track is None or not _is_podcast(track):
            return None
    return current


def _ambiguous_identity(
    subscription: PodcastSubscription, tracks: dict[int, Track]
) -> bool:
    episode_guids = Counter(
        episode.guid for episode in subscription.episodes if episode.guid
    )
    if any(count > 1 for count in episode_guids.values()):
        return True
    current_ids = {
        episode.track_id
        for episode in subscription.episodes
        if episode.track_id is not None
    }
    feed_url = normalize_feed_url(subscription.feed_url)
    matched = tuple(
        track
        for track in tracks.values()
        if _is_podcast(track)
        and (
            track.track_id in current_ids
            or (
                feed_url
                and normalize_feed_url(track.metadata.podcast_rss_url) == feed_url
            )
            or (
                not track.metadata.podcast_rss_url
                and track.album.casefold().strip()
                == subscription.title.casefold().strip()
            )
        )
    )
    guids = Counter(track.episode for track in matched if track.episode)
    enclosures = Counter(
        normalize_feed_url(track.metadata.podcast_enclosure_url)
        for track in matched
        if normalize_feed_url(track.metadata.podcast_enclosure_url)
    )
    if any(
        not episode.on_device
        and (
            (episode.guid and episode.guid in guids)
            or normalize_feed_url(episode.enclosure_url) in enclosures
        )
        for episode in subscription.episodes
    ):
        return True
    return any(count > 1 for count in (*guids.values(), *enclosures.values()))


def _managed_plan(
    subscription: PodcastSubscription,
    current: tuple[PodcastEpisode, ...],
    tracks: dict[int, Track],
    now: int,
    history: tuple[ListeningRecord, ...],
) -> PodcastSyncPlan:
    settings = subscription.sync_settings
    newest = settings.fill_mode is PodcastFillMode.NEWEST
    replacing = settings.clear_method is PodcastClearMethod.REPLACE
    clearing = sorted(
        (
            episode
            for episode in current
            if (settings.clear_when_listened and episode.listened)
            or _aged(episode, tracks, settings.clear_older_than.seconds, now)
        ),
        key=_publication_order,
    )
    retired_ids = {
        record.episode_id for record in history if record.automatically_cleared
    }
    candidates = sorted(
        (
            episode
            for episode in subscription.episodes
            if not episode.on_device
            and not episode.automatically_cleared
            and episode.episode_id not in retired_ids
            and normalize_feed_url(episode.enclosure_url)
            and not (settings.clear_when_listened and episode.listened)
        ),
        key=_publication_order,
        reverse=newest,
    )
    floor = _candidate_floor(subscription, history, newest=newest)
    if floor is not None:
        candidates = [
            episode
            for episode in candidates
            if (
                _publication_order(episode)[:2] > floor[:2]
                if newest
                else _publication_order(episode) > floor
            )
        ]
    vacancies = max(0, settings.episode_slots - len(current))
    # Manual over-capacity libraries may swap one-for-one, but cannot grow from
    # automatic filling. Remove can drain excess; reducing the target never does.
    replacement_limit = (
        len(clearing)
        if replacing
        else max(0, settings.episode_slots - len(current) + len(clearing)) - vacancies
    )
    pairs = (
        _newest_replacements(clearing, candidates, replacement_limit)
        if newest
        else tuple(zip(clearing[:replacement_limit], candidates, strict=False))
    )
    used = {episode.episode_id for _, episode in pairs}
    additions = [
        PodcastEpisodeAddition(
            subscription,
            episode,
            old.track_id if replacing else None,
        )
        for old, episode in pairs
    ]
    unpaired = [episode for episode in candidates if episode.episode_id not in used]
    additions.extend(
        PodcastEpisodeAddition(subscription, episode)
        for episode in unpaired[:vacancies]
    )
    additions.sort(key=lambda item: _publication_order(item.episode), reverse=newest)
    removed = tuple(old for old, _ in pairs) if replacing else tuple(clearing)
    return PodcastSyncPlan(
        additions=tuple(additions),
        removals=()
        if replacing
        else tuple(
            episode.track_id for episode in removed if episode.track_id is not None
        ),
        automatic_removals=tuple(
            (subscription.subscription_id, episode.episode_id) for episode in removed
        ),
    )


def _candidate_floor(
    subscription: PodcastSubscription,
    history: tuple[ListeningRecord, ...],
    *,
    newest: bool,
) -> tuple[int, int, str] | None:
    current = {episode.episode_id: episode for episode in subscription.episodes}
    positions = [
        _publication_order(episode)
        for episode in subscription.episodes
        if (episode.automatically_cleared if newest else episode.listened)
    ]
    for record in history:
        if not (record.automatically_cleared if newest else record.listened):
            continue
        episode = current.get(record.episode_id)
        if episode is not None:
            positions.append(_publication_order(episode))
        else:
            positions.append(
                (record.published_at, record.episode_number or 0, record.episode_id)
            )
    return max(positions, default=None)


def _newest_replacements(
    clearing: list[PodcastEpisode],
    candidates: list[PodcastEpisode],
    limit: int,
) -> tuple[tuple[PodcastEpisode, PodcastEpisode], ...]:
    """Use newest possible candidates without replacing with an older Episode."""
    if limit <= 0:
        return ()
    # Find how many swaps are possible, then choose that many newest candidates.
    # Pair in ascending order to preserve scarce newer replacements.
    remaining = list(reversed(candidates))
    count = 0
    for old in clearing:
        candidate = next(
            (
                item
                for item in remaining
                if _publication_order(item)[:2] > _publication_order(old)[:2]
            ),
            None,
        )
        if candidate is not None:
            remaining.remove(candidate)
            count += 1
        if count >= limit:
            break
    selected = list(reversed(candidates[:count]))
    pairs: list[tuple[PodcastEpisode, PodcastEpisode]] = []
    for old in clearing:
        candidate = next(
            (
                item
                for item in selected
                if _publication_order(item)[:2] > _publication_order(old)[:2]
            ),
            None,
        )
        if candidate is not None:
            selected.remove(candidate)
            pairs.append((old, candidate))
    return tuple(pairs)


def _date_added(episode: PodcastEpisode, tracks: dict[int, Track]) -> int:
    track = tracks.get(episode.track_id) if episode.track_id is not None else None
    return track.metadata.date_added if track is not None else 0


def _aged(
    episode: PodcastEpisode,
    tracks: dict[int, Track],
    threshold: int | None,
    now: int,
) -> bool:
    if threshold == 0:
        return True
    added = _date_added(episode, tracks)
    return threshold is not None and added > 0 and now - added > threshold


def _publication_order(episode: PodcastEpisode) -> tuple[int, int, str]:
    return episode.published_at, episode.episode_number or 0, episode.episode_id


def _is_podcast(track: Track) -> bool:
    return track.media_kind is MediaKind.PODCAST or track.metadata.podcast


def _issue(code: str, message: str) -> WriteIssue:
    return WriteIssue(f"podcast.{code}", message, subject="podcast")


__all__ = [
    "PodcastEpisodeAddition",
    "PodcastSyncPlan",
    "PodcastSyncRequest",
    "plan_podcast_sync",
]
