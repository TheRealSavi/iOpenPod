"""Background workflow that reconciles Active iPod and Jellyfin play counts."""

from __future__ import annotations

from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, replace
from threading import Lock
from typing import TYPE_CHECKING, Protocol

from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    PreparationCancelledError,
)
from iPodDB.library import (
    IssueSeverity,
    MediaKind,
    TrackEditError,
    TrackFieldEdit,
    edit_track_metadata,
)

from .client import JellyfinClient
from .matching import MatchOutcome, TrackIndex
from .models import MAX_PLAY_COUNT, JellyfinError, PlayCountResult
from .state import PairState, merged_count, pair_key

if TYPE_CHECKING:
    from collections.abc import Callable
    from threading import Event

    from iOpenPod.app.library_write import (
        LibraryReview,
        LibrarySaveResult,
        WriteProgress,
    )
    from iOpenPod.app.models.device import ActiveIPod
    from iPodDB.library import Track, WriteIssue

    from .models import JellyfinAccount, JellyfinTrack
    from .state import PlayCountState, PlayCountStore
    from .token_store import TokenStore

SAVE_INTERVAL = 50


class PlayCountSource(Protocol):
    def scrobble_context(
        self, expected: ActiveIPod
    ) -> tuple[str, Callable[[], None]]: ...

    def prepare_library(
        self,
        request: LibraryPreparationRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: Event,
    ) -> LibraryReview: ...

    def save_library(
        self,
        review: LibraryReview,
        expected: ActiveIPod,
        progress: Callable[[WriteProgress], None],
        cancelled: Event,
    ) -> LibrarySaveResult: ...


@dataclass(frozen=True, slots=True)
class _Pair:
    key: str
    track: Track
    remote: JellyfinTrack
    target: int


class _CancelledError(Exception):
    pass


def _label(track: Track) -> str:
    return " - ".join(part for part in (track.artist, track.title) if part)


def _errors(issues: tuple[WriteIssue, ...]) -> tuple[str, ...]:
    return tuple(
        f"{issue.message} {issue.detail}".strip()
        for issue in issues
        if issue.severity is IssueSeverity.ERROR
    ) or ("The iPod Library could not be saved.",)


