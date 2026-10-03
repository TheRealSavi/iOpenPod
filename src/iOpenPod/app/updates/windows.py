"""UI-thread Store adapter; Qt polls WinRT completion without blocking its loop."""

from __future__ import annotations

import ctypes
import math
from importlib import import_module
from queue import Empty, SimpleQueue
from threading import get_ident
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

from .backend import (
    InstallChannel,
    UpdateOutcome,
    UpdateProgress,
    UpdateProvider,
    UpdateResult,
)


class NativeOperation(Protocol):
    @property
    def status(self) -> int: ...

    def get_results(self) -> object: ...

    def cancel(self) -> None: ...

    def close(self) -> None: ...


class NativeProgress(Protocol):
    package_family_name: str
    package_download_progress: float
    package_update_state: int


class NativeInstallOperation(NativeOperation, Protocol):
    progress: Callable[[object, NativeProgress], None]


class NativeResult(Protocol):
    overall_state: int
    store_package_update_statuses: Iterable[NativeProgress]


class NativeContext(Protocol):
    def get_app_and_optional_store_package_updates_async(self) -> NativeOperation: ...

    def request_download_and_install_store_package_updates_async(
        self, updates: Iterable[object]
    ) -> NativeInstallOperation: ...


def _state_detail(state: int) -> str:
    return {
        0: "Pending",
        1: "Downloading",
        2: "Installing",
        3: "Completed",
        4: "Canceled",
        5: "Store error",
        6: "Connect the computer to power and try again",
        7: "Wi-Fi is recommended; check your network and try again",
        8: "Connect to Wi-Fi and try again",
    }.get(state, f"Unknown Store state ({state})")


def install_result(value: NativeResult) -> UpdateResult:
    """Both the overall result and every package must report completion."""
    states = tuple(
        item.package_update_state for item in value.store_package_update_statuses
    )
    if value.overall_state == 3 and all(state == 3 for state in states):
        return UpdateResult(UpdateOutcome.COMPLETED)
    if value.overall_state == 4:
        return UpdateResult(UpdateOutcome.CANCELED)
    failures = tuple(state for state in states if state != 3)
    detail = "; ".join(dict.fromkeys(_state_detail(state) for state in failures))
    return UpdateResult(
        UpdateOutcome.FAILED, detail or _state_detail(value.overall_state)
    )


class StoreBackend:
    def download(self) -> None:
        raise RuntimeError("The Store owns download and installation together")

    def complete_handoff(self) -> None:
        raise RuntimeError("The Store owns application restart")

    def __init__(
        self, context: NativeContext, release_owner: Callable[[], None] = lambda: None
    ) -> None:
        self._context = context
        self._release_owner = release_owner
        self._thread = get_ident()
        self._operation: NativeOperation | None = None
        self._installing = False
        self._closed = False
        self._updates: tuple[object, ...] = ()
        self._progress: SimpleQueue[UpdateProgress] = SimpleQueue()

    def _ready(self) -> None:
        if get_ident() != self._thread:
            raise RuntimeError("Store updates must run on their owning GUI thread")
        if self._closed or self._operation is not None:
            raise RuntimeError("The Store updater is closed or already busy")

    def check(self) -> None:
        self._ready()
        self._updates = ()
        self._installing = False
        self._operation = (
            self._context.get_app_and_optional_store_package_updates_async()
        )

    def install(self) -> None:
        self._ready()
        if not self._updates:
            raise RuntimeError("Check for Store updates before installing")
        self._installing = True
        operation = (
            self._context.request_download_and_install_store_package_updates_async(
                self._updates
            )
        )
        self._operation = operation
        queue = self._progress

        def progress(_sender: object, value: NativeProgress) -> None:
            # The native callback may run on another thread. Capture only the queue,
            # not this adapter or the operation; never touch a Qt object here.
            fraction = value.package_download_progress
            if math.isfinite(fraction):
                queue.put(
                    UpdateProgress(
                        value.package_family_name,
                        max(0.0, min(1.0, fraction)),
                        value.package_update_state == 2,
                    )
                )

        operation.progress = progress

    def poll(self) -> UpdateResult | UpdateProgress | None:
        if get_ident() != self._thread:
            raise RuntimeError("Poll Store updates on their owning GUI thread")
        operation = self._operation
        if self._closed or operation is None:
            return None
        latest = None
        while True:
            try:
                latest = self._progress.get_nowait()
            except Empty:
                break
        if operation.status == 0:  # AsyncStatus.STARTED
            return latest
        self._operation = None
        try:
            if operation.status == 2:  # AsyncStatus.CANCELED
                return UpdateResult(UpdateOutcome.CANCELED)
            # get_results is nonblocking only after the operation is terminal.
            result = operation.get_results()
            if self._installing:
                return install_result(cast("NativeResult", result))
            self._updates = tuple(cast("Iterable[object]", result))
            return UpdateResult(
                UpdateOutcome.AVAILABLE if self._updates else UpdateOutcome.CURRENT
            )
        finally:
            operation.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        operation, self._operation = self._operation, None
        try:
            if operation is not None:
                operation.cancel()
                # A running operation cannot be Close()d. Releasing it after
                # Cancel() is safe; its callback owns only an isolated queue.
                if operation.status != 0:
                    operation.close()
        finally:
            self._updates = ()
            self._release_owner()


def detect_channel() -> InstallChannel:
    # Resolve Windows-only ctypes exports lazily so this module remains importable
    # and type-checkable on the other supported Hosts.
    kernel = vars(ctypes)["WinDLL"]("kernel32", use_last_error=True)
    size = ctypes.c_uint32()
    result = kernel.GetCurrentPackageFullName(ctypes.byref(size), None)
    if result == 15700:  # APPMODEL_ERROR_NO_PACKAGE
        return InstallChannel.UNPACKAGED
    if result != 122:  # ERROR_INSUFFICIENT_BUFFER proves package identity
        raise OSError(result, "Could not determine Windows package identity")
    model = import_module("winrt.windows.applicationmodel")
    return (
        InstallChannel.MICROSOFT_STORE
        if model.Package.current.signature_kind == model.PackageSignatureKind.STORE
        else InstallChannel.WINDOWS_PACKAGE
    )


def _claim_owner() -> Callable[[], None]:
    """One update owner across application processes in this Windows session."""
    kernel = vars(ctypes)["WinDLL"]("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, False, "Local\\iOpenPod.StoreUpdateOwner")
    error = vars(ctypes)["get_last_error"]()
    if not handle:
        raise vars(ctypes)["WinError"](error)
    if error == 183:  # ERROR_ALREADY_EXISTS
        kernel.CloseHandle(handle)
        raise RuntimeError("Another iOpenPod window owns Microsoft Store updates")

    def release() -> None:
        kernel.CloseHandle(handle)

    return release


def create_store_provider(window_id: int) -> UpdateProvider:
    channel = detect_channel()
    if channel is not InstallChannel.MICROSOFT_STORE:
        return UpdateProvider(channel)
    if window_id <= 0:
        raise ValueError("Store updates require a live owner window")
    release = _claim_owner()
    try:
        store = import_module("winrt.windows.services.store")
        interop = import_module("winrt.runtime.interop")
        context = store.StoreContext.get_default()
        interop.initialize_with_window(context, window_id)
        return UpdateProvider(
            channel,
            StoreBackend(cast("NativeContext", context), release),
            "Microsoft Store",
        )
    except Exception:
        release()
        raise
