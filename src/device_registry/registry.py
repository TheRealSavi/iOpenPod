"""The Device Registry deep module."""

from __future__ import annotations

from dataclasses import dataclass

from device_registry.identifiers import (
    format_usb_identifier,
    normalize_model_number,
    normalize_serial,
)
from device_registry.models import (
    ConnectionMode,
    DeviceEvidence,
    DeviceIdentifier,
    DeviceProfile,
    EvidenceAuthority,
    IdentificationIssue,
    IdentificationIssueCode,
    IdentificationResult,
    IdentificationStatus,
    IdentifierKind,
    IdentifierSummary,
    ModelIdentity,
    RegistryCatalog,
    UsbIdentifier,
    UsbProductDefinition,
)


@dataclass(frozen=True, slots=True)
class _ExactClaim:
    profile: DeviceProfile
    summary: IdentifierSummary


@dataclass(frozen=True, slots=True)
class _UsbObservation:
    definition: UsbProductDefinition
    summary: IdentifierSummary


class DeviceRegistry:
    """Resolve normalized evidence against an immutable iPod catalog."""

    def __init__(self, catalog: RegistryCatalog) -> None:
        profiles_by_model: dict[str, DeviceProfile] = {}
        profiles_by_identity: dict[ModelIdentity, list[DeviceProfile]] = {}
        for profile in catalog.profiles:
            model_number = normalize_model_number(profile.model_number)
            if model_number != profile.model_number:
                raise ValueError(
                    f"Catalog model number is not canonical: {profile.model_number}"
                )
            if model_number in profiles_by_model:
                raise ValueError(f"Duplicate catalog model number: {model_number}")
            profiles_by_model[model_number] = profile
            identity = ModelIdentity(profile.family, profile.generation)
            profiles_by_identity.setdefault(identity, []).append(profile)

        suffixes: dict[str, DeviceProfile] = {}
        for suffix_definition in catalog.serial_suffixes:
            suffix = normalize_serial(suffix_definition.suffix)
            if len(suffix) not in {3, 4}:
                raise ValueError(
                    f"Serial suffix must contain 3 or 4 characters: {suffix}"
                )
            if suffix in suffixes:
                raise ValueError(f"Duplicate serial suffix: {suffix}")
            suffix_profile = profiles_by_model.get(
                normalize_model_number(suffix_definition.model_number)
            )
            if suffix_profile is None:
                raise ValueError(
                    f"Serial suffix {suffix} refers to an unknown model: "
                    f"{suffix_definition.model_number}"
                )
            suffixes[suffix] = suffix_profile

        usb_products: dict[UsbIdentifier, UsbProductDefinition] = {}
        usb_candidates: dict[UsbIdentifier, tuple[DeviceProfile, ...]] = {}
        for usb_definition in catalog.usb_products:
            if usb_definition.identifier in usb_products:
                rendered = format_usb_identifier(usb_definition.identifier)
                raise ValueError(f"Duplicate USB definition: {rendered}")
            candidates: list[DeviceProfile] = []
            for identity in usb_definition.candidate_identities:
                candidates.extend(profiles_by_identity.get(identity, ()))
            if not candidates:
                rendered = format_usb_identifier(usb_definition.identifier)
                raise ValueError(
                    f"USB definition has no catalog candidates: {rendered}"
                )
            usb_products[usb_definition.identifier] = usb_definition
            usb_candidates[usb_definition.identifier] = tuple(candidates)

        self._profiles = catalog.profiles
        self._profiles_by_model = profiles_by_model
        self._serial_suffixes = suffixes
        self._serial_suffix_lengths = tuple(
            sorted({len(suffix) for suffix in suffixes}, reverse=True)
        )
        self._usb_products = usb_products
        self._usb_candidates = usb_candidates

    @property
    def profiles(self) -> tuple[DeviceProfile, ...]:
        """Return the immutable catalog in stable display order."""

        return self._profiles

    def profile_for_model_number(self, model_number: str) -> DeviceProfile | None:
        """Return an exact profile for a normalized or SysInfo-style model number."""

        return self._profiles_by_model.get(normalize_model_number(model_number))

    def identify(self, evidence: DeviceEvidence) -> IdentificationResult:
        """Resolve all supplied evidence without performing host or filesystem I/O."""

        exact_claims = self._exact_claims(evidence)
        usb_observations = self._usb_observations(evidence)
        has_current_usb_evidence = any(
            identifier.authority is EvidenceAuthority.CURRENT_HARDWARE
            for identifier in evidence.usb_identifiers
        )
        current_usb = tuple(
            observation
            for observation in usb_observations
            if observation.summary.authority is EvidenceAuthority.CURRENT_HARDWARE
        )

        current_modes = {item.definition.mode for item in current_usb}
        if len(current_modes) > 1:
            issue = IdentificationIssue(
                code=IdentificationIssueCode.USB_IDENTIFIERS_DISAGREE,
                identifiers=tuple(item.summary for item in current_usb),
            )
            return IdentificationResult(
                status=IdentificationStatus.CONFLICTING,
                connection_mode=ConnectionMode.UNKNOWN,
                issues=(issue,),
            )

        connection_mode = (
            next(iter(current_modes)) if current_modes else ConnectionMode.UNKNOWN
        )
        exact_profile, exact_issues, exact_conflict = self._resolve_exact_claims(
            exact_claims
        )
        if exact_conflict:
            return IdentificationResult(
                status=IdentificationStatus.CONFLICTING,
                connection_mode=connection_mode,
                issues=exact_issues,
            )

        candidate_observations = (
            current_usb
            if has_current_usb_evidence
            else self._highest_authority_usb(usb_observations)
        )
        usb_candidates, usb_conflict = self._intersect_usb_candidates(
            candidate_observations
        )
        usb_issues: tuple[IdentificationIssue, ...] = ()
        if usb_conflict:
            usb_issues = (
                IdentificationIssue(
                    code=IdentificationIssueCode.USB_IDENTIFIERS_DISAGREE,
                    identifiers=tuple(item.summary for item in candidate_observations),
                ),
            )

        if connection_mode is ConnectionMode.RECOVERY:
            issues = exact_issues + usb_issues
            if (
                exact_profile is not None
                and usb_candidates
                and exact_profile not in usb_candidates
            ):
                issues += (
                    self._usb_profile_disagreement(
                        exact_claims,
                        current_usb,
                    ),
                )
            return IdentificationResult(
                status=IdentificationStatus.RECOVERY_MODE,
                connection_mode=connection_mode,
                candidates=usb_candidates,
                issues=issues,
            )

        if usb_conflict:
            return IdentificationResult(
                status=IdentificationStatus.CONFLICTING,
                connection_mode=connection_mode,
                issues=exact_issues + usb_issues,
            )

        if exact_profile is not None:
            if current_usb and exact_profile not in usb_candidates:
                return IdentificationResult(
                    status=IdentificationStatus.CONFLICTING,
                    connection_mode=connection_mode,
                    issues=(
                        *exact_issues,
                        self._usb_profile_disagreement(
                            exact_claims,
                            current_usb,
                        ),
                    ),
                )
            return IdentificationResult(
                status=IdentificationStatus.EXACT,
                connection_mode=connection_mode,
                profile=exact_profile,
                candidates=(exact_profile,),
                issues=exact_issues,
            )

        if usb_candidates:
            return IdentificationResult(
                status=IdentificationStatus.AMBIGUOUS,
                connection_mode=connection_mode,
                candidates=usb_candidates,
                issues=usb_issues,
            )

        return IdentificationResult(
            status=IdentificationStatus.UNKNOWN,
            connection_mode=connection_mode,
            issues=usb_issues,
        )

    def _profile_for_product_serial(self, serial: str) -> DeviceProfile | None:
        normalized = normalize_serial(serial)
        for length in self._serial_suffix_lengths:
            if len(normalized) < length:
                continue
            profile = self._serial_suffixes.get(normalized[-length:])
            if profile is not None:
                return profile
        return None

    def _exact_claims(self, evidence: DeviceEvidence) -> tuple[_ExactClaim, ...]:
        claims: list[_ExactClaim] = []
        for identifier in evidence.model_numbers:
            profile = self.profile_for_model_number(identifier.value)
            if profile is not None:
                claims.append(
                    _ExactClaim(
                        profile=profile,
                        summary=self._text_summary(
                            IdentifierKind.MODEL_NUMBER,
                            normalize_model_number(identifier.value),
                            identifier,
                        ),
                    )
                )
        for identifier in evidence.product_serials:
            profile = self._profile_for_product_serial(identifier.value)
            if profile is not None:
                claims.append(
                    _ExactClaim(
                        profile=profile,
                        summary=self._text_summary(
                            IdentifierKind.PRODUCT_SERIAL,
                            normalize_serial(identifier.value),
                            identifier,
                        ),
                    )
                )
        return tuple(claims)

    @staticmethod
    def _text_summary(
        kind: IdentifierKind,
        value: str,
        identifier: DeviceIdentifier[str],
    ) -> IdentifierSummary:
        return IdentifierSummary(
            kind=kind,
            value=value,
            source=identifier.source,
            authority=identifier.authority,
        )

    def _usb_observations(
        self,
        evidence: DeviceEvidence,
    ) -> tuple[_UsbObservation, ...]:
        result: list[_UsbObservation] = []
        for identifier in evidence.usb_identifiers:
            definition = self._usb_products.get(identifier.value)
            if definition is None:
                continue
            result.append(
                _UsbObservation(
                    definition=definition,
                    summary=IdentifierSummary(
                        kind=IdentifierKind.USB,
                        value=format_usb_identifier(identifier.value),
                        source=identifier.source,
                        authority=identifier.authority,
                    ),
                )
            )
        return tuple(result)

    @staticmethod
    def _highest_authority_usb(
        observations: tuple[_UsbObservation, ...],
    ) -> tuple[_UsbObservation, ...]:
        if not observations:
            return ()
        authority = max(item.summary.authority for item in observations)
        return tuple(
            item for item in observations if item.summary.authority is authority
        )

    def _intersect_usb_candidates(
        self,
        observations: tuple[_UsbObservation, ...],
    ) -> tuple[tuple[DeviceProfile, ...], bool]:
        if not observations:
            return (), False
        candidate_sets: list[set[DeviceProfile]] = [
            set(self._usb_candidates[item.definition.identifier])
            for item in observations
        ]
        intersection = candidate_sets[0].intersection(*candidate_sets[1:])
        candidates = tuple(sorted(intersection, key=lambda item: item.model_number))
        return candidates, not bool(intersection)

    @staticmethod
    def _resolve_exact_claims(
        claims: tuple[_ExactClaim, ...],
    ) -> tuple[
        DeviceProfile | None,
        tuple[IdentificationIssue, ...],
        bool,
    ]:
        if not claims:
            return None, (), False
        highest_authority = max(claim.summary.authority for claim in claims)
        strongest = tuple(
            claim for claim in claims if claim.summary.authority is highest_authority
        )
        strongest_models = {claim.profile.model_number for claim in strongest}
        if len(strongest_models) > 1:
            issue = IdentificationIssue(
                code=IdentificationIssueCode.EXACT_IDENTIFIERS_DISAGREE,
                identifiers=tuple(claim.summary for claim in strongest),
            )
            return None, (issue,), True

        winner = strongest[0].profile
        rejected = tuple(
            claim.summary
            for claim in claims
            if claim.profile.model_number != winner.model_number
        )
        if not rejected:
            return winner, (), False
        issue = IdentificationIssue(
            code=IdentificationIssueCode.LOWER_AUTHORITY_IDENTIFIER_DISAGREES,
            identifiers=(strongest[0].summary, *rejected),
        )
        return winner, (issue,), False

    @staticmethod
    def _usb_profile_disagreement(
        exact_claims: tuple[_ExactClaim, ...],
        usb_observations: tuple[_UsbObservation, ...],
    ) -> IdentificationIssue:
        highest_authority = max(claim.summary.authority for claim in exact_claims)
        strongest = next(
            claim
            for claim in exact_claims
            if claim.summary.authority is highest_authority
        )
        return IdentificationIssue(
            code=IdentificationIssueCode.USB_IDENTITY_DISAGREES,
            identifiers=(
                strongest.summary,
                *(item.summary for item in usb_observations),
            ),
        )
