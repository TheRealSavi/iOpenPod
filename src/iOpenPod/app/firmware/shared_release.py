"""Prepare the complete bundled Classic release without any network access."""

from __future__ import annotations

import hashlib
import zlib
from importlib.resources import files
from typing import TYPE_CHECKING

from storage import AtomicHostFile, StorageOperationError
from storage.host_files import lock_host_file

from .classic_layout import STOCK_LAYOUT
from .classic_shared import FIRMWARE_BYTES
from .classic_update import ClassicStockRelease
from .paths import firmware_directory

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from threading import Event

MOD_VERSION = "0.12.3-dev"
IMAGE_SHA256 = "9656d06f3552da7ad23eef3ed7b994435e9aa92b2e53997e9d254f88522d5b9f"
RELEASE_HASHES = {
    "0.2.0-dev": "05b1d49671a42f190ed7f8bbd62c2f8b38e54749cb8261c39904dbef851ecff4",
    "0.2.1-dev": "2dc8b94f0fff21c1fb70f6d9748c95890fed35de8fdd72d187ffd605742ce5dd",
    "0.2.2-dev": "85c66c324fbe4a8042591bcf4302a376e90336d9c1493f761e4d22614561f42d",
    "0.3.0-dev": "5346c62318ecc9995988afc38b28f168436cd5591aea618c602e664196ddd408",
    "0.4.0-dev": "c075efa6507fbd85673b8b9788e7a8e10f52c3efdc387a21f7be64cb24a9ef3c",
    "0.4.1-dev": "8ec96b7483e59c11d34737ebbbc661b54f425834a4880ee12e9a684b97f43c55",
    "0.4.2-dev": "e8298b82fd8ca9d92ed101a5601a8a015e65c9a9aabed8d8563ac9f50081e549",
    "0.4.3-dev": "ab637fa796bab12aab7ed2f5d88f5036fc021726ae9fb9d977db508b47d785ca",
    "0.5.0-dev": "4a1edbea58cda048606dde961fb95cdbc911da7a9841fdfbb536f6d4fae00969",
    "0.6.0-dev": "9d4c9852b737f8ca59401275b033c4a2c8a9d3b2dac35ab8a3351a32ce102701",
    "0.6.1-dev": "8138f36d6b2a9ad16e3329fffb2fbf6c31e80d1b979ecb68f024d0eb31620f61",
    "0.6.2-dev": "4a28fcb0fbc649fe99e3793807764343fbc6b85e26c57e538cb284d84a9572eb",
    "0.6.3-dev": "97a1ae6f321b037b18af52a028335e4c173f60e0ac86b159a62f33e1c5fb24a5",
    "0.6.4-diag": "c16d4af298ecef7aadbbe8d3e4d62312c059b328680e62a4fee9b45ffb24b426",
    "0.6.5-diag": "02881e5dce2d18904b695e5551f9221eb2ce53de956e0c86317a786160aedf15",
    "0.6.6-dev": "7f4d74b4baed56bc22bb29cdac3a08c36d95a48ecf2ca5eed9ce5b38ae50a900",
    "0.6.7-dev": "18f850b017fecc6862ab05eecf09b8129c7ef18db0d61c14fa37220f6156cc13",
    "0.6.8-dev": "b3ea06db84b792375e1467b0364af046bebb8befb97c135b0348eef98404a1e6",
    "0.7.0-dev": "fe1cdca1d2242b379d084c13cd92f7ef0399ff0c5c84fe3ed02f8f8f20cc37cc",
    "0.8.0-dev": "53e5d37236a31bdc40510631f655bd801803275e14317f3a967b0b92065cece7",
    "0.8.1-dev": "a2ce45790af7a68320c4e4f49f1c9736129878208c0a7a45fadc3dc58271a1f4",
    "0.8.2-dev": "315ba834b15f71fc55d12a79cd51b888598fb45c0e689b02a214e8d10d947fa6",
    "0.9.0-dev": "fdad0f8f47936accf0a6ee81351adea8ffb7e479df6981d43cb70df60fa883bf",
    "0.10.0-dev": "eeac9095f05ca7d1077075cf9d805899cc0cf0d317fe105275c8a856943892a9",
    "0.11.0-dev": "bdbbfce14bf1a01638b2988324599efbadf4fb92b4fde048e3110be5ec8ab0fb",
    "0.12.0-dev": "d2e34211ab0934c33775ae3dd1d6c12407013e85b0f63728b3d44f8cc60b8526",
    "0.12.1-dev": "13b6e6d9a52811e0a45e8bdde699840bfcb3fef6dac4805aee5c82f35df815c1",
    "0.12.2-dev": "199454cfa660dac4e0382dac44e7efbaa9613bc630e1c02e6b7cba6eba358311",
    MOD_VERSION: IMAGE_SHA256,
}
RELEASE_BYTES = {
    "0.2.0-dev": STOCK_LAYOUT.end,
    "0.2.1-dev": STOCK_LAYOUT.end,
    "0.2.2-dev": STOCK_LAYOUT.end,
    "0.3.0-dev": FIRMWARE_BYTES,
    "0.4.0-dev": FIRMWARE_BYTES,
    "0.4.1-dev": FIRMWARE_BYTES,
    "0.4.2-dev": FIRMWARE_BYTES,
    "0.4.3-dev": FIRMWARE_BYTES,
    "0.5.0-dev": FIRMWARE_BYTES,
    "0.6.0-dev": FIRMWARE_BYTES,
    "0.6.1-dev": FIRMWARE_BYTES,
    "0.6.2-dev": FIRMWARE_BYTES,
    "0.6.3-dev": FIRMWARE_BYTES,
    "0.6.4-diag": FIRMWARE_BYTES,
    "0.6.5-diag": FIRMWARE_BYTES,
    "0.6.6-dev": FIRMWARE_BYTES,
    "0.6.7-dev": FIRMWARE_BYTES,
    "0.6.8-dev": FIRMWARE_BYTES,
    "0.7.0-dev": FIRMWARE_BYTES,
    "0.8.0-dev": FIRMWARE_BYTES,
    "0.8.1-dev": FIRMWARE_BYTES,
    "0.8.2-dev": FIRMWARE_BYTES,
    "0.9.0-dev": FIRMWARE_BYTES,
    "0.10.0-dev": FIRMWARE_BYTES,
    "0.11.0-dev": FIRMWARE_BYTES,
    "0.12.0-dev": FIRMWARE_BYTES,
    "0.12.1-dev": FIRMWARE_BYTES,
    "0.12.2-dev": FIRMWARE_BYTES,
    MOD_VERSION: FIRMWARE_BYTES,
}
STOCK = ClassicStockRelease(
    38,
    "2.0.5",
    0x09058000,
    0x02058000,
    "Firmware-38.9.0.5",
    "80f974edea54ae4c9b659578a0c4d74438ffd94b8270944ec0cfc8f10e90eb2d",
    "9450c5b51f8785d41c1eef041eac3c7a521d0b325d730f591759b49d041086aa",
    STOCK_LAYOUT.end,
)


