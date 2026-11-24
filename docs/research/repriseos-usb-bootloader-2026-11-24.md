# RepriseOS USB access and bootloader setup

Research date: 2026-11-24. Inspected RepriseOS Installer **v0.2.8** and its
pinned `osos-lab` revision `e5dc12924acd2d51331cf7bf0fb7f6f85e233e75`.
This investigation read source only; it performed no device access, driver
installation, firmware transfer or hardware qualification.

## Finding

RepriseOS bundles libusb, but the operating system still decides whether a
process may open an iPod. Its Windows policy is libusb first, installed Apple
DFU driver second, then actionable installation guidance. macOS uses libusb
against the system USB stack. Linux uses libusb with a narrowly scoped udev
permission rule installed by the package or an explicit administrator action.
The rule in this release covers RepriseOS's temporary upload helper, **not the
Apple BootROM DFU identity**. iOpenPod should adopt the access policy using its
own actual device identities and retain its stronger installation verification.
[Dependency pin and vendoring][cargo], [DFU transport][usb],
[Linux permission helper][permissions], [exact udev rule][rule]

## Distribution and drivers

`Cargo.toml` enables `rusb` 0.9.4's `vendored` feature. This builds libusb for
the target architecture into the release; it does not install an operating
system driver. The release workflow produces a universal macOS app/DMG, Windows
x64 NSIS setup and plain executable, and Linux x64 DEB/RPM/AppImage. Build-time
compilers and development headers in that workflow are not user prerequisites.
[Installer dependencies][cargo], [release workflow][release]

| Host | First-time access behavior | What is not provided |
| --- | --- | --- |
| Windows | Open and claim with libusb; if that fails, try the installed Apple DFU interface. | The NSIS hook does not install Apple or another USB driver. A clean PC still needs a compatible driver. |
| macOS | Open and claim with bundled libusb. Retain its context for the process lifetime. | No separate Apple driver or Homebrew install step appears in the installation instructions. |
| Linux | Bundled libusb; DEB/RPM install a helper-specific udev rule. The GUI can install the rule through polkit. | The GUI is not relaunched as root, and the rule does not grant access to all USB devices. |

The Windows NSIS hook writes/removes only an installation marker. The README's
user instructions direct users to the release, Apple 2.0.5 IPSW and in-app DFU
guide; its libusb/compiler requirements are under Development. The macOS
universal build contains both Intel and Apple Silicon targets.
[Windows installer hook][nsis], [README][readme], [release workflow][release],
[Linux package configuration][tauri]

## Exact USB behavior

### DFU selection and Windows fallback

Apple `05ac:1223` is shared with Nano 3; it does not qualify a Classic.
The selected candidate requires interface 0, alternate setting 0, class `0xfe`,
subclass 1 and protocol 2. Selection must produce one candidate. Windows tries
libusb open/claim before Apple fallback, without rebinding drivers. If Apple
support is absent, guidance points to iTunes and restoring drivers replaced by
Zadig. Discovery/configuration failures precede the fallback. [DFU transport][usb]

The Apple backend enumerates SetupAPI interface GUID
`b8085869-feb9-404b-8cb1-1e5c14fa8c54`, filters paths for `vid_05ac&pid_1223`,
retains the device handle and opens its `\PIPE0` endpoint with overlapped I/O.
It uses `ReadFile`/`WriteFile`, bounded `GetOverlappedResultEx`, and cancellation
followed by completion before releasing request buffers. Setup fields become
an eight-byte USB setup header plus payload. Because Apple interface paths and
libusb bus addresses lack a shared stable key in this implementation, fallback
requires exactly one enumerated DFU candidate and one Apple path. The native
opens permit read/write sharing; that is not an exclusive-device guarantee.
[Apple backend][apple], [packet framing][packet]

### macOS lifetime and claims

macOS uses the same open/claim path, without explicit kernel-driver detachment,
auto-detachment or configuration selection. A mutex retains the context for the
process lifetime to avoid a documented `libusb_exit` deadlock with Darwin's
detach callback after reset; device handles still close. This does not establish
unrestricted driver detachment. [DFU transport][usb]

### Linux permission setup

