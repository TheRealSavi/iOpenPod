# ADR-0190: Prepare and diagnose Linux device access

- Status: Accepted
- Date: 2026-10-25
- Extends: ADR-0011, ADR-0079, and ADR-0167

## Context

Issue [270](https://github.com/TheRealSavi/iOpenPod/issues/270) reports readable
iPods failing discovery under Linux, with no Linux setup prompt and an unresponsive
Open Log Folder button. The reporter's cause is unconfirmed. Captured Linux mount
records reproduce a failure before hardware probing: validating Host recovery
storage cannot identify an eCryptfs home folder's backing Physical Device. The
picker hides the actual error, and discovery does not log it. Original iOpenPod
does not perform this mandatory Host recovery check during discovery.

Frozen Linux desktop helpers also inherit bundled library and Qt search paths.
Their failures can occur after Qt reports a successful launch request. Media tools
already receive a separate Host environment; desktop opening needs that treatment.

## Decision

Storage resolves an eCryptfs mount's absolute backing directory against the same
Linux mount-table snapshot before comparing Physical Device identities. It follows
only this understood filesystem relationship and resolves backing-path aliases.
Missing backing paths, relative sources, cycles, and unsupported non-block-backed
filesystems remain unavailable. The existing same-device rejection policy,
device revalidation, and mandatory Host recovery checks
remain in place; discovery does not skip pending recovery or become an alternate
browse-only workflow.

Host recovery validation errors identify the Host recovery location while retaining
their typed failure. The Device Picker shows inspection details as selectable plain
text. Discovery logs a new or changed inspection failure once per Device Candidate;
unchanged polling results do not repeat it.

Native frozen Linux desktop opening uses `xdg-open` with an explicit child
environment. It restores the original Host library path and removes bundle-owned
Qt/QML search directories without changing process-wide environment variables.
The same Qt-path cleanup applies to other Host tools. Desktop helpers are detached
so application shutdown does not terminate the opened Host application. Their stderr
appends to the active application log, and immediate launch failures are reported.
Source installs, macOS, Windows, and confined Flatpak/Snap packages retain Qt's
desktop integration, including permission-aware portals.

Settings > About always exposes the active log file path in a read-only, copyable
field. A successful desktop launch request still does not guarantee a visible
window, so the path remains available independently of the launch result.

## Consequences

This addresses the reproduced eCryptfs compatibility failure while retaining
recovery validation. It adds no dependencies, installation privileges,
filesystem permission changes, or device mutations during discovery. It does not
add a DEB distribution or establish the cause of an application failing before its
GUI opens.

A follow-up audit found an existing gap in the general Linux Physical Device
comparison: logical mapped-device identifiers are not resolved through their
physical backing graph. A captured mapping backed by the selected iPod was
incorrectly accepted for Host recovery. This change does not fix that broader
case or establish the ADR-0167 separation guarantee for arbitrary storage stacks.
Physical-backing resolution, search-only ancestor permissions, discovery without
udev properties, and durable ZFS/network/FUSE recovery locations need follow-up.

ADR-0191 subsequently adds a separate live backing comparison for supported block
graphs and fails closed for unsupported layouts. Search-only ancestor permissions,
discovery without udev properties, and additional recovery-location support remain
separate follow-ups.

ADR-0192 subsequently permits search-only ancestors while retaining pinned
no-follow reads and normal leaf read/listing permissions.

Regression coverage uses captured Linux mount/udev facts with real temporary files,
same-device and unresolved-backing rejection, discovery/setup integration, repeated
failure logging, a real detached child that records its environment and fails to
stderr, copyable diagnostic paths, and literal picker details. Physical LMDE and
Linux Mint desktop acceptance of the released bundle remains necessary.
