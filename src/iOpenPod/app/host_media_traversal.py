"""Bounded Host directory traversal when selected folders authorize links.

The ordinary no-link scanner keeps its streaming fast path. A graph needs to
retain filtered listings until all overlapping selections have propagated: a
later selection may authorize more media in an already visited directory.
"""

from __future__ import annotations

import os
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock
from typing import TYPE_CHECKING

from iOpenPod.app.display_text import source_text
from storage import HostPath, StorageError
from storage.host_directory import (
    HostDirectoryEntry,
    HostEntryKind,
    LocalHostDirectory,
    resolve_host_entry,
)
from storage.host_input import HostSelectionResolver

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.host_media_folders import HostMediaFolder, HostMediaType

type DirectoryIdentity = tuple[int, int] | str
type ScanIssue = tuple[HostPath, str]


def path_identity(path: HostPath) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(path)))


@dataclass(slots=True)
class _Directory:
    observation: LocalHostDirectory
    grants: set[int] = field(default_factory=set[int])
    processed: set[int] = field(default_factory=set[int])
    entries: tuple[HostDirectoryEntry, ...] | None = None


@dataclass(frozen=True, slots=True)
class HostTraversal:
    files: tuple[HostDirectoryEntry, ...]
    artwork: dict[str, tuple[HostDirectoryEntry, ...]]
    issues: tuple[ScanIssue, ...]
    listings: int
    entries: int


