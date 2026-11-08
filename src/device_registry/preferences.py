"""Pure qualification of studied Preferences formats from ranked identity evidence."""

from device_registry.firmware import resolve_firmware_target, strongest_values
from device_registry.models import (
    DeviceEvidence,
    DeviceProfile,
    PreferencesSupport,
)


def resolve_preferences_support(
    profile: DeviceProfile | None, evidence: DeviceEvidence
) -> PreferencesSupport:
    """Require a studied model and latest release without resolving conflicts.

    Transport revisions are not RetailOS releases. Exact older model/release
    pairs can qualify without an updater observation, but any such observation
    must agree. Later Classic SKUs cannot distinguish updater 35 from 38 and
    therefore require an explicit family (ADR-0242). File framing remains a
    separate codec check; this function neither reads nor authorizes file writes.
    """
    if profile is None:
        return PreferencesSupport(
            reason="Select an identified iPod to edit preferences."
        )
    versions = {value.strip() for value in strongest_values(evidence.firmware_versions)}
    families = set(strongest_values(evidence.updater_family_ids))
    if len(versions) != 1 or len(families) > 1:
        return PreferencesSupport(
            reason="Missing or conflicting firmware evidence leaves preferences read-only."
        )
    target = resolve_firmware_target(
        profile,
        strongest_values(evidence.firmware_versions),
        strongest_values(evidence.updater_family_ids),
    )
    if target is not None:
        return PreferencesSupport(target=target)
    return PreferencesSupport(
        reason="This model and firmware combination is not qualified for preferences editing."
    )
