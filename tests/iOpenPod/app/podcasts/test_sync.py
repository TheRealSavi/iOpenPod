from dataclasses import replace

import pytest

from iOpenPod.app.podcasts.models import (
    ListeningRecord,
    PodcastClearAge,
    PodcastClearMethod,
    PodcastEpisode,
    PodcastFillMode,
    PodcastSnapshot,
    PodcastSubscription,
    PodcastSyncSettings,
    SubscriptionSource,
)
from iOpenPod.app.podcasts.sync import (
    PodcastSyncPlan,
    PodcastSyncRequest,
    plan_podcast_sync,
)
from iPodDB.library import LibrarySnapshot, MediaType, Track, TrackMetadata


def _episode(
    number: int, *, on_device: bool = False, listened: bool = False
) -> PodcastEpisode:
    return PodcastEpisode(
        f"episode-{number}",
        title=f"Episode {number}",
        enclosure_url=f"https://example.test/{number}.mp3",
        published_at=number * 100,
        on_device=on_device,
        track_id=number if on_device else None,
        listened=listened,
    )


def _show(
    *episodes: PodcastEpisode, settings: PodcastSyncSettings | None = None
) -> PodcastSubscription:
    return PodcastSubscription(
        "show",
        "https://example.test/feed",
        "Show",
        SubscriptionSource.USER,
        episodes=episodes,
        sync_settings=settings or PodcastSyncSettings(),
    )


def _library(show: PodcastSubscription, *, date_added: int = 1_000) -> LibrarySnapshot:
    return LibrarySnapshot(
        tuple(
            Track(
                episode.track_id,
                episode.title,
                "",
                show.title,
                1_000,
                media_types=(MediaType.PODCAST,),
                metadata=TrackMetadata(
                    podcast=True,
                    date_added=date_added,
                    podcast_enclosure_url=episode.enclosure_url,
                    podcast_rss_url=show.feed_url,
                ),
            )
            for episode in show.episodes
            if episode.track_id is not None
        )
    )


def _plan(
    show: PodcastSubscription,
    *,
    now: int = 100_000,
    date_added: int = 1_000,
    history: tuple[ListeningRecord, ...] = (),
) -> PodcastSyncPlan:
    return plan_podcast_sync(
        PodcastSyncRequest(PodcastSnapshot((show,), history, writable=True)),
        _library(show, date_added=date_added),
        now=now,
    )


def _added(plan: PodcastSyncPlan) -> tuple[str, ...]:
    return tuple(item.episode.episode_id for item in plan.additions)


@pytest.mark.parametrize("method", tuple(PodcastClearMethod))
def test_newest_adds_latest_and_repeated_sync_does_not_rotate_backwards(
    method: PodcastClearMethod,
) -> None:
    settings = PodcastSyncSettings(episode_slots=2, clear_method=method)
    initial = _show(*(_episode(number) for number in range(1, 5)), settings=settings)
    assert _added(_plan(initial)) == ("episode-4", "episode-3")
    synced = replace(
        initial,
        episodes=tuple(
            replace(episode, on_device=True, track_id=number)
            if number >= 3
            else episode
            for number, episode in enumerate(initial.episodes, 1)
        ),
    )
    assert _plan(synced) == PodcastSyncPlan()


def test_newest_replacement_pairs_only_a_clear_eligible_episode() -> None:
    show = _show(
        _episode(1, on_device=True, listened=True),
        _episode(2, on_device=True),
        _episode(3),
        settings=PodcastSyncSettings(
            episode_slots=2, clear_method=PodcastClearMethod.REPLACE
        ),
    )
    plan = _plan(show)
    assert _added(plan) == ("episode-3",)
    assert plan.additions[0].replaces_track_id == 1
    assert plan.removals == ()


def test_newest_skips_history_but_manual_unlistened_override_remains_eligible() -> None:
    listened = replace(_episode(3), listened=True, listened_override=True)
    overridden = replace(
        _episode(2, on_device=True), play_count=4, listened_override=False
    )
    show = _show(
        _episode(1), overridden, listened, settings=PodcastSyncSettings(episode_slots=1)
    )
    assert _plan(show) == PodcastSyncPlan()