class PlayCountService:
    def __init__(
        self,
        coordinator: PlayCountSource,
        store: PlayCountStore,
        tokens: TokenStore,
        *,
        client: JellyfinClient | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._store = store
        self._tokens = tokens
        self._client = client or JellyfinClient()
        self._lock = Lock()

    def run(
        self,
        active: ActiveIPod,
        cancelled: Event,
        progress: Callable[[str], None],
    ) -> PlayCountResult:
        if not self._lock.acquire(blocking=False):
            raise JellyfinError("Play count sync is already running.")
        try:
            with self._store.lease():
                return self._run(active, cancelled, progress)
        finally:
            self._lock.release()

    def _run(
        self,
        active: ActiveIPod,
        cancelled: Event,
        progress: Callable[[str], None],
    ) -> PlayCountResult:
        account = self._tokens.load()
        if account is None:
            raise JellyfinError("Connect Jellyfin in Settings → Sync first.")
        device, device_checkpoint = self._coordinator.scrobble_context(active)

        def checkpoint() -> None:
            if cancelled.is_set():
                raise _CancelledError
            device_checkpoint()

        # An unreadable state file must stop the run before anything changes.
        state = self._store.load()
        try:
            progress("Reading the Jellyfin music library…")
            remote = self._client.tracks(account, checkpoint)
            checkpoint()
        except _CancelledError:
            return PlayCountResult(cancelled=True)
        progress("Matching iPod songs with Jellyfin…")
        pairs, unmatched, ambiguous, issues = self._pairs(
            active, account, device, state, remote
        )
        result = PlayCountResult(
            matched=len(pairs), unmatched=unmatched, ambiguous=ambiguous
        )

        edited: dict[int, Track] = {}
        for pair in list(pairs):
            if pair.target == pair.track.play_count:
                continue
            changes = [TrackFieldEdit("play_count", pair.target)]
            if not pair.track.metadata.played:
                changes.append(TrackFieldEdit("metadata.played", True))
            try:
                edited[pair.track.track_id] = edit_track_metadata(
                    pair.track, tuple(changes)
                )
            except TrackEditError as error:
                issues.append(f"{_label(pair.track)}: {error}")
                pairs.remove(pair)

        saved_active: ActiveIPod | None = None
        if edited:
            outcome = self._save_ipod(
                active, state, pairs, edited, cancelled, progress, checkpoint
            )
            if isinstance(outcome, PlayCountResult):
                return replace(
                    outcome,
                    matched=len(pairs),
                    unmatched=unmatched,
                    ambiguous=ambiguous,
                    issues=(*issues, *outcome.issues),
                )
            saved_active = outcome
        result = replace(
            result, matched=len(pairs), ipod_updated=len(edited), active=saved_active
        )
        # After an iPod save the app must always learn about the new Library.
        try:
            return self._push(
                account, state, pairs, edited, result, issues, cancelled, progress
            )
        except Exception:
            if saved_active is None:
                raise
            return replace(
                result,
                issues=(
                    *issues,
                    "Play counts were saved on the iPod, but Jellyfin could not be "
                    "fully updated. Run play count sync again.",
                ),
            )

    def _pairs(
        self,
        active: ActiveIPod,
        account: JellyfinAccount,
        device: str,
        state: PlayCountState,
        remote: tuple[JellyfinTrack, ...],
    ) -> tuple[list[_Pair], tuple[str, ...], tuple[str, ...], list[str]]:
        index = TrackIndex(remote)
        unmatched: list[str] = []
        ambiguous: list[str] = []
        issues: list[str] = []
        found: list[tuple[str, Track, JellyfinTrack]] = []
        for track in active.library.tracks:
            if (
                track.media_kind is not MediaKind.MUSIC
                or track.ipod is None
                or track.ipod.db_track_id <= 0
            ):
                continue
            key = pair_key(account.identity, device, track.ipod.db_track_id)
            previous = state.pairs.get(key)
            match = index.match(track, previous.item_id if previous else "")
            if match.outcome is MatchOutcome.MATCHED and match.remote is not None:
                found.append((key, track, match.remote))
            elif match.outcome is MatchOutcome.AMBIGUOUS:
                ambiguous.append(_label(track))
            else:
                unmatched.append(_label(track))
        # Two iPod songs claiming one Jellyfin item would overwrite each other.
        claims = Counter(item.item_id for _, _, item in found)
        pairs: list[_Pair] = []
        for key, track, item in found:
            if claims[item.item_id] > 1:
                ambiguous.append(_label(track))
                continue
            previous = state.pairs.get(key)
            if previous is not None and previous.item_id != item.item_id:
                previous = None
            target = merged_count(previous, track.play_count, item.play_count)
            if target > MAX_PLAY_COUNT:
                issues.append(f"{_label(track)}: the play count is too large.")
                continue
            pairs.append(_Pair(key, track, item, target))
        return pairs, tuple(unmatched), tuple(ambiguous), issues

    def _save_ipod(
        self,
        active: ActiveIPod,
        state: PlayCountState,
        pairs: list[_Pair],
        edited: dict[int, Track],
        cancelled: Event,
        progress: Callable[[str], None],
        checkpoint: Callable[[], None],
    ) -> ActiveIPod | PlayCountResult:
        changed = [pair for pair in pairs if pair.track.track_id in edited]
        before = {pair.key: state.pairs.get(pair.key) for pair in changed}

        def restore() -> None:
            for key, previous in before.items():
                if previous is None:
                    state.pairs.pop(key, None)
                else:
                    state.pairs[key] = previous
            self._store.save(state)

        # Journal first: if the save lands but this process stops, the next run
        # must not add the same plays again.
        for pair in changed:
            state.pairs[pair.key] = PairState(
                pair.remote.item_id,
                pair.target,
                pair.track.play_count,
                pair.remote.play_count,
                pending=True,
            )
        self._store.save(state)

        def forward(value: WriteProgress) -> None:
            progress(value.message)

        snapshot = replace(
            active.library,
            tracks=tuple(
                edited.get(track.track_id, track) for track in active.library.tracks
            ),
        )
        try:
            checkpoint()
            progress("Preparing iPod play counts…")
            review = self._coordinator.prepare_library(
                LibraryPreparationRequest(snapshot, active, 0, 0), forward, cancelled
            )
        except (_CancelledError, PreparationCancelledError):
            restore()
            return PlayCountResult(cancelled=True)
        if review.result.prepared is None:
            restore()
            return PlayCountResult(issues=_errors(review.result.issues))
        saved = self._coordinator.save_library(review, active, forward, cancelled)
        if saved.active is None:
            # The journal stays pending: the save may or may not have landed.
            return PlayCountResult(
                issues=_errors(saved.issues), cancelled=cancelled.is_set()
            )
        for pair in changed:
            state.pairs[pair.key] = PairState(
                pair.remote.item_id, pair.target, pair.target, pair.remote.play_count
            )
        # The push step saves the same state again and reports a failure there;
        # the saved Library must reach the caller either way.
        with suppress(Exception):
            self._store.save(state)
        return saved.active

    def _push(
        self,
        account: JellyfinAccount,
        state: PlayCountState,
        pairs: list[_Pair],
        edited: dict[int, Track],
        result: PlayCountResult,
        issues: list[str],
        cancelled: Event,
        progress: Callable[[str], None],
    ) -> PlayCountResult:
        for pair in pairs:
            if pair.track.track_id not in edited:
                # The iPod already holds the merged count.
                state.pairs[pair.key] = PairState(
                    pair.remote.item_id,
                    pair.target,
                    pair.target,
                    pair.remote.play_count,
                )
        self._store.save(state)
        pending = [pair for pair in pairs if pair.target != pair.remote.play_count]
        pushed = 0
        stopped = False
        for number, pair in enumerate(pending, 1):
            if cancelled.is_set():
                stopped = True
                break
            progress(f"Updating Jellyfin play counts: {number} / {len(pending)}…")
            try:
                self._client.set_play_count(account, pair.remote.item_id, pair.target)
            except JellyfinError as error:
                issues.append(
                    f"{error} The remaining Jellyfin play counts will be sent next time."
                )
                break
            state.pairs[pair.key] = replace(
                state.pairs[pair.key], jellyfin_seen=pair.target
            )
            pushed += 1
            if pushed % SAVE_INTERVAL == 0:
                self._store.save(state)
        self._store.save(state)
        return replace(
            result, jellyfin_updated=pushed, issues=tuple(issues), cancelled=stopped
        )
