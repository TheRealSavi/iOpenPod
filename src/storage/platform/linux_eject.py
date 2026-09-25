"""Linux safe removal through the UDisks2 system D-Bus service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from storage.errors import EjectError, UnsupportedStorageOperationError
from storage.models import EjectResult

_DEVICE_BUSY = "org.freedesktop.UDisks2.Error.DeviceBusy"
_NOT_AUTHORIZED = {
    "org.freedesktop.UDisks2.Error.NotAuthorized",
    "org.freedesktop.UDisks2.Error.NotAuthorizedCanObtain",
    "org.freedesktop.UDisks2.Error.NotAuthorizedDismissed",
}


@dataclass(frozen=True, slots=True)
class UDisksTarget:
    drive: str
    mounted_filesystems: tuple[str, ...]


class UDisksError(RuntimeError):
    def __init__(self, name: str, detail: str) -> None:
        super().__init__(detail)
        self.name = name
        self.detail = detail


class _UDisksClient(Protocol):
    def target_for_device(self, device_path: str) -> UDisksTarget: ...

    def unmount(self, filesystem: str) -> None: ...

    def power_off(self, drive: str) -> None: ...


class LinuxDeviceEjector:
    """Unmount all Volumes on a UDisks Drive, then request USB power-off."""

    def __init__(self, client: _UDisksClient | None = None) -> None:
        self._client = client

    def eject(self, device_path: str) -> EjectResult:
        client = self._client or _QtUDisksClient()
        try:
            target = client.target_for_device(device_path)
        except UDisksError as error:
            raise _target_error(error) from error

        unmounted = False
        for filesystem in target.mounted_filesystems:
            try:
                client.unmount(filesystem)
            except UDisksError as error:
                raise EjectError(
                    _operation_error(
                        error,
                        "Linux could not unmount every iPod Volume",
                    ),
                    volume_unmounted=unmounted,
                ) from error
            unmounted = True

        try:
            client.power_off(target.drive)
        except UDisksError as error:
            raise EjectError(
                _operation_error(
                    error,
                    "Every iPod Volume was unmounted, but Linux did not "
                    "confirm drive power-off",
                ),
                volume_unmounted=True,
            ) from error
        return EjectResult(
            "Linux UDisks confirmed that the iPod is unmounted and powered off."
        )


class _QtUDisksClient:
    _SERVICE = "org.freedesktop.UDisks2"
    _ROOT = "/org/freedesktop/UDisks2"
    _MANAGER = "org.freedesktop.UDisks2.Manager"
    _BLOCK = "org.freedesktop.UDisks2.Block"
    _FILESYSTEM = "org.freedesktop.UDisks2.Filesystem"
    _DRIVE = "org.freedesktop.UDisks2.Drive"
    _PROPERTIES = "org.freedesktop.DBus.Properties"

    def __init__(self) -> None:
        from PySide6.QtDBus import QDBusConnection

        self._connection = QDBusConnection.systemBus()
        if not self._connection.isConnected():
            raise UnsupportedStorageOperationError(
                "The Linux system D-Bus is unavailable. Use the desktop's "
                "Safely Remove or Power Off action."
            )

    def target_for_device(self, device_path: str) -> UDisksTarget:
        resolved = self._call(
            self._ROOT + "/Manager",
            self._MANAGER,
            "ResolveDevice",
            _variant_map({"path": device_path}),
            _variant_map({}),
        )
        blocks = _object_paths(_first_argument(resolved))
        if len(blocks) != 1:
            raise UDisksError(
                "org.freedesktop.UDisks2.Error.NotFound",
                "UDisks did not resolve the mounted Volume to one exact block device.",
            )
        selected_block = blocks[0]
        drive = _object_path(self._property(selected_block, self._BLOCK, "Drive"))
        if not drive or drive == "/":
            raise UDisksError(
                "org.freedesktop.UDisks2.Error.NotSupported",
                "UDisks did not associate the Volume with a physical Drive.",
            )
        if self._property(drive, self._DRIVE, "CanPowerOff") is not True:
            raise UDisksError(
                "org.freedesktop.UDisks2.Error.NotSupported",
                "UDisks reports that this Drive cannot be safely powered off.",
            )
        self._require_no_drive_siblings(drive)

        listed = self._call(
            self._ROOT + "/Manager",
            self._MANAGER,
            "GetBlockDevices",
            _variant_map({}),
        )
        all_blocks = _object_paths(_first_argument(listed))
        mounted: list[str] = []
        seen: set[str] = set()
        for block in (selected_block, *all_blocks):
            if block in seen:
                continue
            seen.add(block)
            if _object_path(self._property(block, self._BLOCK, "Drive")) != drive:
                continue
            try:
                mount_points = self._property(block, self._FILESYSTEM, "MountPoints")
            except UDisksError as error:
                if _missing_interface(error):
                    continue
                raise
            if _has_mount_points(mount_points):
                mounted.append(block)
        if selected_block not in mounted:
            mounted.insert(0, selected_block)
        return UDisksTarget(drive=drive, mounted_filesystems=tuple(mounted))

    def unmount(self, filesystem: str) -> None:
        self._call(
            filesystem,
            self._FILESYSTEM,
            "Unmount",
            _variant_map({}),
            timeout_ms=75_000,
        )

    def power_off(self, drive: str) -> None:
        self._call(
            drive,
            self._DRIVE,
            "PowerOff",
            _variant_map({}),
            timeout_ms=75_000,
        )

    def _require_no_drive_siblings(self, drive: str) -> None:
        sibling_id = self._property(drive, self._DRIVE, "SiblingId")
        if not isinstance(sibling_id, str) or not sibling_id:
            return
        try:
            listed = self._call(
                self._ROOT + "/Manager",
                self._MANAGER,
                "GetDrives",
                _variant_map({}),
            )
        except UDisksError as error:
            if error.name.endswith("UnknownMethod"):
                raise UDisksError(
                    "org.freedesktop.UDisks2.Error.NotSupported",
                    "UDisks cannot verify whether powering off this Drive would "
                    "also affect other media.",
                ) from error
            raise
        for candidate in _object_paths(_first_argument(listed)):
            if candidate != drive and (
                self._property(candidate, self._DRIVE, "SiblingId") == sibling_id
            ):
                raise UDisksError(
                    "org.freedesktop.UDisks2.Error.NotSupported",
                    "Powering off this Drive may also affect other media in the "
                    "same device. Use the desktop's Safely Remove action.",
                )

    def _property(self, path: str, interface: str, name: str) -> object:
        reply = self._call(path, self._PROPERTIES, "Get", interface, name)
        return _unwrap(_first_argument(reply))

    def _call(
        self,
        path: str,
        interface: str,
        method: str,
        *arguments: object,
        timeout_ms: int = 30_000,
    ) -> object:
        from PySide6.QtDBus import QDBus, QDBusMessage

        message = QDBusMessage.createMethodCall(
            self._SERVICE,
            path,
            interface,
            method,
        )
        message.setArguments(list(arguments))
        reply = self._connection.call(
            message,
            QDBus.CallMode.Block,
            timeout_ms,
        )
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            raise UDisksError(reply.errorName(), reply.errorMessage())
        return reply


def _variant_map(values: dict[str, object]) -> dict[str, object]:
    """Return the PySide representation of a D-Bus ``a{sv}`` map."""

    # PySide converts a Python dict to Qt's QVariantMap, whose D-Bus signature is
    # a{sv}. Building a QDBusArgument manually instead makes the Python binding
    # marshal an empty structure and causes UDisks to reject the method call.
    return dict(values)


def _first_argument(message: object) -> object:
    arguments_method = getattr(message, "arguments", None)
    if not callable(arguments_method):
        raise UDisksError(
            "org.freedesktop.DBus.Error.InvalidSignature",
            "UDisks returned an invalid response.",
        )
    raw_arguments: object = arguments_method()
    if not isinstance(raw_arguments, list):
        raise UDisksError(
            "org.freedesktop.DBus.Error.InvalidSignature",
            "UDisks returned invalid response arguments.",
        )
    arguments = cast("list[object]", raw_arguments)
    if not arguments:
        raise UDisksError(
            "org.freedesktop.DBus.Error.InvalidSignature",
            "UDisks returned an empty response.",
        )
    return arguments[0]


def _unwrap(value: object) -> object:
    from PySide6.QtDBus import QDBusVariant

    if isinstance(value, QDBusVariant):
        return value.variant()
    return value


def _object_path(value: object) -> str | None:
    from PySide6.QtDBus import QDBusObjectPath

    value = _unwrap(value)
    if isinstance(value, QDBusObjectPath):
        return value.path()
    if isinstance(value, str) and value.startswith("/"):
        return value
    return None


def _object_paths(value: object) -> tuple[str, ...]:
    return tuple(
        path for item in _array_items(value) if (path := _object_path(item)) is not None
    )


def _has_mount_points(value: object) -> bool:
    return bool(_array_items(value))


def _array_items(value: object) -> tuple[object, ...]:
    from PySide6.QtDBus import QDBusArgument

    value = _unwrap(value)
    if isinstance(value, QDBusArgument):
        # Array replies such as ``ao`` and ``aay`` remain QDBusArgument values in
        # PySide. Calling asVariant() on the container returns another container;
        # enter the array first so each call consumes one element instead.
        value.beginArray()
        items: list[object] = []
        while not value.atEnd():
            items.append(_unwrap(value.asVariant()))
        # PySide 6.11 selects QDBusArgument's write-mode endArray overload for a
        # read-only reply and emits a spurious warning. This top-level reader is
        # discarded here, so it does not need to be repositioned after the array.
        return tuple(items)
    if isinstance(value, list | tuple):
        return tuple(cast("list[object] | tuple[object, ...]", value))
    return ()


def _missing_interface(error: UDisksError) -> bool:
    return error.name.endswith(("UnknownInterface", "UnknownProperty", "InvalidArgs"))


def _target_error(error: UDisksError) -> Exception:
    if error.name.endswith(("ServiceUnknown", "NameHasNoOwner")):
        return UnsupportedStorageOperationError(
            "The UDisks2 service is unavailable. Use the desktop's Safely Remove "
            "or Power Off action."
        )
    if error.name.endswith("NotSupported"):
        return UnsupportedStorageOperationError(error.detail)
    return EjectError(_operation_error(error, "Linux could not prepare safe removal"))


def _operation_error(error: UDisksError, prefix: str) -> str:
    if error.name == _DEVICE_BUSY:
        return (
            f"{prefix} because files are still open. Close apps and file-manager "
            "windows using the iPod, then try again. The iPod was not safely ejected."
        )
    if error.name in _NOT_AUTHORIZED:
        return (
            f"{prefix} because authorization was denied or cancelled. The iPod "
            "was not safely ejected."
        )
    detail = error.detail.strip() or error.name
    return f"{prefix}: {detail}. The iPod was not safely ejected."


__all__ = ["LinuxDeviceEjector", "UDisksError", "UDisksTarget"]
