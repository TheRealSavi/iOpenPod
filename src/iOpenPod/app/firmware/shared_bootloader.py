"""One Classic executable; source deltas only encode migrations to that body."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import cast

from .bootloader_bundle import WriterPlan, apply_delta, prepare_writer, sha
from .bootloader_identity import IDENTIFIER as IDENTIFIER
from .bootloader_identity import (
    BootloaderIdentity,
    read_bootloader_identity,
)
from .bootloader_targets import bootloader_target
from .classic_layout import MAX_OS_BODY_BYTES, MINIMUM_BOOTLOADER_VERSION

VERSION = MINIMUM_BOOTLOADER_VERSION
BODY_SHA256 = "7d4e94a6a509713d92e3d54f839491e4152a2fb639fb178ad50d2aaf38abbe61"
MANIFEST_SHA256 = "cc160a8e0077185f6abcfdf1f575046681afe29a264af30400efcd23f54113f5"
GAP_START = 110016
SECCORE_OFFSET = 128272


class SharedBootloaderBundle:
    def __init__(self) -> None:
        root = files("iOpenPod").joinpath("assets/bootloader/classic-shared")
        raw = root.joinpath("manifest.json").read_bytes()
        if sha(raw) != MANIFEST_SHA256:
            raise ValueError("Damaged shared bootloader manifest")
        manifest = json.loads(raw)
        if (
            manifest["schema"],
            manifest["target_sha256"],
            manifest["version"],
            manifest["gap_start"],
            manifest["seccore_offset"],
            manifest["max_body_bytes"],
        ) != (2, BODY_SHA256, VERSION, GAP_START, SECCORE_OFFSET, MAX_OS_BODY_BYTES):
            raise ValueError("Unsupported shared bootloader bundle")
        self._assets: dict[str, bytes] = {}
        for name, expected in manifest["files"].items():
            data = root.joinpath(name).read_bytes()
            if sha(data) != expected:
                raise ValueError(f"Damaged shared bootloader asset: {name}")
            self._assets[name] = data
        self._sources: dict[tuple[int, str], str] = {
            (source["family"], source["sha256"]): source["delta"]
            for source in manifest["sources"]
        }
        self._slots = cast("dict[str, dict[str, int]]", manifest["slots"])

    @staticmethod
    def is_current(body: bytes) -> bool:
        return (
            len(body) == 0x1F800
            and read_bootloader_identity(body)
            == BootloaderIdentity(2, 2, 0x43534C43, 15, VERSION)
            and sha(body) == BODY_SHA256
        )

    def apply(self, body: bytes, hardware_family: int) -> bytes:
        bootloader_target(hardware_family)
        if self.is_current(body):
            return body
        filename = self._sources.get((hardware_family, sha(body)))
        if len(body) != 0x1F800 or filename is None:
            raise ValueError(
                "This bootloader is not a qualified source for the selected Classic"
            )
        return apply_delta(body, self._assets[filename], BODY_SHA256)

    def writer(self, before: bytes, target: bytes, nonce: bytes) -> WriterPlan:
        return prepare_writer(
            before,
            target,
            nonce,
            body_sha256=BODY_SHA256,
            gap=GAP_START,
            tail=SECCORE_OFFSET,
            template=self._assets["writer.dfu"],
            slots=self._slots,
        )
