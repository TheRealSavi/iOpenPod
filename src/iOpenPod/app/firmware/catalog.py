"""Initial research catalog, deliberately separate from installation eligibility.

Hashes describe exact preserved build inputs. These are not installable bundles
or an online Apple update catalog. No mod has a production build adapter yet.
"""

from device_registry import FirmwareTarget
from iOpenPod.app.firmware.models import AppleFirmware, FirmwareMod

PLATFORM_VERSION = "0.1.0-dev"
CORE_ID = "org.iopenpod.platform"

BASES = {
    FirmwareTarget.CLASSIC_120GB_2_0_1: AppleFirmware(
        "classic-120gb-2.0.1-normalized",
        "2.0.1",
        "220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e",
        10513984,
    ),
    FirmwareTarget.CLASSIC_UPDATER_38_2_0_5: AppleFirmware(
        "classic-2.0.5-body",
        "2.0.5",
        "d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224",
        10632448,
    ),
    FirmwareTarget.NANO_3_1_1_3: AppleFirmware(
        "nano-3-1.1.3-body",
        "1.1.3",
        "ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a",
        10790256,
    ),
}
_TARGETS = tuple(base.target_id for base in BASES.values())
_CLASSICS = tuple(
    base.target_id
    for target, base in BASES.items()
    if target is not FirmwareTarget.NANO_3_1_1_3
)

CATALOG = (
    FirmwareMod(
        CORE_ID,
        PLATFORM_VERSION,
        "Mod platform",
        "Platform version and installed-mod registry.",
        _TARGETS,
    ),
    FirmwareMod(
        "org.iopenpod.homebrew",
        "0.1.0-dev",
        "Homebrew games",
        "Support for independently authored click-wheel games.",
        _TARGETS,
        dependencies=(CORE_ID,),
        hooks=("game-manifest-reader",),
    ),
    FirmwareMod(
        "org.iopenpod.parachute",
        "0.1.0-dev",
        "Parachute Fixed",
        "Parachute with corrected gameplay and remade artwork.",
        _TARGETS,
        dependencies=("org.iopenpod.homebrew",),
    ),
    FirmwareMod(
        "org.iopenpod.dark-mode",
        "0.1.0-dev",
        "Dark Mode",
        "A dark appearance for the iPod menus.",
        _CLASSICS,
        dependencies=(CORE_ID,),
        hooks=("menu-colors",),
    ),
)
