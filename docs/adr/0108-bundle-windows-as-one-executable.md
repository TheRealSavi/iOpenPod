# ADR-0108: Bundle Windows as one executable

- Status: Accepted
- Date: 2026-10-03
- Amends: ADR-0079's Windows directory-bundle layout

## Context

The owner requested a standalone Windows executable without a separate `_internal`
folder and accepted the extraction and startup-time tradeoff.

## Decision

Use PyInstaller one-file mode on Windows. Embed the runtime, libraries, resources,
and notices in `dist/iOpenPod.exe`. The Windows release ZIP contains only that file,
and MSIX staging places the same file under `app/`. macOS and Linux retain their
existing bundle layouts.

## Consequences

Windows users can move the executable independently. PyInstaller extracts the
embedded payload into a temporary directory at launch and removes it on normal
exit. Bundle validation inspects the embedded archive rather than `_internal`;
CI still runs the frozen smoke test outside the checkout. Store acceptance remains
a separate validation of the actual installed package.
