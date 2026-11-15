"""Shared background workflow for manual scrobbling and Sync."""

from __future__ import annotations

from dataclasses import replace
from threading import Lock
from typing import TYPE_CHECKING, Protocol

from whenever import Instant

from iOpenPod.app.media.recording_id import embedded_recording_mbid
from iOpenPod.app.media.tag_reader import read_embedded_media
from iOpenPod.app.playback.backend import PlaybackSourceError

from .clients import LastFmClient, ListenBrainzClient, client_for, wait_between_batches
from .feedback import FeedbackCancelledError, capture_feedback
from .models import LASTFM_MAX_AGE, ScrobbleError, ScrobbleResult, Service
from .queue import MIN_TIMESTAMP, capture
from .reporting import adjustment_report, rejection_report
from .timestamps import adjust_lastfm_dates

if TYPE_CHECKING:
    from collections.abc import Callable
    from threading import Event

    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.playback.backend import PlaybackSourceProvider
    from iPodDB.library import Track

    from .clients import Submitter
    from .credentials import CredentialStore
    from .models import Account, RejectedListen
    from .queue import ScrobbleQueue


class ScrobbleSource(Protocol):
    def scrobble_context(
        self, expected: ActiveIPod
    ) -> tuple[str, Callable[[], None]]: ...


def _unix_now() -> float:
    """Keep the injected Unix-clock boundary; delivery dates use whole seconds."""
    return float(Instant.now().timestamp())


