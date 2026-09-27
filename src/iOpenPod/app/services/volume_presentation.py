"""Portable desktop presentation derived from the saved iPod name and model."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageOps

from storage import (
    DevicePath,
    FileContent,
    FilePrecondition,
    StorageError,
    TransactionWrite,
)

if TYPE_CHECKING:
    from storage import FilesystemSession

_IMAGE_DIRECTORY = Path(__file__).parents[2] / "assets" / "ipod_images"
_ICON = "iPod_Control/iOpenPod/volume-icon"
_MAX_FILE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class VolumePresentation:
    files: tuple[FilePrecondition, ...]
    writes: tuple[TransactionWrite, ...]


@lru_cache(maxsize=32)
def _icons(product_image: str) -> tuple[tuple[str, bytes], ...]:
    if Path(product_image).name != product_image or not product_image.endswith(".png"):
        raise ValueError("Invalid packaged iPod image name")
    source_path = _IMAGE_DIRECTORY / product_image
    if not source_path.is_file():
        source_path = _IMAGE_DIRECTORY / "iPodGeneric.png"
    with Image.open(source_path) as source:
        scaled = ImageOps.contain(source.convert("RGBA"), (512, 512))
        canvas = Image.new("RGBA", (512, 512))
        canvas.paste(scaled, ((512 - scaled.width) // 2, (512 - scaled.height) // 2))
    files: list[tuple[str, bytes]] = []
    for path, format_name in (
        (_ICON + ".png", "PNG"),
        (_ICON + ".ico", "ICO"),
        (".VolumeIcon.icns", "ICNS"),
    ):
        output = BytesIO()
        canvas.save(output, format=format_name)
        files.append((path, output.getvalue()))
    return tuple(files)


def _escape_name(name: str) -> str:
    return (
        name.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace(" ", "\\s")
    )


def _merge(
    data: bytes, section: str, values: dict[str, str], *, windows: bool = False
) -> bytes:
    """Replace only owned keys, retaining comments, other groups, and view settings."""
    try:
        text = data.decode(
            "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        )
    except UnicodeError as error:
        raise ValueError(
            "Companion metadata is not UTF-8 or BOM-marked UTF-16"
        ) from error
    if "\x00" in text:
        raise ValueError("Companion metadata contains NUL characters")
    newline = "\r\n" if windows or "\r\n" in text else "\n"
    keys = {key.casefold() for key in values}
    output: list[str] = []
    inside = False
    inserted = False
    for line in text.splitlines(keepends=True):
        header = re.fullmatch(r"\s*\[([^\]]+)\]\s*", line.rstrip("\r\n"))
        if header:
            inside = header[1].casefold() == section.casefold()
            output.append(
                f"[{section}]{newline}"
                if inside
                else line
                if line.endswith(("\n", "\r"))
                else line + newline
            )
            if inside and not inserted:
                output.extend(
                    f"{key}={value}{newline}" for key, value in values.items()
                )
                inserted = True
            continue
        key = line.split("=", 1)[0].strip().split("[", 1)[0].casefold()
        if inside and "=" in line and key in keys:
            continue
        output.append(line)
    if not inserted:
        if output and not output[-1].endswith(("\n", "\r")):
            output.append(newline)
        output.append(f"[{section}]{newline}")
        output.extend(f"{key}={value}{newline}" for key, value in values.items())
    return "".join(output).encode("utf-16" if windows else "utf-8")


def capture(
    session: FilesystemSession, name: str, product_image: str
) -> VolumePresentation:
    """Read bounded, validated paths and plan changes without performing any writes."""
    if "\x00" in name:
        raise ValueError("The iPod name contains NUL characters")
    root_paths = tuple(entry.path for entry in session.list_root())
    files: list[FilePrecondition] = []
    writes: list[TransactionWrite] = []

    def prepare(
        path_text: str,
        data: bytes | None,
        section: str = "",
        values: dict[str, str] | None = None,
    ) -> None:
        path = DevicePath(path_text)
        if path.name.casefold() == "autorun.inf":
            matches = tuple(
                p for p in root_paths if p.name.casefold() == path.name.casefold()
            )
            if len(matches) > 1:
                raise ValueError(f"Ambiguous desktop companion path: {path}")
            if matches:
                path = matches[0]
        snapshot = (
            session.read_snapshot(path, max_bytes=_MAX_FILE_BYTES)
            if session.exists(path)
            else None
        )
        original = snapshot.data if snapshot is not None else b""
        expected = snapshot.fingerprint if snapshot is not None else None
        if data is None:
            data = _merge(
                original,
                section,
                values or {},
                windows=path.name.casefold() == "autorun.inf",
            )
        files.append(FilePrecondition(path, expected))
        if snapshot is None or data != original:
            writes.append(
                TransactionWrite(
                    path,
                    data,
                    FileContent(len(data), hashlib.sha256(data).hexdigest()),
                    expected,
                )
            )

    for path, data in _icons(product_image):
        prepare(path, data)
    windows = {"icon": _ICON.replace("/", "\\") + ".ico"}
    linux = {"IconFile": _ICON + ".png"}
    kde = {"Icon": "./" + _ICON + ".png"}
    if name:
        windows["label"] = "".join(" " if ord(c) < 32 else c for c in name)
        linux["Name"] = _escape_name(name)
        kde["Name"] = _escape_name(name)
    prepare("autorun.inf", None, "AutoRun", windows)
    prepare(".xdg-volume-info", None, "Volume Info", linux)
    prepare(".directory", None, "Desktop Entry", kde)
    return VolumePresentation(tuple(files), tuple(writes))


def apply_native(session: FilesystemSession, name: str) -> tuple[str, ...]:
    """Derived cosmetic metadata may fail independently of a committed Library."""
    issues: list[str] = []
    try:
        session.enable_volume_icon()
    except StorageError as error:
        issues.append(str(error))
    if name and session.is_active:
        try:
            label = session.set_volume_label(name)
            if label != name:
                issues.append(
                    f"The filesystem volume label is {label!r}; its format cannot represent the full iPod name {name!r}."
                )
        except (StorageError, ValueError) as error:
            issues.append(str(error))
    if session.is_active:
        try:
            flushed = session.flush()
            if not flushed.complete:
                issues.append(flushed.detail)
        except StorageError as error:
            issues.append(str(error))
    return tuple(issues)
