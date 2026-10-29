"""Background workflow that reconciles Active iPod and Jellyfin play counts."""

from __future__ import annotations

from collections import Counter
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
from .device_state import (
    MAX_DOCUMENT,
    PLAY_COUNTS_PATH,
    DevicePlayCounts,
    decode_play_counts,
    encode_play_counts,
    play_counts_write,
)
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
    from storage import DevicePath, FileFingerprint, TransactionWrite

    from .models import JellyfinAccount, JellyfinTrack
    from .state import PlayCountStore
    from .token_store import TokenStore


class PlayCountSource(Protocol):
    def scrobble_context(
        self, expected: ActiveIPod
    ) -> tuple[str, Callable[[], None]]: ...

    def prepare_library(
        self,
        request: LibraryPreparationRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: Event,
        *,
        application_writes: tuple[TransactionWrite, ...] = (),
    ) -> LibraryReview: ...

    def save_library(
        self,
        review: LibraryReview,
        expected: ActiveIPod,
        progress: Callable[[WriteProgress], None],
        cancelled: Event,
    ) -> LibrarySaveResult: ...

    def load_application_document(
        self, expected: ActiveIPod, path: DevicePath, max_bytes: int
    ) -> tuple[bytes | None, FileFingerprint | None]: ...

    def save_application_document(
        self,
        expected: ActiveIPod,
        path: DevicePath,
        data: bytes,
        before: FileFingerprint | None,
    ) -> FileFingerprint: ...


