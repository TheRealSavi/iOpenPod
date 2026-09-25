# ADR-0007: Ship one application with branded package names

- Status: Accepted
- Date: 2026-08-20

## Context

The architecture separates iOpenPod, Device Registry, iPodDB, and Storage so that
their responsibilities and dependency direction remain clear. That separation does
not require four independently released products. Separate distributions would add
versioning, publishing, and compatibility work without a current consumer outside
iOpenPod.

The product and Apple format names also have established capitalization that should
not be erased merely to make every visible name resemble a generic Python module.

## Decision

- Ship iOpenPod 2.0 as one application and one distribution named iOpenPod.
- Keep Device Registry, iPodDB, and Storage as internal packages. Do not publish or
  version them separately.
- Preserve established branded spelling wherever practical, including iOpenPod,
  iPod, iPodDB, iTunesDB, and ArtworkDB.
- Retain branded top-level Python package names such as `iOpenPod` and `iPodDB`.
- Use conventional lowercase identifiers for generic packages and modules, including
  `device_registry` and `storage`.
- Enforce subsystem independence through imports, explicit data, and tests rather
  than separate distribution machinery.

## Consequences

- One lockfile, installation, application version, and release contains all four
  subsystems.
- Internal package changes can be coordinated atomically within the repository.
- Code and documentation must not casually respell branded terms as `IOpenPod`,
  `Ipod`, or `Itunes`.
- Import names remain case-sensitive even though packaging tools or host filesystems
  may compare some names without case distinctions.
