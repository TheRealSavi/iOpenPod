"""Versioned iPod settings documents, accessed only through Storage sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from iOpenPod.app.display_text import source_text
from storage import DevicePath, FileFingerprint, StorageError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from storage import FilesystemSession

SETTINGS_PATH = DevicePath("iPod_Control/iOpenPod/settings-v2.json")
_MAX_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class DeviceSettings:
    """Captured overrides and the exact file revision they may replace."""

    values: tuple[tuple[str, object], ...] = ()
    revision: FileFingerprint | None = None
    writable: bool = False
    message: str = ""


def load_device_settings(session: FilesystemSession) -> DeviceSettings:
    writable = session.mounted_volume.volume.capabilities.safe_for_writes
    try:
        if not session.exists(SETTINGS_PATH):
            return DeviceSettings(writable=writable)
        source = session.read_snapshot(SETTINGS_PATH, max_bytes=_MAX_BYTES)
        document: object = json.loads(source.data)
        if not isinstance(document, dict):
            raise ValueError("Expected a settings object")
        payload = cast("dict[str, object]", document)
        if type(payload.get("version")) is not int or payload["version"] != 1:
            raise ValueError("Unsupported iPod settings version")
        values = payload.get("overrides")
        if not isinstance(values, dict):
            raise ValueError("Expected an overrides object")
        return DeviceSettings(
            tuple(cast("dict[str, object]", values).items()),
            source.fingerprint,
            writable,
        )
    except (ValueError, StorageError) as error:
        return DeviceSettings(
            message=source_text(
                "iPod settings could not be read. Reload the iPod to try again. {detail}",
                detail=str(error),
            )
        )


def save_device_settings(
    session: FilesystemSession,
    previous: DeviceSettings,
    values: Mapping[str, object],
) -> DeviceSettings:
    """Preserve unknown keys and reject stale, unreadable, or read-only state."""
    if not previous.writable:
        raise ValueError("iPod settings are read-only")
    data = (
        json.dumps(
            {"version": 1, "overrides": dict(values)},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if len(data) > _MAX_BYTES:
        raise ValueError("iPod settings exceed the document size limit")
    result = session.atomic_write(
        SETTINGS_PATH, data, expected=previous.revision, create_parents=True
    )
    flush = session.flush()
    return replace(
        previous,
        values=tuple(values.items()),
        revision=result.fingerprint,
        message=(
            ""
            if flush.complete
            else source_text(
                "Settings were verified, but the device flush was incomplete. "
                "Safe-eject the iPod before unplugging."
            )
        ),
    )