@dataclass(frozen=True, slots=True)
class _Pair:
    track_id: int
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
    """Merge play counts through a memory stored on the iPod itself.

    Every Host that syncs the iPod reads the same memory, so plays merged by
    one computer are never added again by another. The memory is written with
    final values in the same Storage transaction as the iPod's play counts, and
    before Jellyfin is updated. Jellyfin updates that fail are recorded with
    Jellyfin's previous count, so they are retried. Any interruption can at
    worst miss a play; it can never count one twice.
    """

    def __init__(
        self,
        coordinator: PlayCountSource,
        tokens: TokenStore,
        *,
        client: JellyfinClient | None = None,
        legacy: PlayCountStore | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._tokens = tokens
        self._client = client or JellyfinClient()
        # Host memory from earlier versions, read once to seed the iPod memory.
        self._legacy = legacy
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

        # An unreadable memory must stop the run before anything changes.
        raw, revision = self._coordinator.load_application_document(
            active, PLAY_COUNTS_PATH, MAX_DOCUMENT
        )
        memory = decode_play_counts(raw) if raw is not None else DevicePlayCounts()
        try:
            progress("Reading the Jellyfin music library…")
            remote = self._client.tracks(account, checkpoint)
            checkpoint()
        except _CancelledError:
            return PlayCountResult(cancelled=True)
        progress("Matching iPod songs with Jellyfin…")
        remembered = memory.accounts.get(account.identity, {})
        pairs, unmatched, ambiguous, issues = self._pairs(
            active, account, device, remembered, remote
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

        # Final values for every pair, assuming every Jellyfin update succeeds.
        present = {
            track.ipod.db_track_id
            for track in active.library.tracks
            if track.ipod is not None
        }
        updated = {
            track_id: pair
            for track_id, pair in remembered.items()
            if track_id in present
        }
        for pair in pairs:
            updated[pair.track_id] = PairState(
                pair.remote.item_id, pair.target, pair.target, pair.target
            )
        memory.accounts[account.identity] = updated
        document = encode_play_counts(memory)
        result = PlayCountResult(
            matched=len(pairs),
            ipod_updated=len(edited),
            unmatched=unmatched,
            ambiguous=ambiguous,
        )

        current = active
        saved_active: ActiveIPod | None = None
        if edited:
            outcome = self._save_ipod(
                active,
                edited,
                play_counts_write(document, revision),
                cancelled,
                progress,
                checkpoint,
            )
            if isinstance(outcome, PlayCountResult):
                return replace(
                    result,
                    ipod_updated=0,
                    issues=(*issues, *outcome.issues),
                    cancelled=outcome.cancelled,
                )
            current = saved_active = outcome
            # The memory now has a new revision; read it when it must change.
            revision = None
            result = replace(result, active=saved_active)
        elif document != raw and (raw is not None or updated):
            try:
                checkpoint()
            except _CancelledError:
                return replace(result, cancelled=True)
            progress("Saving the play count memory on the iPod…")
            revision = self._coordinator.save_application_document(
                active, PLAY_COUNTS_PATH, document, revision
            )
        # After an iPod save the app must always learn about the new Library.
        try:
            return self._push(
                account,
                current,
                memory,
                pairs,
                revision,
                result,
                issues,
                cancelled,
                progress,
                reread=saved_active is not None,
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

    def _legacy_pairs(self) -> dict[str, PairState]:
        if self._legacy is None:
            return {}
        try:
            return self._legacy.load().pairs
        except (JellyfinError, OSError):
            # A first pairing is the safe fallback for unreadable old memory.
            return {}

    def _pairs(
        self,
        active: ActiveIPod,
        account: JellyfinAccount,
        device: str,
        remembered: dict[int, PairState],
        remote: tuple[JellyfinTrack, ...],
    ) -> tuple[list[_Pair], tuple[str, ...], tuple[str, ...], list[str]]:
        index = TrackIndex(remote)
        legacy = self._legacy_pairs()
        unmatched: list[str] = []
        ambiguous: list[str] = []
        issues: list[str] = []
        found: list[tuple[int, PairState | None, Track, JellyfinTrack]] = []
        for track in active.library.tracks:
            if (
                track.media_kind is not MediaKind.MUSIC
                or track.ipod is None
                or track.ipod.db_track_id <= 0
            ):
                continue
            track_id = track.ipod.db_track_id
            previous = remembered.get(track_id) or legacy.get(
                pair_key(account.identity, device, track_id)
            )
            match = index.match(track, previous.item_id if previous else "")
            if match.outcome is MatchOutcome.MATCHED and match.remote is not None:
                found.append((track_id, previous, track, match.remote))
            elif match.outcome is MatchOutcome.AMBIGUOUS:
                ambiguous.append(_label(track))
            else:
                unmatched.append(_label(track))
        # Two iPod songs claiming one Jellyfin item would overwrite each other.
        claims = Counter(item.item_id for _, _, _, item in found)
        pairs: list[_Pair] = []
        for track_id, previous, track, item in found:
            if claims[item.item_id] > 1:
                ambiguous.append(_label(track))
                continue
            baseline = (
                previous
                if previous is not None and previous.item_id == item.item_id
                else None
            )
            target = merged_count(baseline, track.play_count, item.play_count)
            if target > MAX_PLAY_COUNT:
                issues.append(f"{_label(track)}: the play count is too large.")
                continue
            pairs.append(_Pair(track_id, track, item, target))
        return pairs, tuple(unmatched), tuple(ambiguous), issues

    def _save_ipod(
        self,
        active: ActiveIPod,
        edited: dict[int, Track],
        memory: TransactionWrite,
        cancelled: Event,
        progress: Callable[[str], None],
        checkpoint: Callable[[], None],
    ) -> ActiveIPod | PlayCountResult:
        """Commit the play counts and the memory together, or neither."""

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
                LibraryPreparationRequest(snapshot, active, 0, 0),
                forward,
                cancelled,
                application_writes=(memory,),
            )
        except (_CancelledError, PreparationCancelledError):
            return PlayCountResult(cancelled=True)
        if review.result.prepared is None:
            return PlayCountResult(issues=_errors(review.result.issues))
        saved = self._coordinator.save_library(review, active, forward, cancelled)
        if saved.active is None:
            # Storage recovery restores the counts and the memory together.
            return PlayCountResult(
                issues=_errors(saved.issues), cancelled=cancelled.is_set()
            )
        return saved.active

    def _push(
        self,
        account: JellyfinAccount,
        active: ActiveIPod,
        memory: DevicePlayCounts,
        pairs: list[_Pair],
        revision: FileFingerprint | None,
        result: PlayCountResult,
        issues: list[str],
        cancelled: Event,
        progress: Callable[[str], None],
        *,
        reread: bool,
    ) -> PlayCountResult:
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
            pushed += 1
        unsent = pending[pushed:]
        if unsent:
            # Record Jellyfin's real counts so the next run sends them again.
            remembered = memory.accounts[account.identity]
            for pair in unsent:
                remembered[pair.track_id] = replace(
                    remembered[pair.track_id], jellyfin_seen=pair.remote.play_count
                )
            try:
                if reread:
                    _, revision = self._coordinator.load_application_document(
                        active, PLAY_COUNTS_PATH, MAX_DOCUMENT
                    )
                self._coordinator.save_application_document(
                    active, PLAY_COUNTS_PATH, encode_play_counts(memory), revision
                )
            except Exception:
                issues.append(
                    "The iPod could not record which Jellyfin play counts are "
                    "still unsent. Some plays may be missed instead of counted twice."
                )
        return replace(
            result, jellyfin_updated=pushed, issues=tuple(issues), cancelled=stopped
        )