@pytest.mark.parametrize("mode", tuple(PodcastFillMode))
def test_manual_listened_override_authorizes_clearing_in_both_modes(
    mode: PodcastFillMode,
) -> None:
    played = replace(_episode(1, on_device=True), listened=True, listened_override=True)
    show = _show(
        played,
        _episode(2),
        settings=PodcastSyncSettings(episode_slots=1, fill_mode=mode),
    )
    plan = _plan(show)
    assert plan.removals == (1,)
    assert _added(plan) == ("episode-2",)


def test_next_starts_oldest_and_manual_future_episode_does_not_advance_position() -> (
    None
):
    settings = PodcastSyncSettings(episode_slots=2, fill_mode=PodcastFillMode.NEXT)
    show = _show(*(_episode(number) for number in range(1, 5)), settings=settings)
    assert _added(_plan(show)) == ("episode-1", "episode-2")
    show = replace(
        show,
        episodes=tuple(
            replace(episode, on_device=True, track_id=3)
            if episode.episode_id == "episode-3"
            else episode
            for episode in show.episodes
        ),
    )
    assert _added(_plan(show)) == ("episode-1",)


def test_next_replacement_does_not_wrap_to_older_episode() -> None:
    show = _show(
        _episode(1),
        _episode(2, on_device=True, listened=True),
        settings=PodcastSyncSettings(
            episode_slots=1,
            fill_mode=PodcastFillMode.NEXT,
            clear_method=PodcastClearMethod.REPLACE,
        ),
    )
    assert _plan(show) == PodcastSyncPlan()


def test_next_remove_does_not_restart_before_the_furthest_listened_episode() -> None:
    show = _show(
        _episode(1),
        _episode(2, on_device=True, listened=True),
        settings=PodcastSyncSettings(episode_slots=1, fill_mode=PodcastFillMode.NEXT),
    )
    plan = _plan(show)
    assert plan.removals == (2,)
    assert _added(plan) == ()


@pytest.mark.parametrize(
    ("date_added", "now", "cleared"),
    ((1_000, 87_400, False), (1_000, 87_401, True), (0, 99_999, False)),
)
def test_next_ages_by_device_addition_time_and_strict_threshold(
    date_added: int, now: int, cleared: bool
) -> None:
    show = _show(
        _episode(1, on_device=True),
        settings=PodcastSyncSettings(
            fill_mode=PodcastFillMode.NEXT,
            clear_when_listened=False,
            clear_older_than=PodcastClearAge.DAY,
        ),
    )
    assert _plan(show, now=now, date_added=date_added).removals == (
        (1,) if cleared else ()
    )


@pytest.mark.parametrize("mode", tuple(PodcastFillMode))
def test_replacement_keeps_listened_episode_without_available_replacement(
    mode: PodcastFillMode,
) -> None:
    show = _show(
        _episode(1, on_device=True, listened=True),
        settings=PodcastSyncSettings(
            episode_slots=1, fill_mode=mode, clear_method=PodcastClearMethod.REPLACE
        ),
    )
    assert _plan(show) == PodcastSyncPlan()


@pytest.mark.parametrize("mode", tuple(PodcastFillMode))
def test_replacement_clears_only_when_paired_addition_succeeds(
    mode: PodcastFillMode,
) -> None:
    show = _show(
        _episode(1, on_device=True, listened=True),
        _episode(2),
        settings=PodcastSyncSettings(
            episode_slots=1, fill_mode=mode, clear_method=PodcastClearMethod.REPLACE
        ),
    )
    plan = _plan(show)
    assert plan.removals == ()
    assert plan.additions[0].replaces_track_id == 1


@pytest.mark.parametrize("mode", tuple(PodcastFillMode))
def test_lower_slot_limit_retains_existing_episodes_without_clear_eligibility(
    mode: PodcastFillMode,
) -> None:
    show = _show(
        *(_episode(number, on_device=True) for number in range(1, 5)),
        settings=PodcastSyncSettings(
            episode_slots=2, fill_mode=mode, clear_method=PodcastClearMethod.REPLACE
        ),
    )
    plan = _plan(show)
    assert plan.additions == ()
    assert plan.removals == ()


