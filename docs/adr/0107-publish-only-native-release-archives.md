# ADR-0107: Publish only native release archives

- Status: Accepted
- Date: 2026-10-03
- Amends: ADR-0104's public release asset set

## Context

The owner requested that GitHub Release downloads contain only native binaries,
without separate checksums, JSON reports, Python distributions, or source archives.
Linux retains its binary tar.gz format; Windows and both macOS targets use ZIP.

## Decision

Upload only those four native archives to the release. Keep assembly validation
and retain supporting files in the producing Actions run's
`release-supporting-files` artifact. Keep notices inside each application bundle.

## Consequences

The release download list is limited to native applications. Supporting files
remain available through Actions, subject to artifact access and retention rules.
This changes publication layout, not the outstanding source/licensing review or
platform acceptance requirements documented in the packaging guide.
