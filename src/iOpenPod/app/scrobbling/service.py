"""Shared background workflow for manual scrobbling and Sync."""

from __future__ import annotations

import time
from threading import Lock
from typing import TYPE_CHECKING, Protocol

from .clients import client_for, wait_between_batches
from .models import LASTFM_MAX_AGE, ScrobbleError, ScrobbleResult, Service
from .queue import capture
from .reporting import adjustment_report, rejection_report
from .timestamps import adjust_lastfm_dates

if TYPE_CHECKING:
    from collections.abc import Callable
    from threading import Event

    from iOpenPod.app.models.device import ActiveIPod

    from .clients import Submitter
    from .credentials import CredentialStore
    from .models import Account, RejectedListen
    from .queue import ScrobbleQueue


class ScrobbleSource(Protocol):
    def scrobble_context(
        self, expected: ActiveIPod
    ) -> tuple[str, Callable[[], None]]: ...


class ScrobbleService:
    def __init__(
        self,
        coordinator: ScrobbleSource,
        queue: ScrobbleQueue,
        credentials: CredentialStore,
        *,
        clients: Callable[[Service], Submitter] = client_for,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._coordinator = coordinator
        self._queue = queue
        self._credentials = credentials
        self._clients = clients
        self._clock = clock
        self._lock = Lock()

    def run(
        self,
        active: ActiveIPod,
        accounts: tuple[Account, ...],
        cancelled: Event,
        progress: Callable[[str], None],
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
                return self._run(active, accounts, cancelled, progress)
        finally:
            self._lock.release()

    def _run(
        self,
        active: ActiveIPod,
        accounts: tuple[Account, ...],
        cancelled: Event,
        progress: Callable[[str], None],
    ) -> ScrobbleResult:
        if cancelled.is_set():
            return ScrobbleResult(cancelled=True)
        device, checkpoint = self._coordinator.scrobble_context(active)
        state = self._queue.load()
        now = int(self._clock())
        skipped = capture(state, device, active.library, accounts, now)
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
        for account in accounts:
            if cancelled.is_set():
                break
            entries = sorted(
                (
                    item
                    for item in state.pending
                    if item.device == device
                    and item.account == account.identity
                    and (
                        account.service is not Service.LASTFM
                        or item.submission.timestamp >= now - LASTFM_MAX_AGE
                    )
                ),
                key=lambda item: (item.submission.timestamp, item.identity),
            )
            if not entries:
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
        return ScrobbleResult(
            accepted,
            pending,
            skipped,
            tuple(issues),
            cancelled.is_set(),
            adjusted=adjusted,
            notices=tuple(notices),
        )