def test_manual_add_bypasses_slots_and_listened_retention() -> None:
    show = _show(
        _episode(1, on_device=True),
        _episode(2, listened=True),
        settings=PodcastSyncSettings(episode_slots=1),
    )
    plan = plan_podcast_sync(
        PodcastSyncRequest(
            PodcastSnapshot((show,), writable=True),
            additions=(("show", "episode-2"),),
            automatic=False,
        ),
        _library(show),
    )
    assert _added(plan) == ("episode-2",)
    assert plan.removals == ()


def test_per_show_sync_does_not_change_other_subscription() -> None:
    show = _show(_episode(1))
    other = replace(_show(_episode(2)), subscription_id="other")
    plan = plan_podcast_sync(
        PodcastSyncRequest(
            PodcastSnapshot((show, other), writable=True), subscription_ids=("show",)
        ),
        LibrarySnapshot(),
    )
    assert _added(plan) == ("episode-1",)


def test_manual_cross_show_removal_deduplicates_selection() -> None:
    show = _show(_episode(1, on_device=True))
    other = replace(_show(_episode(2, on_device=True)), subscription_id="other")
    plan = plan_podcast_sync(
        PodcastSyncRequest(
            PodcastSnapshot((show, other), writable=True),
            removals=(
                ("show", "episode-1"),
                ("other", "episode-2"),
                ("show", "episode-1"),
            ),
            automatic=False,
        ),
        LibrarySnapshot((*_library(show).tracks, *_library(other).tracks)),
    )
    assert plan.removals == (1, 2)


def test_changed_membership_cannot_remove_a_non_podcast_track() -> None:
    show = _show(_episode(1, on_device=True, listened=True))
    library = LibrarySnapshot((Track(1, "Music", "", "", 1_000),))
    plan = plan_podcast_sync(
        PodcastSyncRequest(PodcastSnapshot((show,), writable=True)), library
    )
    assert plan.removals == ()
    assert plan.issues[0].code == "podcast.stale_membership"


def test_unknown_manual_selection_and_missing_media_are_reported() -> None:
    show = _show(replace(_episode(1), enclosure_url="file:///secret.mp3"))
    plan = plan_podcast_sync(
        PodcastSyncRequest(
            PodcastSnapshot((show,), writable=True),
            additions=(("show", "episode-1"), ("show", "missing")),
            automatic=False,
        ),
        LibrarySnapshot(),
    )
    assert plan.additions == ()
    assert {issue.code for issue in plan.issues} == {
        "podcast.missing_media",
        "podcast.missing_episode",
    }


def test_managed_sync_preserves_playable_device_episode_without_download_url() -> None:
    show = _show(replace(_episode(1, on_device=True), enclosure_url=""))
    assert _plan(show) == PodcastSyncPlan()


@pytest.mark.parametrize("successful", (True, False))
def test_newest_overcapacity_replacements_do_not_grow_or_trim_the_library(
    successful: bool,
) -> None:
    show = _show(
        *(
            _episode(number, on_device=True, listened=number == 1)
            for number in range(1, 6)
        ),
        _episode(6),
        _episode(7),
        settings=PodcastSyncSettings(
            episode_slots=3, clear_method=PodcastClearMethod.REPLACE
        ),
    )
    plan = _plan(show)
    assert plan.removals == ()
    assert len(plan.additions) == 1
    assert plan.additions[0].replaces_track_id == 1
    removed: set[int] = set(plan.removals)
    if successful:
        removed.update(
            item.replaces_track_id
            for item in plan.additions
            if item.replaces_track_id is not None
        )
    retained = {1, 2, 3, 4, 5} - removed
    assert 5 in retained
    assert len(retained) + (len(plan.additions) if successful else 0) == 5
    if successful:
        assert retained == {2, 3, 4, 5}


def test_hidden_duplicate_device_episode_blocks_automatic_retention() -> None:
    show = _show(_episode(1, on_device=True, listened=True), _episode(2))
    library = _library(show)
    library = replace(
        library, tracks=(*library.tracks, replace(library.tracks[0], track_id=99))
    )
    plan = plan_podcast_sync(
        PodcastSyncRequest(PodcastSnapshot((show,), writable=True)), library
    )
    assert plan.removals == ()
    assert plan.additions == ()
    assert plan.issues[0].code == "podcast.ambiguous_identity"