The shipped rule grants `TAG+="uaccess"` only to USB device `f055:180d`, the
RepriseOS upload helper. It does not name DFU `05ac:1223`. DEB/RPM install it at
`/usr/lib/udev/rules.d/70-repriseos.rules`; post-install/removal reloads rules
when udevadm is available. This separate identity matters: iOpenPod's DFU-only
bootloader transport cannot gain access by copying this rule unchanged.
[Exact rule][rule], [helper identity][helper-id],
[package configuration][tauri], [package hook][reload]

The app checks the first existing rule in precedence order `/etc`, `/run`,
`/usr/local/lib`, `/usr/lib`. It compares active lines while ignoring blank
lines/comments. An explicit Enable iPod access action starts
`pkexec --disable-internal-agent /bin/sh -c` with a compiled-in script and
destination, writes the rule under `/etc`, sets mode 0644, reloads udev and
verifies the installed content. No user-supplied shell text or path enters this
command. Canceled/denied authentication is an error; the GUI remains the normal
user. The script reloads rules without triggering all existing USB devices.
[Permission implementation][permissions], [permission screen][permission-ui]

### Temporary helper and Windows automatic binding

The upload helper is separate from BootROM DFU. It advertises Microsoft OS 1.0
descriptors with `WINUSB` compatibility and its own interface GUID. The Host
waits up to 90 seconds for helper enumeration and Windows driver readiness,
requiring the same bus and nonempty physical port path as the prior DFU device.
It validates interface class/subclass/protocol and bulk OUT endpoint before use.
This explains why the helper can use automatic WinUSB binding; it does not
remove the initial Apple DFU driver requirement. [Helper descriptors][winusb],
[helper transport][bulk]

## Bootloader installation sequence

All three platforms share the same checked Session and installation pipeline:

1. Serialize USB operations. Rediscover the selected DFU candidate, open its
   transport, restore DFU idle, read/qualify BootROM and cross-check SysCfg.
   Retain the checked Session and bind it to the selected package digest.
2. Authenticate and fingerprint the installed loader. Matching code is Keep;
   Apple code is Install; differing custom code is Upgrade.
3. Launch a temporary helper to inspect storage capacity and required disk
   space, then return to nonce-verified DFU.
4. Save a fresh full NOR/SysCfg copy for Install or Upgrade. Keep may reuse a
   complete saved copy only after checksum and device-identity validation.
5. Validate/decrypt the selected Apple 2.0.5 inputs, assemble pinned package
   recipes, personalize the companion's copied identity and save outputs.
6. Upload and verify themes, companion loader and custom OS disk files.
   Keep requests restart without rewriting NOR. Install/Upgrade disables
   cancellation and sends the compiled dual-boot NOR installer over DFU.

[Checked Session ownership][device], [transport checks][usb],
[install orchestration][install], [bootloader action][assembly],
[backup and assembly][firmware], [file transfers][transfer]

The device crate validates installer framing and bounds, appends a CRC, sends
1024-byte DFU download blocks with state/deadline checks, and manifests the
image. A timeout/disconnect during manifestation can represent handoff; that
does not prove flash completion. The GUI prevents close/exit while work is
running and journals the stages before disabling cancellation.
[Installer transfer][device-install], [DFU download][dfu],
[application lifecycle][app], [job journal][job]

The v0.2.8 result deliberately distinguishes InstallerSent from FilesUpdated.
Its journal explicitly says the NOR completion was not read back and the
subsequent boot was not verified. iOpenPod already requires a fresh retained
session, matching nonce and verified flash digests before success, plus
read-only result checks after interruption. Replacing those guarantees with
RepriseOS's handoff-only completion would weaken the existing design.
[Upstream completion handling][job],
[iOpenPod bootloader decision](../adr/0279-guide-classic-bootloader-unlock-through-device-summary.md)

## Application to iOpenPod

At investigation start, iOpenPod bundles `libusb-package` only on Linux;
Windows uses its retained Apple PIPE0 adapter and macOS uses an IOKit adapter.
Linux permission denial uses a polkit helper that hands one validated open
descriptor back to the normal-user process. These choices are explicit in
[ADR-0294](../adr/0294-use-upstream-usb-backends-for-classic-dfu-setup.md).

Adopting RepriseOS's policy means recording the changed backend preference and
permission lifetime, bundling native libusb on every supported Host, providing
Windows compatible-driver fallback and guidance, and implementing any one-time
Linux permission rule for iOpenPod's actual DFU identity. Keep Storage's retained
connection identity and invalidation, platform-neutral workflow, exact hardware
qualification, current nonce/readback checks and interruption journals.
The temporary RepriseOS filesystem helper and its firmware layout are separate
architecture; they are not required merely to adopt its Host driver strategy.

