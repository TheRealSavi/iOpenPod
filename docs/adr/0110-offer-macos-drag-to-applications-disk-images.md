# ADR-0110: Offer macOS drag-to-Applications disk images

- Status: Accepted
- Date: 2026-10-03
- Amends: ADR-0107's public release asset set

## Context

The macOS ZIP contains the app bundle needed by Sparkle, but first-time users must
extract it and decide where to place the app. A disk image can present the app beside
an Applications shortcut without changing the update protocol.

## Decision

Publish a read-only compressed DMG for each macOS architecture, containing the same
signed `iOpenPod.app` as the ZIP and a shortcut to `/Applications`. Keep both macOS
ZIPs as Sparkle update archives. GitHub Releases now contain six native downloads:
the Windows ZIP, two macOS ZIPs, two macOS DMGs, and the Linux tar.gz. Candidate
builds verify the mounted image layout and app signature; release assembly checks
each DMG and its checksum. Supporting files remain in the Actions artifact.

## Consequences

The initial standalone macOS install is still a user-directed drag into
Applications. Sparkle does not perform that first installation. A DMG alone does
not establish Gatekeeper acceptance; Developer ID signing, notarization, and native
installed-app testing remain separate release gates.
