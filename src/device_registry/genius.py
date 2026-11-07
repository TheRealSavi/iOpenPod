"""Pure refinement of catalog Genius support from RetailOS version evidence."""

from __future__ import annotations

import re
from dataclasses import replace

from device_registry.models import DeviceEvidence, DeviceProfile, FeatureSupport


def refine_genius_capabilities(
    profile: DeviceProfile, evidence: DeviceEvidence
) -> DeviceProfile:
    """Resolve firmware-dependent support without changing the catalog baseline.

    Missing, malformed, or equally authoritative conflicting versions leave the
    conditional feature unknown. Transport revisions and internal build numbers
    are deliberately excluded from ``DeviceEvidence.firmware_versions``.
    """

    genius = profile.capabilities.genius
    minimum = genius.mixes_minimum_firmware
    if minimum is None:
        return profile
    support = FeatureSupport.UNKNOWN
    if evidence.firmware_versions:
        authority = max(item.authority for item in evidence.firmware_versions)
        versions = {
            _release_version(item.value)
            for item in evidence.firmware_versions
            if item.authority == authority
        }
        if len(versions) == 1 and (version := next(iter(versions))) is not None:
            support = (
                FeatureSupport.SUPPORTED
                if version >= minimum
                else FeatureSupport.UNSUPPORTED
            )
    if support is genius.mixes:
        return profile
    return profile.with_capabilities(
        replace(profile.capabilities, genius=replace(genius, mixes=support))
    )


def _release_version(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(
        r"([0-9]{1,3})\.([0-9]{1,3})(?:\.([0-9]{1,3}))?", value.strip()
    )
    if match is None:
        return None
    return int(match[1]), int(match[2]), int(match[3] or 0)
