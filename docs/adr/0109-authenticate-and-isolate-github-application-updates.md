# ADR-0109: Authenticate and isolate GitHub application updates

- Status: Accepted
- Date: 2026-10-03
- Extends: ADR-0105 and ADR-0108

## Context

The owner approved implementing GitHub update checks and installation, including
Sparkle on macOS. The Original iOpenPod is the behavior baseline, but its directory
mirroring and remove-before-copy implementations could remove unrelated files or
leave an installation unusable. Windows now ships as one executable. Apple
Developer ID credentials are not currently available.

## Decision

Use runtime package evidence before consulting embedded standalone build metadata.
Store, Flatpak, Snap, receipt-bearing Mac apps, and source launches never fall back
to a GitHub installer. Standalone builds embed a numeric version, exact target,
layout protocol and public Ed25519 trust keys. Empty keys permit notification and
manual download only. Signing credentials are never embedded.

Authenticate a bounded, expiring release description before interpreting assets.
Use the existing PyCryptodome dependency rather than adding another crypto runtime.
The signed description fixes the repository, stable tag, version, platform,
layout, archive length and SHA-256, executable SHA-256, minimum runtime and protocol.
Persist authenticated sequence/version evidence to reject rollback and conflicting
metadata. Derive asset URLs locally; metadata supplies no executable commands or
destination paths. HTTPS transport additionally bounds size, time and redirects.

Keep signed JSON and architecture-specific signed Sparkle appcasts on the dedicated
`update-feed` branch. Publishing verifies already-public GitHub asset digests and
fast-forwards all feed files in one commit. This avoids Pages deployments replacing
feeds, while retaining the four-download GitHub Releases contract. It requires
release-key custody and explicit feed renewal when releases are infrequent.

Windows uses a separately frozen helper embedded in the single EXE. Stage into a
new private directory on the same fixed NTFS volume. Accept exactly one ZIP member,
`iOpenPod.exe`. Acknowledged, explicit handoff precedes orderly application exit.
Hold OS process handles and shared-use/exclusive-maintenance locks. Publication uses
verified open-file handles and no-replace renames. Retain the previous executable
and journal; rollback refuses changed identities or occupied destinations.

Linux archives contain a stable launcher, a version pointer, and immutable version
directories. Dereference packaging symlinks, then reject links and special files
during update extraction. The helper rechecks every runtime file against the signed
archive before executing it. Publish only the version pointer; retain previous and
failed versions. Earlier arbitrary onedir archives require a manual migration.
Package-managed Linux routes remain with their package manager.

Portable helpers run a device-free frozen runtime check before handoff. The next
GUI launch remains disabled and defers discovery/recovery until its health
handshake commits. Failed or interrupted publication retains recovery material.
There is no recursive cleanup or automatic deletion of retained versions.

macOS uses pinned Sparkle 2.10.0, with its full upstream notices. A small compiled
Objective-C bridge gives Qt typed callbacks without dynamically guessing block
metadata. Sparkle owns archive verification and bundle replacement. Require signed
feeds without the signature-expiration fallback, verify before extraction, disable
background downloads, and take the application work guard before accepting an
install. The selected version and URL must match authenticated JSON metadata.
Sparkle's lifecycle requires holding that guard through download and restart.

Ed25519 release signing is independent of Apple signing. Ad-hoc builds remain
possible; Developer ID signing and notarization are a later distribution setup.
Do not strip quarantine or invent an Apple identity. Native release validation
remains necessary on both Mac architectures and the minimum OS. ADR-0106's manual
Health policy remains unchanged.

## Consequences

- Users must install the first updater-enabled release manually.
- Checking never authorizes installation. Portable updates additionally require
  Restart to install, with the existing Library Draft and work guards.
- No updater may infer ownership of `_internal`, adjacent user files, or a backup
  merely from its name. Retained recovery files consume disk space until reviewed.
- Unsupported filesystems, layouts, versions, protocols or absent keys fail closed.
- Portable recovery is an explicit helper operation when a crash leaves no launchable
  target. It remains possible after feed expiry and never installs a newer candidate.
- Signing-key loss or an unplanned trust-root replacement requires a manual bootstrap.
  The publisher currently signs with the first configured key; automatic Sparkle
  key rotation is not claimed.
- OS locks coordinate cooperating launches. They are not a security boundary
  against a compromised account that already controls the application and its data.
- Native Windows, Linux and Mac update acceptance is separate from mocked lifecycle
  tests. Sparkle owns its recovery semantics; the portable health protocol does not
  imply that Sparkle rolls back an application that crashes after relaunch.

## References

- [Application updates](../app-updates.md)
- [Sparkle publishing](https://sparkle-project.org/documentation/publishing/)
- [Sparkle custom interfaces](https://sparkle-project.org/documentation/custom-user-interfaces/)
- [PyInstaller subprocess lifetime](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)