class ScrobbleService:
    def __init__(
        self,
        coordinator: ScrobbleSource,
        queue: ScrobbleQueue,
        credentials: CredentialStore,
        *,
        clients: Callable[[Service], Submitter] = client_for,
        clock: Callable[[], float] = _unix_now,
        media: PlaybackSourceProvider | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._queue = queue
        self._credentials = credentials
        self._clients = clients
        self._clock = clock
        self._media = media
        self._lock = Lock()

    def run(
        self,
        active: ActiveIPod,
        accounts: tuple[Account, ...],
        cancelled: Event,
        progress: Callable[[str], None],
        *,
        ratings: bool = False,
    ) -> ScrobbleResult:
        if not accounts:
            return ScrobbleResult(
                issues=(
                    "Connect Last.fm or ListenBrainz in Settings → Sync to scrobble.",
                )
            )
        if not self._lock.acquire(blocking=False):
            raise ScrobbleError("Scrobbling is already running.")
        try:
            with self._queue.lease():
                return self._run(active, accounts, cancelled, progress, ratings=ratings)
        finally:
            self._lock.release()

    def _run(
        self,
        active: ActiveIPod,
        accounts: tuple[Account, ...],
        cancelled: Event,
        progress: Callable[[str], None],
        *,
        ratings: bool,
    ) -> ScrobbleResult:
        if cancelled.is_set():
            return ScrobbleResult(cancelled=True)
        device, checkpoint = self._coordinator.scrobble_context(active)
        state = self._queue.load()
        now = int(self._clock())
        skipped = capture(state, device, active.library, accounts, now)
        if ratings:
            progress("Capturing iPod star ratings…")
            capture_feedback(
                state,
                device,
                active.library,
                accounts,
                lambda track: self._recording_mbid(track, cancelled, checkpoint),
                cancelled,
            )
        issues: list[str] = []
        notices: list[str] = []
        adjusted = 0
        for account in accounts:
            deferred = adjust_lastfm_dates(state, device, account, now)
            if deferred:
                issues.append(
                    f"Last.fm: {deferred} old listens remain pending until more distinct "
                    "timestamps are available today. Retry later."
                )
            changed = [
                item
                for item in state.pending
                if item.device == device
                and item.account == account.identity
                and item.submission_timestamp is not None
            ]
            if changed:
                adjusted += len(changed)
                notices.append(adjustment_report(account, changed))
        # Failure here must stop Sync before it can remove the source Tracks.
        # Persist chosen submission dates before any request, including uncertain replies.
        self._queue.save(state)
        accepted = 0
        feedback_accepted = 0
        feedback_skipped = 0
        for account in accounts:
            if cancelled.is_set():
                break
            entries = sorted(
                (
                    item
                    for item in state.pending
                    if item.device == device
                    and item.account == account.identity
                    and MIN_TIMESTAMP <= item.submission.timestamp <= now
                    and (
                        account.service is not Service.LASTFM
                        or item.submission.timestamp >= now - LASTFM_MAX_AGE
                    )
                ),
                key=lambda item: (item.submission.timestamp, item.identity),
            )
            feedback = [
                item
                for item in state.feedback.values()
                if ratings
                and item.pending
                and item.device == device
                and item.account == account.identity
            ]
            if not entries and not feedback:
                continue
            rejections: list[RejectedListen] = []
            try:
                credentials = self._credentials.load(account.service)
                if (
                    credentials is None
                    or credentials.username.casefold() != account.username.casefold()
                ):
                    raise ScrobbleError("Reconnect this account in Settings → Sync.")
                client = self._clients(account.service)
                for offset in range(0, len(entries), client.batch_size):
                    if cancelled.is_set():
                        break
                    checkpoint()
                    batch = entries[offset : offset + client.batch_size]
                    progress(
                        f"Scrobbling to {account.service.label}: {offset} / {len(entries)}…"
                    )
                    result = client.submit(
                        tuple(item.submission for item in batch), credentials
                    )
                    if len(result.accepted) != len(batch):
                        raise ScrobbleError(
                            "The service returned incomplete acknowledgements."
                        )
                    received = {
                        item.identity
                        for item, ok in zip(batch, result.accepted, strict=True)
                        if ok
                    }
                    state.pending = [
                        item for item in state.pending if item.identity not in received
                    ]
                    # Even cancellation/disconnect after a response must retain receipts.
                    self._queue.save(state)
                    accepted += len(received)
                    rejections.extend(result.rejections)
                    if offset + len(batch) < len(entries) and not wait_between_batches(
                        client, cancelled, checkpoint
                    ):
                        break
                if feedback and not isinstance(
                    client, (LastFmClient, ListenBrainzClient)
                ):
                    raise ScrobbleError("This client does not support rating feedback.")
                if isinstance(client, (LastFmClient, ListenBrainzClient)):
                    for index, item in enumerate(feedback):
                        if not wait_between_batches(client, cancelled, checkpoint):
                            break
                        checkpoint()
                        progress(
                            f"Sending {account.service.label} ratings: {index} / {len(feedback)}…"
                        )
                        if (
                            isinstance(client, ListenBrainzClient)
                            and not item.recording_mbid
                        ):
                            mbid = client.lookup_recording(
                                item.artist, item.title, credentials
                            )
                            if not mbid:
                                state.feedback[item.identity] = replace(
                                    item, pending=False
                                )
                                self._queue.save(state)
                                feedback_skipped += 1
                                continue
                            item = replace(item, recording_mbid=mbid)
                            state.feedback[item.identity] = item
                            # Keep the resolved identity across failed or uncertain POSTs.
                            self._queue.save(state)
                            if not wait_between_batches(client, cancelled, checkpoint):
                                break
                            checkpoint()
                        if isinstance(client, LastFmClient):
                            client.set_loved(
                                item.artist, item.title, item.score == 1, credentials
                            )
                        else:
                            client.submit_feedback(
                                item.recording_mbid, item.score, credentials
                            )
                        state.feedback[item.identity] = replace(item, pending=False)
                        self._queue.save(state)
                        feedback_accepted += 1
            except ScrobbleError as error:
                issues.append(f"{account.service.label}: {error}")
            if rejections:
                issues.append(
                    rejection_report(
                        account,
                        rejections,
                        now=now,
                        adjusted=any(
                            item.submission_timestamp is not None for item in entries
                        ),
                    )
                )
        targets = {account.identity for account in accounts}
        pending = sum(
            item.device == device and item.account in targets for item in state.pending
        )
        feedback_pending = sum(
            ratings
            and item.pending
            and item.device == device
            and item.account in targets
            for item in state.feedback.values()
        )
        if feedback_skipped:
            issues.append(
                f"ListenBrainz: {feedback_skipped} ratings skipped because no recording matched."
            )
        return ScrobbleResult(
            accepted,
            pending,
            skipped,
            tuple(issues),
            cancelled.is_set(),
            adjusted=adjusted,
            notices=tuple(notices),
            feedback_accepted=feedback_accepted,
            feedback_pending=feedback_pending,
            feedback_skipped=feedback_skipped,
        )

    def _recording_mbid(
        self, track: Track, cancelled: Event, checkpoint: Callable[[], None]
    ) -> str:
        def check() -> None:
            if cancelled.is_set():
                raise FeedbackCancelledError
            checkpoint()

        check()
        if self._media is None:
            return ""
        try:
            source = self._media.open_playback_source(track)
            parsed = read_embedded_media(source, checkpoint=check)
        except (PlaybackSourceError, ValueError, OSError):
            # Optional tag failures allow lookup; an invalid session still stops work.
            check()
            return ""
        check()
        return embedded_recording_mbid(parsed)