The corresponding iOpenPod Linux rule is fixed to USB device `05ac:1223` and
grants `uaccess` to the active local desktop user. It must not reuse RepriseOS's
`f055:180d`, cover all Apple devices, or substitute for the later BootROM/SysCfg
qualification. Preserve sysfs connection checks and the retained descriptor;
permission to open the node is not evidence that it is the selected Classic.
One-time DFU access setup is separate from the existing SCSI authorization path.

Automated adapter and workflow tests can establish forwarding, fallback,
identity-change failures, permission errors and package contents. They cannot
establish physical boot success on Linux, Intel macOS, Apple Silicon macOS, or
a Windows machine with each real driver binding. Those acceptance limits must
remain explicit. The Windows MSIX exclusion in ADR-0294 is a separate
distribution decision; a standalone transport change does not silently lift it.

## Source licensing

The installer manifest and inspected `reprise-device` sources declare
`GPL-3.0-only`; the Apple backend credits Rockbox's `GPL-2.0-or-later` PIPE0
protocol. iOpenPod already attributes these protocol sources in its Windows
adapter and uses `GPL-3.0-only` for several firmware-derived files. Preserve
source-specific attribution/license notices if adapting code. Vendored native
dependencies also need their own notices in distribution. This note records
source declarations, not a new license decision. [Installer manifest][cargo],
[Apple backend notice][apple], [device crate manifest][device-cargo]

[cargo]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src-tauri/Cargo.toml
[release]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/.github/workflows/release.yml
[readme]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/README.md
[nsis]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src-tauri/windows/hooks.nsh
[tauri]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src-tauri/tauri.conf.json
[rule]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src-tauri/linux/70-repriseos.rules
[reload]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src-tauri/linux/reload-udev.sh
[permissions]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src-tauri/src/usb_permissions.rs
[permission-ui]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src/components/UsbPermissionsScreen.tsx
[device]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src-tauri/src/device.rs
[install]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src-tauri/src/install.rs
[firmware]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src-tauri/src/install/firmware.rs
[transfer]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src-tauri/src/install/transfer.rs
[job]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src-tauri/src/install/job.rs
[app]: https://github.com/lgreitis/repriseos-installer/blob/v0.2.8/src-tauri/src/lib.rs
[usb]: https://github.com/lgreitis/osos-lab/blob/e5dc12924acd2d51331cf7bf0fb7f6f85e233e75/host/crates/reprise-device/src/usb.rs
[apple]: https://github.com/lgreitis/osos-lab/blob/e5dc12924acd2d51331cf7bf0fb7f6f85e233e75/host/crates/reprise-device/src/usb/apple.rs
[packet]: https://github.com/lgreitis/osos-lab/blob/e5dc12924acd2d51331cf7bf0fb7f6f85e233e75/host/crates/reprise-device/src/usb/apple_packet.rs
[dfu]: https://github.com/lgreitis/osos-lab/blob/e5dc12924acd2d51331cf7bf0fb7f6f85e233e75/host/crates/reprise-device/src/dfu.rs
[device-install]: https://github.com/lgreitis/osos-lab/blob/e5dc12924acd2d51331cf7bf0fb7f6f85e233e75/host/crates/reprise-device/src/install.rs
[device-cargo]: https://github.com/lgreitis/osos-lab/blob/e5dc12924acd2d51331cf7bf0fb7f6f85e233e75/host/crates/reprise-device/Cargo.toml
[bulk]: https://github.com/lgreitis/osos-lab/blob/e5dc12924acd2d51331cf7bf0fb7f6f85e233e75/host/crates/reprise-device/src/upload/transport.rs
[assembly]: https://github.com/lgreitis/osos-lab/blob/e5dc12924acd2d51331cf7bf0fb7f6f85e233e75/host/crates/reprise-bundle/src/assembly.rs
[helper-id]: https://github.com/lgreitis/osos-lab/blob/e5dc12924acd2d51331cf7bf0fb7f6f85e233e75/usb-helper/usb_identity.h
[winusb]: https://github.com/lgreitis/osos-lab/blob/e5dc12924acd2d51331cf7bf0fb7f6f85e233e75/usb-helper/winusb.h
