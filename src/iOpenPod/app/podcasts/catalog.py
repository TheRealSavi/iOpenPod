"""Pure reconciliation and edit operations for the podcast catalog."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

from iOpenPod.app.podcasts.identity import (
    episode_identity,
    normalize_feed_url,
    subscription_identity,
)
from iOpenPod.app.podcasts.models import (
    ListeningRecord,
    PodcastEpisode,
    PodcastSnapshot,
    PodcastSubscription,
    SubscriptionSource,
)
from iPodDB.library import MediaKind

if TYPE_CHECKING:
    from collections.abc import Iterable

    from iPodDB.library import Track


def reconcile_device_podcasts(
    snapshot: PodcastSnapshot,
    tracks: Iterable[Track],
) -> PodcastSnapshot:
    """Overlay current device membership and retain observed listening history."""

    subscriptions = {
        item.subscription_id: _clear_device_projection(item)
        for item in snapshot.subscriptions
    }
    history = {
        (item.subscription_id, item.episode_id): item for item in snapshot.history
    }
    history_guids = _history_guid_index(history.values())
    device_tracks = tuple(tracks)
    guid_counts = Counter(
        track.episode.strip()
        for track in device_tracks
        if track.episode.strip()
        and (track.media_kind is MediaKind.PODCAST or track.metadata.podcast)
    )

    for track in device_tracks:
        if track.media_kind is not MediaKind.PODCAST and not track.metadata.podcast:
            continue
        title = (
            track.album.strip()
            or track.show.strip()
            or track.artist.strip()
            or "Unknown Podcast"
        )
        author = track.album_artist.strip() or track.artist.strip()
        feed_url = normalize_feed_url(track.metadata.podcast_rss_url)
        derived_subscription_id = subscription_identity(feed_url, title, author)
        episode = _episode_from_track(track)
        subscription = subscriptions.get(derived_subscription_id)
        if subscription is None:
            subscription = _subscription_matching_evidence(
                subscriptions.values(),
                (episode.episode_id,),
                title,
                author,
            )
        if subscription is None:
            subscription = PodcastSubscription(
                derived_subscription_id,
                feed_url,
                title,
                SubscriptionSource.DEVICE,
                author=author,
                artwork_id=track.artwork_id,
            )
        subscription_id = subscription.subscription_id

        retained = {item.episode_id: item for item in subscription.episodes}
        existing = retained.get(episode.episode_id)
        if existing is None and guid_counts[episode.guid] == 1:
            existing = _episode_matching_guid(subscription.episodes, episode.guid)
        observed = _matching_history(
            history,
            history_guids,
            subscription_id,
            episode,
            allow_guid=guid_counts[episode.guid] == 1,
        )
        if existing is None and observed is not None:
            episode = replace(episode, episode_id=observed.episode_id)
        if existing is not None:
            episode = replace(
                existing,
                title=episode.title or existing.title,
                description=episode.description or existing.description,
                guid=episode.guid or existing.guid,
                enclosure_url=episode.enclosure_url or existing.enclosure_url,
                published_at=episode.published_at or existing.published_at,
                duration_seconds=episode.duration_seconds or existing.duration_seconds,
                size_bytes=episode.size_bytes or existing.size_bytes,
                episode_number=episode.episode_number or existing.episode_number,
                season_number=episode.season_number or existing.season_number,
                on_device=True,
                track_id=track.track_id,
            )
        retained[episode.episode_id] = episode

        history_key = (subscription_id, episode.episode_id)
        observed = _matching_history(
            history,
            history_guids,
            subscription_id,
            episode,
            allow_guid=guid_counts[episode.guid] == 1,
        )
        play_count = max(
            track.play_count,
            track.metadata.unscrobbled_play_count,
            int(track.metadata.played),
            observed.observed_play_count if observed is not None else 0,
        )
        last_played = max(
            track.metadata.last_played,
            observed.last_played if observed is not None else 0,
        )
        played = track.metadata.played or play_count > 0 or last_played > 0
        if observed is not None or played:
            history[history_key] = ListeningRecord(
                subscription_id,
                episode.episode_id,
                guid=episode.guid or (observed.guid if observed else ""),
                enclosure_url=episode.enclosure_url
                or (observed.enclosure_url if observed else ""),
                title=episode.title or (observed.title if observed else ""),
                listened_override=(
                    observed.listened_override if observed is not None else None
                ),
                observed_play_count=play_count,
                last_played=last_played,
                published_at=episode.published_at
                or (observed.published_at if observed else 0),
                episode_number=episode.episode_number
                or (observed.episode_number if observed else None),
                automatically_cleared=observed.automatically_cleared
                if observed
                else False,
            )
        subscriptions[subscription_id] = replace(
            subscription,
            title=subscription.title or title,
            author=subscription.author or author,
            artwork_id=subscription.artwork_id or track.artwork_id,
            episodes=_ordered_episodes(retained.values()),
        )

    subscriptions = {
        key: replace(
            subscription,
            episodes=tuple(
                _with_history(
                    episode,
                    history.get((subscription.subscription_id, episode.episode_id)),
                )
                for episode in subscription.episodes
            ),
        )
        for key, subscription in subscriptions.items()
    }
    return replace(
        snapshot,
        subscriptions=_ordered_subscriptions(subscriptions.values()),
        history=_ordered_history(history.values()),
    )


def merge_fetched_subscription(
    snapshot: PodcastSnapshot,
    fetched: PodcastSubscription,
    *,
    source: SubscriptionSource | None = None,
) -> PodcastSnapshot:
    """Merge refreshed feed metadata without discarding local device/history facts."""

    current = snapshot.subscription(fetched.subscription_id)
    if current is None:
        current = _subscription_matching_evidence(
            snapshot.subscriptions,
            (episode.episode_id for episode in fetched.episodes),
            fetched.title,
            fetched.author,
        )
    subscription_id = (
        current.subscription_id if current is not None else fetched.subscription_id
    )
    retained = (
        {episode.episode_id: episode for episode in current.episodes}
        if current is not None
        else {}
    )
    merged: list[PodcastEpisode] = []
    history = {
        (record.subscription_id, record.episode_id): record
        for record in snapshot.history
    }
    history_guids = _history_guid_index(history.values())
    guid_counts = Counter(episode.guid for episode in fetched.episodes if episode.guid)
    for episode in fetched.episodes:
        old = retained.pop(episode.episode_id, None)
        unique_guid = guid_counts[episode.guid] == 1
        if old is None and unique_guid and current is not None:
            match = _episode_matching_guid(current.episodes, episode.guid)
            if match is not None:
                old = retained.pop(match.episode_id, None)
        record = (
            _matching_history(history, history_guids, subscription_id, episode)
            if unique_guid
            else history.get((subscription_id, episode.episode_id))
        )
        if old is not None:
            episode = replace(
                episode,
                episode_id=old.episode_id,
                on_device=old.on_device,
                track_id=old.track_id,
                listened=old.listened,
                listened_override=old.listened_override,
                play_count=old.play_count,
                last_played=old.last_played,
                automatically_cleared=old.automatically_cleared,
            )
        elif record is not None:
            episode = replace(episode, episode_id=record.episode_id)
        record = history.get((subscription_id, episode.episode_id)) or record
        if record is not None:
            record = _enrich_history(record, episode)
            history[(subscription_id, record.episode_id)] = record
        merged.append(_with_history(episode, record))
    for episode in retained.values():
        record = history.get((subscription_id, episode.episode_id))
        # Independent history survives, but a vanished feed Episode must not
        # become a fresh automatic download candidate from stale metadata.
        if episode.on_device:
            merged.append(_with_history(episode, record))

    subscription = replace(
        fetched,
        subscription_id=subscription_id,
        source=source or (current.source if current is not None else fetched.source),
        artwork_id=current.artwork_id if current is not None else fetched.artwork_id,
        sync_settings=(
            current.sync_settings if current is not None else fetched.sync_settings
        ),
        episodes=_ordered_episodes(merged),
    )
    subscriptions = {item.subscription_id: item for item in snapshot.subscriptions}
    subscriptions[subscription.subscription_id] = subscription
    return replace(
        snapshot,
        subscriptions=_ordered_subscriptions(subscriptions.values()),
        history=_ordered_history(history.values()),
    )


def remove_subscription(
    snapshot: PodcastSnapshot,
    subscription_id: str,
) -> PodcastSnapshot:
    """Unsubscribe without deleting independent listening history."""

    if snapshot.subscription(subscription_id) is None:
        raise ValueError("The Podcast Subscription is no longer available")
    return replace(
        snapshot,
        subscriptions=tuple(
            item
            for item in snapshot.subscriptions
            if item.subscription_id != subscription_id
        ),
    )


def mark_episodes_listened(
    snapshot: PodcastSnapshot,
    subscription_id: str,
    episode_ids: Iterable[str],
    listened: bool,
    *,
    changed_at: int | None = None,
) -> PodcastSnapshot:
    """Persist an explicit listened/unlistened choice for selected episodes."""

    subscription = snapshot.subscription(subscription_id)
    if subscription is None:
        raise ValueError("The Podcast Subscription is no longer available")
    selected = frozenset(episode_ids)
    episodes = {episode.episode_id: episode for episode in subscription.episodes}
    if not selected or not selected <= episodes.keys():
        raise ValueError("The selected Podcast Episodes are no longer available")
    records = {
        (record.subscription_id, record.episode_id): record
        for record in snapshot.history
    }
    timestamp = int(time.time()) if changed_at is None else changed_at
    if timestamp < 0:
        raise ValueError("A listening-history time must not be negative")
    for episode_id in selected:
        episode = episodes[episode_id]
        old = records.get((subscription_id, episode_id))
        records[(subscription_id, episode_id)] = ListeningRecord(
            subscription_id,
            episode_id,
            guid=episode.guid or (old.guid if old else ""),
            enclosure_url=episode.enclosure_url or (old.enclosure_url if old else ""),
            title=episode.title or (old.title if old else ""),
            listened_override=listened,
            observed_play_count=old.observed_play_count if old else episode.play_count,
            last_played=max(
                old.last_played if old else episode.last_played,
                timestamp if listened else 0,
            ),
            published_at=episode.published_at or (old.published_at if old else 0),
            episode_number=episode.episode_number
            or (old.episode_number if old else None),
            automatically_cleared=(
                old.automatically_cleared if old else episode.automatically_cleared
            ),
        )
    updated = replace(snapshot, history=_ordered_history(records.values()))
    return _project_history(updated)


def mark_episode_selection_listened(
    snapshot: PodcastSnapshot,
    episode_identities: Iterable[tuple[str, str]],
    listened: bool,
    *,
    changed_at: int | None = None,
) -> PodcastSnapshot:
    """Persist one listened choice across Episodes from multiple subscriptions."""

    selected_by_subscription: dict[str, set[str]] = {}
    for subscription_id, episode_id in episode_identities:
        selected_by_subscription.setdefault(subscription_id, set()).add(episode_id)
    if not selected_by_subscription:
        raise ValueError("No Podcast Episodes were selected")

    timestamp = int(time.time()) if changed_at is None else changed_at
    if timestamp < 0:
        raise ValueError("A listening-history time must not be negative")
    updated = snapshot
    for subscription_id in sorted(selected_by_subscription):
        updated = mark_episodes_listened(
            updated,
            subscription_id,
            selected_by_subscription[subscription_id],
            listened,
            changed_at=timestamp,
        )
    return updated


def mark_episodes_automatically_cleared(
    snapshot: PodcastSnapshot,
    selections: tuple[tuple[str, str], ...],
) -> PodcastSnapshot:
    """Remember automatic removals without inventing a listened/unlistened choice.

    The caller publishes this desired history with the Library transaction that
    removes these Episodes. Manual additions may still select cleared Episodes.
    """
    selected = frozenset(selections)
    if not selected:
        raise ValueError("No Podcast Episodes were selected")
    episodes = {
        (subscription.subscription_id, episode.episode_id): episode
        for subscription in snapshot.subscriptions
        for episode in subscription.episodes
    }
    if not selected <= episodes.keys():
        raise ValueError("The selected Podcast Episodes are no longer available")
    records = {
        (record.subscription_id, record.episode_id): record
        for record in snapshot.history
    }
    for identity in selected:
        episode = episodes[identity]
        record = records.get(identity)
        if record is None:
            record = ListeningRecord(
                identity[0],
                identity[1],
                listened_override=episode.listened_override,
                observed_play_count=episode.play_count,
                last_played=episode.last_played,
            )
        records[identity] = replace(
            _enrich_history(record, episode),
            observed_play_count=max(record.observed_play_count, episode.play_count),
            last_played=max(record.last_played, episode.last_played),
            automatically_cleared=True,
        )
    return _project_history(
        replace(snapshot, history=_ordered_history(records.values()))
    )


def _project_history(snapshot: PodcastSnapshot) -> PodcastSnapshot:
    history = {
        (record.subscription_id, record.episode_id): record
        for record in snapshot.history
    }
    return replace(
        snapshot,
        subscriptions=tuple(
            replace(
                subscription,
                episodes=tuple(
                    _with_history(
                        episode,
                        history.get((subscription.subscription_id, episode.episode_id)),
                    )
                    for episode in subscription.episodes
                ),
            )
            for subscription in snapshot.subscriptions
        ),
    )


def _episode_from_track(track: Track) -> PodcastEpisode:
    enclosure = track.metadata.podcast_enclosure_url.strip()
    guid = track.episode.strip()
    published_at = track.metadata.release_date or track.metadata.date_added
    episode_number = track.episode_number or None
    season_number = track.season_number or None
    return PodcastEpisode(
        episode_identity(
            enclosure_url=enclosure,
            guid=guid,
            title=track.title,
            published_at=published_at,
            episode_number=episode_number,
            season_number=season_number,
        ),
        guid=guid,
        title=track.title.strip() or "Untitled Episode",
        description=track.metadata.description.strip(),
        enclosure_url=enclosure,
        published_at=published_at,
        duration_seconds=max(0, track.length_ms // 1000),
        size_bytes=track.size_bytes,
        episode_number=episode_number,
        season_number=season_number,
        on_device=True,
        track_id=track.track_id,
        play_count=max(track.play_count, track.metadata.unscrobbled_play_count),
        last_played=track.metadata.last_played,
    )


def _clear_device_projection(subscription: PodcastSubscription) -> PodcastSubscription:
    return replace(
        subscription,
        artwork_id=0,
        episodes=tuple(
            replace(
                episode,
                on_device=False,
                track_id=None,
                listened=False,
                listened_override=None,
                play_count=0,
                last_played=0,
                automatically_cleared=False,
            )
            for episode in subscription.episodes
        ),
    )


def _subscription_matching_evidence(
    subscriptions: Iterable[PodcastSubscription],
    episode_ids: Iterable[str],
    title: str,
    author: str,
) -> PodcastSubscription | None:
    candidates = tuple(subscriptions)
    identities = frozenset(episode_ids)
    if identities:
        episode_matches = tuple(
            subscription
            for subscription in candidates
            if any(
                episode.episode_id in identities for episode in subscription.episodes
            )
        )
        if len(episode_matches) == 1:
            return episode_matches[0]

    normalized_title = title.strip().casefold()
    normalized_author = author.strip().casefold()
    if not normalized_title:
        return None
    title_matches = tuple(
        subscription
        for subscription in candidates
        if subscription.title.strip().casefold() == normalized_title
        and (
            not normalized_author
            or not subscription.author.strip()
            or subscription.author.strip().casefold() == normalized_author
        )
    )
    return title_matches[0] if len(title_matches) == 1 else None


def _with_history(
    episode: PodcastEpisode,
    history: ListeningRecord | None,
) -> PodcastEpisode:
    if history is None:
        return replace(
            episode,
            listened=episode.play_count > 0 or episode.last_played > 0,
        )
    return replace(
        episode,
        listened=history.listened,
        listened_override=history.listened_override,
        play_count=max(episode.play_count, history.observed_play_count),
        last_played=max(episode.last_played, history.last_played),
        published_at=episode.published_at or history.published_at,
        episode_number=episode.episode_number or history.episode_number,
        automatically_cleared=history.automatically_cleared,
    )


def _enrich_history(
    record: ListeningRecord, episode: PodcastEpisode
) -> ListeningRecord:
    """Retain publisher ordering facts even after the Episode leaves its feed."""
    return replace(
        record,
        guid=episode.guid or record.guid,
        enclosure_url=episode.enclosure_url or record.enclosure_url,
        title=episode.title or record.title,
        published_at=episode.published_at or record.published_at,
        episode_number=episode.episode_number or record.episode_number,
    )


def _episode_matching_guid(
    episodes: Iterable[PodcastEpisode], guid: str
) -> PodcastEpisode | None:
    if not guid:
        return None
    matches = tuple(episode for episode in episodes if episode.guid == guid)
    return matches[0] if len(matches) == 1 else None


def _matching_history(
    records: dict[tuple[str, str], ListeningRecord],
    by_guid: dict[tuple[str, str], ListeningRecord | None],
    subscription_id: str,
    episode: PodcastEpisode,
    *,
    allow_guid: bool = True,
) -> ListeningRecord | None:
    exact = records.get((subscription_id, episode.episode_id))
    if exact is not None or not episode.guid or not allow_guid:
        return exact
    return by_guid.get((subscription_id, episode.guid))


def _history_guid_index(
    records: Iterable[ListeningRecord],
) -> dict[tuple[str, str], ListeningRecord | None]:
    result: dict[tuple[str, str], ListeningRecord | None] = {}
    for record in records:
        if record.guid:
            key = (record.subscription_id, record.guid)
            result[key] = None if key in result else record
    return result


def _ordered_episodes(episodes: Iterable[PodcastEpisode]) -> tuple[PodcastEpisode, ...]:
    return tuple(
        sorted(
            episodes,
            key=lambda item: (
                -item.published_at,
                -(item.episode_number or 0),
                item.title.casefold(),
                item.episode_id,
            ),
        )
    )


def _ordered_subscriptions(
    subscriptions: Iterable[PodcastSubscription],
) -> tuple[PodcastSubscription, ...]:
    return tuple(
        sorted(
            subscriptions,
            key=lambda item: (item.title.casefold(), item.subscription_id),
        )
    )


def _ordered_history(records: Iterable[ListeningRecord]) -> tuple[ListeningRecord, ...]:
    return tuple(
        sorted(records, key=lambda item: (item.subscription_id, item.episode_id))
    )


__all__ = [
    "mark_episode_selection_listened",
    "mark_episodes_automatically_cleared",
    "mark_episodes_listened",
    "merge_fetched_subscription",
    "reconcile_device_podcasts",
    "remove_subscription",
]