def test_unresolved_guid_match_blocks_duplicate_addition_and_retention() -> None:
    show = _show(replace(_episode(2), guid="stable-guid"))
    existing = replace(
        _library(_show(_episode(1, on_device=True))).tracks[0], episode="stable-guid"
    )
    plan = plan_podcast_sync(
        PodcastSyncRequest(PodcastSnapshot((show,), writable=True)),
        LibrarySnapshot((existing,)),
    )
    assert plan.additions == ()
    assert plan.issues[0].code == "podcast.ambiguous_identity"


@pytest.mark.parametrize("method", tuple(PodcastClearMethod))
def test_new_publication_never_evicts_an_ineligible_occupied_slot(
    method: PodcastClearMethod,
) -> None:
    show = _show(
        _episode(1, on_device=True),
        _episode(2),
        settings=PodcastSyncSettings(episode_slots=1, clear_method=method),
    )
    assert _plan(show) == PodcastSyncPlan()


@pytest.mark.parametrize("mode", tuple(PodcastFillMode))
@pytest.mark.parametrize("method", tuple(PodcastClearMethod))
def test_overcapacity_retains_every_ineligible_episode(
    mode: PodcastFillMode,
    method: PodcastClearMethod,
) -> None:
    show = _show(
        *(_episode(number, on_device=True) for number in range(1, 5)),
        _episode(5),
        settings=PodcastSyncSettings(
            episode_slots=3, fill_mode=mode, clear_method=method
        ),
    )
    assert _plan(show) == PodcastSyncPlan()


@pytest.mark.parametrize("mode", tuple(PodcastFillMode))
def test_overcapacity_replace_swaps_without_filling_additional_slots(
    mode: PodcastFillMode,
) -> None:
    show = _show(
        _episode(1, on_device=True, listened=True),
        *(_episode(number, on_device=True) for number in range(2, 5)),
        _episode(5),
        _episode(6),
        settings=PodcastSyncSettings(
            episode_slots=3, fill_mode=mode, clear_method=PodcastClearMethod.REPLACE
        ),
    )
    plan = _plan(show)
    assert plan.removals == ()
    assert len(plan.additions) == 1
    assert plan.additions[0].replaces_track_id == 1
    assert plan.automatic_removals == (("show", "episode-1"),)


@pytest.mark.parametrize("mode", tuple(PodcastFillMode))
def test_overcapacity_remove_drains_excess_before_refilling(
    mode: PodcastFillMode,
) -> None:
    show = _show(
        _episode(1, on_device=True, listened=True),
        *(_episode(number, on_device=True) for number in range(2, 5)),
        _episode(5),
        settings=PodcastSyncSettings(episode_slots=3, fill_mode=mode),
    )
    plan = _plan(show)
    assert plan.removals == (1,)
    assert plan.additions == ()


@pytest.mark.parametrize("mode", tuple(PodcastFillMode))
def test_age_clear_applies_in_both_fill_modes(mode: PodcastFillMode) -> None:
    show = _show(
        _episode(1, on_device=True),
        _episode(2),
        settings=PodcastSyncSettings(
            episode_slots=1,
            fill_mode=mode,
            clear_when_listened=False,
            clear_older_than=PodcastClearAge.DAY,
        ),
    )
    plan = _plan(show, date_added=1_000, now=90_000)
    assert plan.removals == (1,)
    assert _added(plan) == ("episode-2",)
    assert plan.automatic_removals == (("show", "episode-1"),)


@pytest.mark.parametrize("mode", tuple(PodcastFillMode))
def test_immediate_clear_does_not_require_an_added_timestamp(
    mode: PodcastFillMode,
) -> None:
    show = _show(
        _episode(1, on_device=True),
        settings=PodcastSyncSettings(
            episode_slots=1, fill_mode=mode, clear_older_than=PodcastClearAge.IMMEDIATE
        ),
    )
    assert _plan(show, date_added=0, now=0).removals == (1,)


