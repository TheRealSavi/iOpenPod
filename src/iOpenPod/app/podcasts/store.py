"""Filesystem Session adapter for versioned on-device podcast documents."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from iOpenPod.app.podcasts.catalog import reconcile_device_podcasts
from iOpenPod.app.podcasts.documents import (
    PodcastDocumentError,
    decode_history,
    decode_subscriptions,
    encode_history,
    encode_subscriptions,
)
from iOpenPod.app.podcasts.models import (
    ListeningRecord,
    PodcastIssue,
    PodcastIssueCode,
    PodcastSnapshot,
    PodcastSubscription,
)
from storage import DevicePath, FileFingerprint

if TYPE_CHECKING:
    from collections.abc import Iterable

    from iPodDB.library import Track
    from storage import FilesystemSession

PODCAST_DIRECTORY = DevicePath("iPod_Control/iOpenPod/Podcasts")
SUBSCRIPTIONS_PATH = PODCAST_DIRECTORY.joinpath("subscriptions-v1.json")
HISTORY_PATH = PODCAST_DIRECTORY.joinpath("listening-history-v1.json")
_MAX_DOCUMENT_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PodcastStateRevision:
    subscriptions: FileFingerprint | None = None
    history: FileFingerprint | None = None


@dataclass(frozen=True, slots=True)
class LoadedPodcastState:
    snapshot: PodcastSnapshot
    revision: PodcastStateRevision
    requires_persistence: bool = False


class PodcastDeviceStore:
    """Hide document paths, validation, reconciliation, and safe replacement."""

    def load(
        self,
        session: FilesystemSession,
        tracks: Iterable[Track],
        *,
        writable: bool,
    ) -> LoadedPodcastState:
        subscriptions: tuple[PodcastSubscription, ...] = ()
        history: tuple[ListeningRecord, ...] = ()
        issues: list[PodcastIssue] = []
        can_replace = True
        subscription_fingerprint: FileFingerprint | None = None
        history_fingerprint: FileFingerprint | None = None

        if session.exists(SUBSCRIPTIONS_PATH):
            source = session.read_snapshot(
                SUBSCRIPTIONS_PATH, max_bytes=_MAX_DOCUMENT_BYTES
            )
            subscription_fingerprint = source.fingerprint
            try:
                subscriptions = decode_subscriptions(source.data)
            except PodcastDocumentError as error:
                can_replace = False
                issues.append(
                    PodcastIssue(
                        PodcastIssueCode.SUBSCRIPTIONS_UNREADABLE,
                        "The existing Podcast subscriptions file is invalid. "
                        "iOpenPod left it unchanged.",
                        str(error),
                    )
                )
        if session.exists(HISTORY_PATH):
            source = session.read_snapshot(HISTORY_PATH, max_bytes=_MAX_DOCUMENT_BYTES)
            history_fingerprint = source.fingerprint
            try:
                history = decode_history(source.data)
            except PodcastDocumentError as error:
                can_replace = False
                issues.append(
                    PodcastIssue(
                        PodcastIssueCode.HISTORY_UNREADABLE,
                        "The existing Podcast listening-history file is invalid. "
                        "iOpenPod left it unchanged.",
                        str(error),
                    )
                )

        source_snapshot = PodcastSnapshot(
            subscriptions,
            history,
            tuple(issues),
            writable=writable and can_replace,
        )
        reconciled = reconcile_device_podcasts(source_snapshot, tracks)
        source_documents = (
            encode_subscriptions(source_snapshot.subscriptions),
            encode_history(source_snapshot.history),
        )
        current_documents = (
            encode_subscriptions(reconciled.subscriptions),
            encode_history(reconciled.history),
        )
        return LoadedPodcastState(
            reconciled,
            PodcastStateRevision(subscription_fingerprint, history_fingerprint),
            can_replace
            and writable
            and (
                subscription_fingerprint is None
                or history_fingerprint is None
                or source_documents != current_documents
            ),
        )

    def save(
        self,
        session: FilesystemSession,
        state: LoadedPodcastState,
    ) -> LoadedPodcastState:
        """Generation-check and atomically replace each independent document."""

        if not state.snapshot.writable:
            raise ValueError("Podcast state is not safely writable")
        history = encode_history(state.snapshot.history)
        subscriptions = encode_subscriptions(state.snapshot.subscriptions)
        history_fingerprint = self._write_if_changed(
            session,
            HISTORY_PATH,
            history,
            state.revision.history,
        )
        subscription_fingerprint = self._write_if_changed(
            session,
            SUBSCRIPTIONS_PATH,
            subscriptions,
            state.revision.subscriptions,
        )
        flush = session.flush()
        issues = state.snapshot.issues
        if not flush.complete:
            issues = (
                *issues,
                PodcastIssue(
                    PodcastIssueCode.PERSISTENCE_FAILED,
                    "Podcast files were verified, but the operating system did not "
                    "confirm a complete device flush. Safe-eject before unplugging.",
                    flush.detail,
                ),
            )
        return LoadedPodcastState(
            replace(state.snapshot, issues=issues),
            PodcastStateRevision(subscription_fingerprint, history_fingerprint),
        )

    @staticmethod
    def _write_if_changed(
        session: FilesystemSession,
        path: DevicePath,
        payload: bytes,
        expected: FileFingerprint | None,
    ) -> FileFingerprint:
        import hashlib

        digest = hashlib.sha256(payload).hexdigest()
        if (
            expected is not None
            and expected.size == len(payload)
            and expected.sha256 == digest
        ):
            return expected
        result = session.atomic_write(
            path,
            payload,
            expected=expected,
            create_parents=True,
        )
        return result.fingerprint


__all__ = [
    "HISTORY_PATH",
    "PODCAST_DIRECTORY",
    "SUBSCRIPTIONS_PATH",
    "LoadedPodcastState",
    "PodcastDeviceStore",
    "PodcastStateRevision",
]
