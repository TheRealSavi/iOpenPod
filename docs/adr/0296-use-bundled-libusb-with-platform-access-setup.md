# ADR-0296: Use bundled libusb with platform access setup

- Status: Accepted
- Date: 2026-11-24
- Supersedes: ADR-0294's DFU backend and Linux permission policy
- Preserves: ADR-0277, ADR-0279 and the MSIX distribution restriction

## Decision

Adopt the RepriseOS Installer v0.2.8 access policy for iOpenPod's existing
Classic bootloader workflow. Include the pinned libusb-package binary library
on Windows, macOS and Linux; users need neither a compiler nor a separate libusb
download. Native builds collect the matching DLL, dylib or shared object, and
the runtime smoke check loads it without discovering devices. Existing source
and license records cover the additional platforms. This increases the Windows
and macOS bundles by one native dependency and avoids relying on a Host install.

Windows prefers libusb, with the installed Apple PIPE0 driver as a fallback
when opening or preparing the interface is unsupported or denied. Busy or
disconnected sessions stop. Fallback requires an unambiguous candidate and
rechecks the original connection before and after opening Apple handles.
The Application Layer still qualifies the selected product serial and SysCfg
before any persistent write. A transfer failure never switches transports or
replays a request. If neither driver can open DFU, explain that Apple's iPod
device support is included with iTunes. iOpenPod does not install, replace or
redistribute a Windows driver; a portable executable cannot guarantee access
on a clean Windows PC.

macOS uses bundled libusb against the system USB stack. Retain one libusb
context for the process lifetime to avoid the Darwin teardown problem noted
upstream. Each channel releases its claim and handle. Retained device references
and per-observation identities reject a reconnect even at the same USB address.

Linux keeps sysfs connection checks and libusb's wrapped descriptor transport.
The native staging root includes a udev rule for `05ac:1223`. If opening is
denied and the rule is absent, one polkit authorization installs the same narrow
rule and refreshes matching devices. The helper accepts bounded numeric USB
identifiers and generates fixed syntax, without caller-supplied paths or text.
Only the active local desktop user receives access; there is no world-writable
USB rule or raw-disk grant. The app reopens as its ordinary user and rechecks
the connection. Denial stops the attempt; a rule that is already installed but
ineffective produces reconnect/session guidance rather than another prompt.
Sandboxed packages still need Host permission setup outside their sandbox.

## Installation and qualification

Retain iOpenPod's bundled writer, exact input qualification, retained initial
NOR image, durable handoff, matching nonce, complete flash verification and
read-only unfinished-result check. RepriseOS v0.2.8 does not read back final NOR
completion, so its completion criterion is not adopted. Routine firmware updates
continue through the existing native SCSI Sessions, including their separate
authorization rules. The Windows MSIX continues to omit both install actions.

Automated tests cover transport selection, multiple candidates, stale connections,
claim/transfer failures, handle cleanup, fixed permission rules, cancellation,
packaged resources and existing installation/result-verification behavior.
The Windows bundled runtime is load-tested without USB access. Physical DFU
installation through the new libusb path, Linux desktop permission setup, and
Intel/Apple Silicon Mac installations remain acceptance work; tests with native
API doubles do not establish hardware qualification.

See the [source investigation](../research/repriseos-usb-bootloader-2026-11-24.md)
for pinned upstream evidence and the distinction between RepriseOS's temporary
helper and iOpenPod's actual DFU identity.
