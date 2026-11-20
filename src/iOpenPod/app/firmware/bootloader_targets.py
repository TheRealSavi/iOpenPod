"""Pinned Classic releases; capacity or model name alone never selects a loader."""

from dataclasses import dataclass

BOOTROM_SHA = "69c087afc5753d7f0f11f09b141b372af753a854bc526673ea444c486d6003e4"


@dataclass(frozen=True)
class BootloaderTarget:
    family: int
    apple_version: str
    models: tuple[str, ...]
    hardware: int
    stock_sha256: str
    target_sha256: str
    manifest_sha256: str
    gap_start: int
    seccore_offset: int
    max_body_bytes: int
    legacy_sha256: str | None = None

    @property
    def unlocked_digests(self) -> tuple[str, ...]:
        return (self.target_sha256,) + (
            (self.legacy_sha256,) if self.legacy_sha256 is not None else ()
        )


CLASSIC_BOOTLOADERS = (
    BootloaderTarget(
        24,
        "1.1.2",
        ("MB029", "MB147", "MB145", "MB150"),
        0x00130000,
        "460368ec325ab567b3ea1d0c5e2eb09df7dac0502c1141257ffb32d661248f96",
        "2f29ceef5ad494885cc81e390261b34227bdc6d14ec455224c7e4272e052f5cf",
        "27b3c0df7e7910e8ff755094077ce330cdb3fa6f15d04e7d86cffea170d58648",
        110000,
        128240,
        0x978800,
    ),
    BootloaderTarget(
        33,
        "2.0.1",
        ("MB562", "MB565"),
        0x00130100,
        "8d028296d20d7162eb109d062239ba510fe842510e006178040caacbabead1b8",
        "286656927ea39e2115583930d867ae810e715255b1b54ff6ca0a01e151caabea",
        "8f2f5f2b8749ccefa60ed4afcda3f42ffd77cf5688d336875a90bcf00f46dbf1",
        109832,
        128272,
        0xA07800,
        "fb0d5ebff7c97f3efb8de3e5b429e0b0bb698687b0aa7b1a8ef50d205c404f90",
    ),
    BootloaderTarget(
        35,
        "2.0.4",
        ("MC293", "MC297"),
        0x00130200,
        "7caf3863376cf7890adc73601d24fbf11bc9ce89c7b40366fd61b45a1d6633e8",
        "641f4adbcad34a36845f4dfffe3cf97fc8f4373f4f85693c6980a4f3501ac002",
        "2682c67f7ede70d90ce61d418845a38640e514326afec4ed8013cad815b1370c",
        109880,
        128272,
        0xA1C800,
    ),
    BootloaderTarget(
        38,
        "2.0.5",
        ("MC293", "MC297"),
        0x00130300,
        "d2670f7e5493c4b5ed4b9b6fa2029ce1e519c1927522384469e810fbf408fb5e",
        "4db5f3d96d5a7544f9a70fd2c271fbaf26d4f675995423a167a0d1d23d402f19",
        "9aab370e62021910dc4a0ad9c6e544c24266445a1ba5c12f79a330e36b54dcd3",
        109880,
        128272,
        0xA25800,
    ),
)


def bootloader_target(family: int) -> BootloaderTarget:
    for target in CLASSIC_BOOTLOADERS:
        if family == target.family:
            return target
    raise ValueError("Unsupported Classic updater family")