def validate_release(image: bytes) -> None:
    if (
        len(image) != FIRMWARE_BYTES
        or hashlib.sha256(image).hexdigest() != IMAGE_SHA256
    ):
        raise ValueError("Shared firmware does not match the bundled release")


def bundled_firmware() -> bytes:
    asset = files("iOpenPod").joinpath("assets/firmware/classic-shared/firmware.zlib")
    with asset.open("rb") as source:
        compressed = source.read(FIRMWARE_BYTES + 1)
    if len(compressed) > FIRMWARE_BYTES:
        raise ValueError("Oversized bundled firmware asset; reinstall iOpenPod")
    stream = zlib.decompressobj()
    try:
        image = stream.decompress(compressed, FIRMWARE_BYTES + 1)
    except zlib.error as error:
        raise ValueError(
            "Damaged bundled firmware asset; reinstall iOpenPod"
        ) from error
    if not stream.eof or stream.unused_data or stream.unconsumed_tail:
        raise ValueError("Damaged bundled firmware asset; reinstall iOpenPod")
    validate_release(image)
    return image


class SharedFirmwareRelease:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory if directory is not None else firmware_directory()

    def prepare(self, cancel: Event, progress: Callable[[int | None], None]) -> bytes:
        destination = AtomicHostFile(
            self.directory / "shared" / MOD_VERSION / "firmware.bin"
        )
        with lock_host_file(destination.path):
            if cancel.is_set():
                raise InterruptedError("Firmware preparation canceled")
            try:
                cached = destination.read_bytes(max_bytes=FIRMWARE_BYTES)
            except StorageOperationError:
                cached = None
            if (
                cached is not None
                and len(cached) == FIRMWARE_BYTES
                and hashlib.sha256(cached).hexdigest() == IMAGE_SHA256
            ):
                return cached
            progress(None)
            image = bundled_firmware()
            if cancel.is_set():
                raise InterruptedError("Firmware preparation canceled")
            destination.replace_bytes(image)
            progress(100)
            return image
