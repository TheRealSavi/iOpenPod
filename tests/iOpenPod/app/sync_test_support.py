"""Shared Sync execution doubles and durable transaction-journal fixtures."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from threading import Event
from typing import TYPE_CHECKING

import pytest

from iOpenPod.app.library_write import WriteProgress
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionResult,
    SyncExecutionStatus,
)
from storage import (
    AccessMode,
    DevicePath,
    FileContent,
    RecoverableWriteError,
    StorageTransaction,
    TransactionProgress,
    TransactionState,
    TransactionWrite,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.iOpenPod.app.services.test_library_resources import Device

DATABASE_PATH = DevicePath("iPod_Control/iTunes/iTunesDB")
PARTIAL_DATABASE_BYTES = b"partially published database"


class SyncExecutionStub:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self.request: SyncExecutionRequest | None = None
        self.crash = False
        self.outcome: SyncExecutionResult | None = None

    def execute(
        self,
        request: SyncExecutionRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: Event,
    ) -> SyncExecutionResult:
        self.request = request
        self.entered.set()
        progress(WriteProgress("sync.prepare", "Preparing on Host"))
        assert self.release.wait(5)
        if self.outcome is not None:
            return self.outcome
        if self.crash:
            raise RuntimeError("fixture failure")
        if cancelled.is_set():
            return SyncExecutionResult(SyncExecutionStatus.CANCELLED)
        return SyncExecutionResult(
            SyncExecutionStatus.SUCCESS,
            active=replace(
                request.source,
                library=replace(request.source.library, device_name="Synced"),
            ),
            completed=request.plan.items,
        )


def create_transaction_journal(device: Device, state: TransactionState) -> str:
    """Leave an actual Storage journal at a selected durable transaction boundary."""
    with device.storage.open_session(
        device.storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        plan = StorageTransaction(
            (
                TransactionWrite(
                    DATABASE_PATH,
                    PARTIAL_DATABASE_BYTES,
                    FileContent(
                        len(PARTIAL_DATABASE_BYTES),
                        hashlib.sha256(PARTIAL_DATABASE_BYTES).hexdigest(),
                    ),
                    session.fingerprint(DATABASE_PATH),
                ),
            )
        )

        def interrupt(event: TransactionProgress) -> None:
            if event.state is state and (
                state is not TransactionState.PUBLISHING or event.completed == 1
            ):
                raise InterruptedError("Simulated application interruption")

        if state is TransactionState.COMMITTED:
            result = session.execute_transaction(plan)
            return str(result.recovery.journal_path)
        if state is TransactionState.RESTORED:
            result = session.execute_transaction(plan)
            return str(
                session.restore_transaction(result.recovery).recovery.journal_path
            )
        with pytest.raises(RecoverableWriteError) as caught:
            session.execute_transaction(plan, progress=interrupt)
        return caught.value.recovery_path
