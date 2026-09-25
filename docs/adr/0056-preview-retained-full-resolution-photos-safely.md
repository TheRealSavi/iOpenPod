# ADR-0056: Preview retained full-resolution Photos safely

- Status: Accepted
- Date: 2026-09-15
- Extends: ADR-0054 and ADR-0055

## Context

The Photo inspector can select exact iTHMB formats, and Photo export can copy a
retained full-resolution image through Storage. A user should also be able to view
that original in the inspector when the semantic Photo exposes one, without giving
the GUI a Device Path or allowing a large original to bypass the display-cache
bounds.

## Decision

- The inspector shows a Full res chip only when the selected Photo has a non-empty
  full-resolution reference. The largest retained iTHMB format remains the default
  selection so merely selecting a Photo does not read its original.
- Application-level `PhotoRequest` selector zero names the semantic full-resolution
  representation; positive selectors continue to name exact iTHMB formats, and an
  omitted selector continues to request automatic thumbnail selection. The original
  MHNI format ID is independent (Original iOpenPod writes `1`) and remains unchanged
  in the Library API's `PhotoRepresentation`.
- `DeviceCoordinator` resolves the current Photo and validates a readable,
  non-empty regular file beneath `Photos/` through the active Filesystem Session.
  Storage reads and fingerprints at most 32 MiB; the Application Layer rejects
  images beyond the shared 8,192-edge and 32-megapixel bounds, applies EXIF
  orientation, converts to RGB888, and downsamples to the requested display edge.
- Full-resolution cache entries include the file fingerprint and display target.
  They retain the existing Connection-Generation scope, asynchronous worker path,
  unavailable/error state, and explicit retry interaction.

## Consequences

The inspector can compare the original with each device rendition while the GUI
still receives only owned pixels and semantic metadata. Full-resolution reads remain
opt-in and cannot retain the original-sized decoded image merely because the source
contains more pixels than the inspector can display. A retained reference can still
be missing or malformed at read time; the existing selected-chip error and retry
behavior makes that state explicit.