def walk_linked_folders(
    folders: tuple[HostMediaFolder, ...],
    explicit_paths: frozenset[str],
    *,
    selected: Callable[[Path, frozenset[HostMediaType]], bool],
    cover: Callable[[Path], bool],
    checkpoint: Callable[[], None],
    progress: Callable[[HostPath, int, int], None],
    max_workers: int,
) -> HostTraversal:
    """List each physical directory once, propagating each selection separately.

    Keeping each grant intact prevents one folder's recursion or link permission
    from accidentally widening another folder's selected media types. Repeated
    visits only propagate new grants through retained observations, without I/O.
    """
    states: dict[DirectoryIdentity, _Directory] = {}
    queued: deque[_Directory] = deque()
    applicable: deque[_Directory] = deque()
    files: dict[str, HostDirectoryEntry] = {}
    artwork: dict[str, tuple[HostDirectoryEntry, ...]] = {}
    issues: list[ScanIssue] = []
    skipped_links: dict[str, HostPath] = {}
    targets: dict[str, HostDirectoryEntry | None] = {}
    resolver = HostSelectionResolver()
    listings = 0
    entry_count = 0
    selected_types = frozenset(
        kind for folder in folders for kind in folder.media_types
    )
    recursive = any(folder.recurse for folder in folders)
    stopped = Event()
    lock = Lock()
    live: dict[str, tuple[HostPath, int]] = {}

    def enqueue(directory: LocalHostDirectory, grant: int) -> None:
        identity: DirectoryIdentity = (
            (directory.device, directory.inode)
            if directory.inode
            else path_identity(directory.path)
        )
        state = states.get(identity)
        if state is None:
            state = _Directory(directory)
            states[identity] = state
            queued.append(state)
        if grant not in state.grants:
            state.grants.add(grant)
            if state.entries is not None:
                applicable.append(state)

    for grant, folder in enumerate(folders):
        checkpoint()
        try:
            enqueue(LocalHostDirectory.observe(folder.path), grant)
        except (OSError, StorageError) as error:
            artwork[path_identity(folder.path)] = ()
            issues.append(
                (
                    folder.path,
                    source_text(
                        "The selected folder could not be fully scanned: {error}",
                        error=str(error),
                    ),
                )
            )

    def read(
        state: _Directory,
    ) -> tuple[tuple[HostDirectoryEntry, ...], tuple[ScanIssue, ...]]:
        directory = state.observation
        identity = path_identity(directory.path)
        local_issues: list[ScanIssue] = []
        found = 0

        def check() -> None:
            checkpoint()
            if stopped.is_set():
                raise StorageError("Host directory discovery stopped")

        def report(path: HostPath, error: OSError | StorageError) -> None:
            local_issues.append(
                (
                    path,
                    source_text(
                        "Some folder contents were unavailable; scanning continued: {error}",
                        error=str(error),
                    ),
                )
            )

        def include(name: str) -> bool:
            path = Path(name)
            return (
                selected(path, selected_types)
                or cover(path)
                or (
                    bool(explicit_paths)
                    and path_identity(HostPath(directory.path.path / name))
                    in explicit_paths
                )
            )

        def discovered(entry: HostDirectoryEntry) -> None:
            nonlocal found
            if entry.kind is HostEntryKind.FILE and selected(
                Path(entry.path), selected_types
            ):
                found += 1
            with lock:
                live[identity] = (entry.path, found)

        with lock:
            live[identity] = (directory.path, 0)
        try:
            entries = directory.list_entries(
                checkpoint=check,
                on_issue=report,
                include_file=include,
                include_directories=recursive,
                include_links=True,
                on_entry=discovered,
            )
        except (OSError, StorageError) as error:
            checkpoint()
            report(directory.path, error)
            entries = ()
        return entries, tuple(local_issues)

    def follow(entry: HostDirectoryEntry) -> HostDirectoryEntry | None:
        identity = path_identity(entry.path)
        if identity not in targets:
            checkpoint()
            try:
                targets[identity] = resolve_host_entry(entry.path, resolver=resolver)
            except (OSError, StorageError) as error:
                targets[identity] = None
                issues.append(
                    (
                        entry.path,
                        source_text(
                            "The symbolic link could not be followed: {error}",
                            error=str(error),
                        ),
                    )
                )
        return targets[identity]

    def apply(state: _Directory) -> None:
        assert state.entries is not None
        for grant in sorted(state.grants - state.processed):
            state.processed.add(grant)
            folder = folders[grant]
            for original in state.entries:
                checkpoint()
                entry = original
                if entry.kind is HostEntryKind.LINK_OR_REPARSE_POINT:
                    if not folder.follow_symlinks:
                        identity = path_identity(entry.path)
                        skipped_links[identity] = entry.path
                        continue
                    target = follow(entry)
                    if target is None:
                        continue
                    entry = target
                if entry.directory is not None:
                    if folder.recurse:
                        enqueue(entry.directory, grant)
                elif entry.file is not None and (
                    selected(Path(entry.path), folder.media_types)
                    or path_identity(entry.path) in explicit_paths
                ):
                    files[path_identity(entry.path)] = entry

    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="host-media-links"
    ) as executor:
        pending: dict[
            Future[tuple[tuple[HostDirectoryEntry, ...], tuple[ScanIssue, ...]]],
            _Directory,
        ] = {}
        try:
            while queued or applicable or pending:
                checkpoint()
                while applicable:
                    apply(applicable.popleft())
                while queued and len(pending) < max_workers * 2:
                    state = queued.popleft()
                    pending[executor.submit(read, state)] = state
                with lock:
                    active = tuple(live.values())
                if active:
                    progress(
                        active[-1][0],
                        listings + len(active),
                        len(files) + sum(count for _, count in active),
                    )
                if not pending:
                    continue
                finished, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
                for future in finished:
                    checkpoint()
                    state = pending.pop(future)
                    entries, local_issues = future.result()
                    identity = path_identity(state.observation.path)
                    with lock:
                        live.pop(identity, None)
                    state.entries = entries
                    listings += 1
                    entry_count += len(entries)
                    issues.extend(local_issues)
                    artwork[identity] = tuple(
                        entry
                        for entry in entries
                        if entry.file is not None and cover(Path(entry.path))
                    )
                    applicable.append(state)
                    progress(state.observation.path, listings, len(files))
        finally:
            stopped.set()
            for future in pending:
                future.cancel()
    issues.extend(
        (
            path,
            source_text(
                "Symbolic link skipped because Follow symbolic links is disabled."
            ),
        )
        for identity, path in skipped_links.items()
        if identity not in targets
    )
    return HostTraversal(
        tuple(files.values()), artwork, tuple(issues), listings, entry_count
    )