@pytest.mark.parametrize("method", tuple(PodcastClearMethod))
def test_newest_never_replaces_a_cleared_episode_with_an_older_one(
    method: PodcastClearMethod,
) -> None:
    show = _show(
        _episode(1),
        _episode(2, on_device=True),
        settings=PodcastSyncSettings(
            episode_slots=1,
            clear_older_than=PodcastClearAge.IMMEDIATE,
            clear_method=method,
        ),
    )
    plan = _plan(show)
    assert plan.additions == ()
    assert plan.removals == ((2,) if method is PodcastClearMethod.REMOVE else ())


def test_newest_uses_old_catalog_only_for_vacancies_that_preceded_clearing() -> None:
    show = _show(
        _episode(8),
        _episode(9),
        _episode(10, on_device=True),
        settings=PodcastSyncSettings(
            episode_slots=3, clear_older_than=PodcastClearAge.IMMEDIATE
        ),
    )
    plan = _plan(show)
    assert plan.removals == (10,)
    assert _added(plan) == ("episode-9", "episode-8")


def test_newest_removal_does_not_downgrade_on_a_later_sync() -> None:
    settings = PodcastSyncSettings(
        episode_slots=1, clear_older_than=PodcastClearAge.IMMEDIATE
    )
    before = _show(_episode(1), _episode(2, on_device=True), settings=settings)
    assert _plan(before).removals == (2,)
    history = (
        ListeningRecord(
            "show", "episode-2", published_at=200, automatically_cleared=True
        ),
    )
    after = _show(
        _episode(1), replace(_episode(2), automatically_cleared=True), settings=settings
    )
    assert _plan(after, history=history) == PodcastSyncPlan()
    # The retired Episode may vanish from the feed without losing its position.
    assert (
        _plan(_show(_episode(1), settings=settings), history=history)
        == PodcastSyncPlan()
    )
    assert _added(
        _plan(replace(after, episodes=(*after.episodes, _episode(3))), history=history)
    ) == ("episode-3",)


def test_newest_uses_newest_candidates_while_maximizing_valid_replacements() -> None:
    show = _show(
        _episode(10, on_device=True),
        _episode(20, on_device=True),
        _episode(15),
        _episode(18),
        _episode(25),
        settings=PodcastSyncSettings(
            episode_slots=2,
            clear_older_than=PodcastClearAge.IMMEDIATE,
            clear_method=PodcastClearMethod.REPLACE,
        ),
    )
    plan = _plan(show)
    assert [
        (item.episode.episode_id, item.replaces_track_id) for item in plan.additions
    ] == [("episode-25", 20), ("episode-18", 10)]


def test_next_uses_furthest_listened_publication_and_not_most_recent_play() -> None:
    show = _show(
        replace(_episode(1, listened=True), last_played=900),
        _episode(2),
        replace(_episode(3, listened=True), last_played=100),
        _episode(4),
        _episode(5),
        settings=PodcastSyncSettings(episode_slots=1, fill_mode=PodcastFillMode.NEXT),
    )
    assert _added(_plan(show)) == ("episode-4",)


def test_next_keeps_listening_position_after_episode_removal_and_feed_truncation() -> (
    None
):
    show = _show(
        _episode(1),
        _episode(2),
        _episode(4),
        _episode(5),
        settings=PodcastSyncSettings(episode_slots=1, fill_mode=PodcastFillMode.NEXT),
    )
    history = (
        ListeningRecord("show", "episode-3", published_at=300, observed_play_count=1),
    )
    assert _added(_plan(show, history=history)) == ("episode-4",)


def test_next_history_uses_episode_number_for_equal_publication_dates() -> None:
    show = _show(
        replace(_episode(1), published_at=100, episode_number=1),
        replace(_episode(3), published_at=100, episode_number=3),
        settings=PodcastSyncSettings(episode_slots=1, fill_mode=PodcastFillMode.NEXT),
    )
    history = (
        ListeningRecord(
            "show",
            "episode-2",
            published_at=100,
            episode_number=2,
            listened_override=True,
        ),
    )
    assert _added(_plan(show, history=history)) == ("episode-3",)


