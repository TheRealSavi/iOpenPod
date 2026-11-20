"""Exact Classic source inputs, historical ports and the common 2.0.5 output.

Executable ROM/Bds/FirmwareFS sections are identical across these releases.
See docs/research/classic-bootloader-family-comparison-2026-11-17.md.
"""

from dataclasses import dataclass, replace

from iOpenPod.app.firmware.classic_layout import MAX_OS_BODY_BYTES


@dataclass(frozen=True)
class LoaderProfile:
    family: int
    stock_sha256: str
    rom_sha256: str
    bds_sha256: str
    fs_sha256: str
    rom_offset: int
    pad_offset: int
    seccore_offset: int
    max_body_bytes: int
    hardware: int
    unmarked_sha256: str
    marker_offset: int
    shared: bool = False


PROFILES = {
    24: LoaderProfile(
        24,
        "460368ec325ab567b3ea1d0c5e2eb09df7dac0502c1141257ffb32d661248f96",
        "da907bb58d3b276780da0dcfbde0bb9ac32beb0bc2598c62f8a9c13a76aa1bb1",
        "ac008eeb64e668de1426037f63cd9a4216ef1b44e729d1a4bd9dd1502a41b1bd",
        "6ea5c797b508d220bf1480c121f1fa8a40ae5000924706d62ea1322112cd8fe6",
        79784,
        108440,
        128240,
        0x978800,
        0x00130000,
        "42d18c4828a7fe84380d85dfd759948f511af8a9fd35bea0a53b2656787a169c",
        109936,
    ),
    33: LoaderProfile(
        33,
        "8d028296d20d7162eb109d062239ba510fe842510e006178040caacbabead1b8",
        "b40292cb19cf8830172d3671d96cb4ae0eb720287ff37ef85698456aa0d29959",
        "3098db1612edfc87180a52ec9fc9c5fbd8430e0e21d7afe19749f09dfec87e6a",
        "6e9fceb9753df6b5552ffdc5f03869c7fd8cef12ded7af5f430266d1897f6652",
        79680,
        108264,
        128272,
        0xA07800,
        0x00130100,
        "fb0d5ebff7c97f3efb8de3e5b429e0b0bb698687b0aa7b1a8ef50d205c404f90",
        109768,
    ),
    35: LoaderProfile(
        35,
        "7caf3863376cf7890adc73601d24fbf11bc9ce89c7b40366fd61b45a1d6633e8",
        "e7891d4c91baa5cc739ef45ae4c91f65707db66f0f1136efbcc4ad267b601be8",
        "2508bb3cf843f67508b04e0bbb8bc3654b782964927ad43644b3a3ba9a4d2cff",
        "1eaa4e3f45abcb7664faaf7542b989a1eb96d19ac0721e3dc45e5cc4ddbc1f3a",
        79720,
        108312,
        128272,
        0xA1C800,
        0x00130200,
        "aa5307e1e39bb5f26e7506acd16d493b29ba5f2e18fe8279175686f3a1c4969d",
        109816,
    ),
    38: LoaderProfile(
        38,
        "d2670f7e5493c4b5ed4b9b6fa2029ce1e519c1927522384469e810fbf408fb5e",
        "3a26b4e8049824b99865d8d2d6eb2c2d3edc9c008f7f244a51d8f5cd1417ebfe",
        "6f0989ec72cfc881b074ffa75da398896e2e7aca169948de68574d2898f01ab3",
        "4b2012c6b1d9a531b0bcf5ebc7035925099a411d6f5ae1d6969f4fadc922bbf7",
        79696,
        108312,
        128272,
        0xA25800,
        0x00130300,
        "1bfcee49f13331378d3d4478ed970893d4cd1d0badbb5e82138ee4f4e0927b2d",
        109816,
    ),
}

# One 2.0.5 executable. The original profiles qualify migration inputs and
# retain reproducible builds of the previous installers.
SHARED_PROFILE = replace(
    PROFILES[38],
    shared=True,
    max_body_bytes=MAX_OS_BODY_BYTES,
    unmarked_sha256="104c0d6453dc03e6cd8952c46855802dbbae91ffc8a1023a921ab0b474b17a32",
    marker_offset=109952,
)