def test_next_age_retirement_excludes_identity_without_advancing_listening_position() -> (
    None
):
    show = _show(
        _episode(1),
        _episode(3),
        _episode(4),
        replace(_episode(9), automatically_cleared=True),
        settings=PodcastSyncSettings(episode_slots=1, fill_mode=PodcastFillMode.NEXT),
    )
    history = (
        ListeningRecord("show", "episode-2", published_at=200, observed_play_count=1),
        ListeningRecord(
            "show", "episode-9", published_at=900, automatically_cleared=True
        ),
    )
    assert _added(_plan(show, history=history)) == ("episode-3",)


def test_next_no_history_skips_retired_episode_instead_of_repeatedly_downloading_it() -> (
    None
):
    show = _show(
        _episode(1),
        _episode(2),
        _episode(3),
        settings=PodcastSyncSettings(episode_slots=1, fill_mode=PodcastFillMode.NEXT),
    )
    history = (
        ListeningRecord(
            "show", "episode-1", published_at=100, automatically_cleared=True
        ),
    )
    assert _added(_plan(show, history=history)) == ("episode-2",)


def test_next_can_replace_aged_manual_future_episode_with_next_after_listening_position() -> (
    None
):
    show = _show(
        _episode(3),
        _episode(9, on_device=True),
        settings=PodcastSyncSettings(
            episode_slots=1,
            fill_mode=PodcastFillMode.NEXT,
            clear_older_than=PodcastClearAge.DAY,
            clear_method=PodcastClearMethod.REPLACE,
        ),
    )
    history = (
        ListeningRecord("show", "episode-2", published_at=200, observed_play_count=1),
    )
    plan = _plan(show, history=history)
    assert _added(plan) == ("episode-3",)
    assert plan.additions[0].replaces_track_id == 9


def test_manual_add_bypasses_automatic_retirement_and_newest_position() -> None:
    retired = replace(_episode(1), automatically_cleared=True)
    show = _show(
        retired,
        _episode(2, on_device=True),
        settings=PodcastSyncSettings(episode_slots=1),
    )
    snapshot = PodcastSnapshot(
        (show,),
        (
            ListeningRecord(
                "show", "episode-1", published_at=100, automatically_cleared=True
            ),
        ),
        writable=True,
    )
    plan = plan_podcast_sync(
        PodcastSyncRequest(
            snapshot, additions=(("show", "episode-1"),), automatic=False
        ),
        _library(show),
    )
    assert _added(plan) == ("episode-1",)
    assert plan.automatic_removals == ()


def test_manual_removal_does_not_mark_episode_automatically_cleared() -> None:
    show = _show(_episode(1, on_device=True))
    plan = plan_podcast_sync(
        PodcastSyncRequest(
            PodcastSnapshot((show,), writable=True),
            removals=(("show", "episode-1"),),
            automatic=False,
        ),
        _library(show),
    )
    assert plan.removals == (1,)
    assert plan.automatic_removals == ()


@pytest.mark.parametrize("method", tuple(PodcastClearMethod))
def test_newest_does_not_treat_episode_identity_order_as_a_newer_publication(
    method: PodcastClearMethod,
) -> None:
    existing = replace(_episode(1, on_device=True), episode_id="a", episode_number=7)
    candidate = replace(_episode(2), episode_id="z", published_at=100, episode_number=7)
    show = _show(
        existing,
        candidate,
        settings=PodcastSyncSettings(
            episode_slots=1,
            clear_older_than=PodcastClearAge.IMMEDIATE,
            clear_method=method,
        ),
    )

    plan = _plan(show)

    assert plan.additions == ()
    assert plan.removals == ((1,) if method is PodcastClearMethod.REMOVE else ())


def test_newest_retired_position_ignores_identity_ties_but_accepts_newer_numbers() -> (
    None
):
    history = (
        ListeningRecord(
            "show", "a", published_at=100, episode_number=7, automatically_cleared=True
        ),
    )
    candidate = replace(_episode(2), episode_id="z", published_at=100, episode_number=7)
    show = _show(candidate, settings=PodcastSyncSettings(episode_slots=1))

    assert _plan(show, history=history) == PodcastSyncPlan()
    newer = replace(candidate, episode_number=8)
    assert _added(_plan(replace(show, episodes=(newer,)), history=history)) == ("z",)
