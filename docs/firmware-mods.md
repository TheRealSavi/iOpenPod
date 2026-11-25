# Firmware mods

iOpenPod's firmware mod platform is being developed inside **Device Summary**.
It preserves Apple's firmware version and gives the platform its own version.
Users will compose a build by selecting mods, and the iPod's firmware will expose
the registry of mods included in that build. See [ADR-0275](adr/0275-compose-firmware-mods-with-independent-platform-identity.md).

## Current behavior

Device Summary shows Reported Firmware, Mod Platform Version, hardware family ID,
bootloader version and OS Updater Family. Cached OS values are marked explicitly;
tooltips distinguish current firmware reports from historical DFU results. A new
connection or explicit refresh reads current metadata again. Its **Firmware**
section offers bootloader setup and normal-USB firmware installation on standalone
Windows, macOS and Linux builds for Classic families 24, 33, 35 and 38:

1. **Install unlocked bootloader** installs the Universal Unlocked Bootloader
   **2.1.0** through guided DFU setup. It is hidden when the qualified current
   bootloader is installed. A recognized older loader instead offers
   **Update bootloader to 2.1.0**.
2. **Install universal 2.0.5** installs Universal Classic Firmware **2.0.5**, with
   **Mod Version: 0.12.3-dev**, through normal USB. It appears only with a qualified
   current bootloader and is hidden when the current Mod Platform Version is
   already installed. An existing mod release instead offers
   **Update firmware to 0.12.3-dev**.

When both versions are current, neither button nor its hint appears. The section
says **Bootloader and firmware are up to date.**

The new release allows up to **4 MiB of linked mod code and data**, with a
**16 MiB OS slot** inside the existing firmware partition. Already-unlocked
Classics need the 2.1.0 loader upgrade in DFU once; later compatible OS updates
use normal USB. The expanded pair has passed offline/native tests and awaits
physical installation. See [expanded-space evidence](research/classic-expanded-mod-space-2026-11-17.md).

Both are included with iOpenPod and work offline from first use. There is no Apple
catalog check, stock firmware offer, Restore/Update download button or network
fallback. Universal refers to the four Classic families, not every iPod model.
The preceding 0.2.0-dev shared pair physically booted on family 33, with About versions,
menus/clickwheel and headphone playback confirmed. The other families are enabled
by project-owner direction using binary comparisons and simulated installation.
See [ADR-0283](adr/0283-bundle-universal-classic-firmware-and-remove-stock-offers.md)
and [the physical trial](research/classic-shared-205-os-layout-2026-11-17.md#physical-family-33-trial).

The current release includes unsigned eapp manifests through Apple's native
game-reader mode. Executable Verify/DRM checks remain unchanged. Parachute passes
the native gate and import probes; the user confirmed launch and controls on family 33. See
[homebrew evidence](research/classic-homebrew-eapp-manifests-2026-11-17.md).

Highlight **Mods** in **Extras** to see a silver gear in the preview pane.
Press the center button to see the Firmware Mods included in this build.

- Mod Version String
- Mod Version in About
- Unsigned Game Manifests
- Mod Menu
- Expanded Mod Memory
- Light / Dark Appearance
- Now Playing Preview Artwork
- Bootloader Report
- Long Audio Playback
- Fast Audio Seeking
- Photo Zoom and Pan
- Title Bar Clock
- Mono Audio

This is a read-only native list, with ordinary Menu-button back navigation.
The labels and build provenance come from the same included-mod records.
It does not enable the parked desktop mod selector. Native ARM and resource
checks pass; physical display/navigation verification remains outstanding. See
[menu evidence](research/classic-mod-menu-2026-11-17.md).

On the iPod, **Settings → Mono Audio** appears below Sound Check. Highlight it
to see two channels joining at a single speaker. Choose **On**
to hear both stereo channels through either headphone or dock channel. **Off**
restores stereo. The iPod keeps this choice across output changes and restarts.
See [playback routing and validation](research/classic-mono-audio.md).

**Title Bar Clock** follows **Settings → Date & Time → Time in Title**. With
the setting on, full-width bars show the title at the left, the status indicators
five pixels before the clock's measured text, and the time at the far right.
This includes photo album grids,
the running or stopped Stopwatch, Genius Mixes and the video playback overlay.
The video clock disappears with the overlay. Narrow menu bars keep alternating
between title and time. See the [layout inventory](research/classic-title-bar-clock-2026-11-19.md).

**Photo Zoom and Pan** opens when you click Center on a full-size photo. One
clockwise revolution adds 100 percentage points. Counterclockwise turns reduce
zoom, with limits of 100% and 500%. Hold Center to look up, Play/Pause to look
down, Reverse to look left or Forward to look right. The view moves at 200 screen
pixels per second and stops at the photo edge or when you release the button.
Click Menu to restore the fitted view, then click Menu at fit to leave the
mode. A small magnifier in the bottom-right corner stays visible while the mode
is active, including at 100%. Play/Pause starts the slideshow during ordinary photo viewing.
Zoom uses the 720 × 480 F1067 photo rendition when available, preserving the
fitted image's proportions. Missing or pending high-resolution images use the
320 × 240 LCD rendition until the higher-resolution image is ready for a paint.
See [native qualification](research/classic-photo-zoom-2026-11-19.md).

**Long Audio Playback** corrects the MP4 audio timestamp comparisons that stop
long M4B playback around 13.5 hours at 44.1 kHz. **Fast Audio Seeking** jumps near
the requested position using the native sample tables, then lets Apple's walker
finish the seek. Unsupported layouts retain the native path. Both are included
in 0.7.0-dev; they add one 4 KiB reserved page and no retained audio cache.
Native cursor/packet, boundary and error-recovery checks pass; physical playback
and timing still need validation. See
[implementation and qualification](research/classic-long-audio-fixes-2026-11-18.md).

**Settings → Appearance** cycles **Light → Dark → Auto → Light**, directly after
Brightness. Auto uses the iPod's displayed local time: Light from 7 AM until
6 PM, Dark overnight. It reevaluates on the existing clock timer, including
after sleep or a time change, with no extra timer or preference writes.
Light is the default. The firmware remembers the selection across
restarts; if saving fails, it displays **Not saved** and retains the current mode.
Dark appearance changes native interface surfaces, text, shadows, selections and
controls while preserving personal album artwork, photos and games. The latest
refinement covers Genius/Shuffle control skins and labels, Calendar date/weekday
ink, a charcoal Search field and built-in artwork placeholders. Compressed
artwork deltas apply in place without a second image buffer. Its offline native
tests pass; this release still needs a physical display check. See
[appearance design and validation](research/classic-dark-mode-design-2026-11-17.md).

The 0.6.1-dev correction darkens the unselected World Clock row gradient while
preserving the day/night faces and hands. Cached rendering updates in place and
returns exactly to Light, with no additional reserved RAM. See
[clock-row evidence](research/classic-dark-mode-clocks-2026-11-18.md).

**Now Playing Preview Artwork** displays the current track's 128 × 128 album
cover when Now Playing is highlighted on the main menu. Title, artist and album
remain below it. The preview uses native artwork loading, track-change refresh
and no-art fallback. The mod works independently
of appearance. Version 0.6.2-dev drops borrowed dynamic image contexts when
views hide/show, with no new image cache or reserved RAM. The user reports this
mostly fixes preview loss after Cover Flow. Version 0.6.3-dev also refreshes the
Now Playing artwork property during manual and Auto appearance changes, covering
an attached preview that receives no hide/show transition. This passes native
tests but awaits the remaining Dark → Light hardware check. See
[appearance refresh evidence](research/classic-appearance-artwork-refresh-2026-11-18.md),
[lifetime evidence and limits](research/classic-menu-artwork-lifetime-2026-11-18.md) and
[native preview evidence](research/classic-now-playing-preview-artwork-2026-11-18.md).

Version **0.6.6-dev** added current-track thumbnail loading and retention:
it retains the current track's thumbnail using Apple's existing model reference,
instead of relying on the transient playback buffer. Native replay tests pass,
including an explicit thumbnail request from the menu with no playback artwork
preloaded; opening the full Now Playing screen is not required by that path.
Native replay coverage also includes track changes, failed-file recovery and
reference cleanup. Ownership
stays at about 32 KiB, briefly 64 KiB during replacement, without an accumulating
image cache. The user still reproduced the Podcasts failure on that build.
Version **0.6.7-dev** corrects the drawing mode: the preview reads the
actual dynamic bitmap format instead of a stale embedded bitmap format. This
prevents color artwork being drawn as an icon mask. The matching blank-draw replay
passes, and the user confirms correct behavior on the iPod. The
**0.6.8-dev** release keeps that correction and removes temporary artwork tracing,
pixel sampling and its USB fields. It frees one 4 KiB RAM page. Bootloader Report
remains enabled; developers can opt into artwork tracing when needed. See
[drawing-mode evidence](research/classic-now-playing-render-mode-2026-11-18.md) and
[capture, fix and evidence limits](research/classic-artwork-diagnostics-2026-11-18.md).

## Install the universal Classic release

These installation actions are available outside the Windows MSIX distribution.
The Microsoft Store edition shows the firmware information reported by the iPod.

Bootloader setup and upgrades include libusb on Windows, macOS and Linux.
Windows tries libusb first, then Apple's installed DFU driver. If neither is
available, install Apple's iPod device support included with iTunes, reconnect
the iPod and reopen setup. iOpenPod does not install a Windows driver.
macOS uses bundled libusb with the system USB stack, without a Homebrew package.
Linux native package staging includes a narrowly scoped DFU udev rule. When
permission setup is needed, the desktop's polkit prompt installs that rule once;
the app continues as the normal user. It grants access only to the active local
desktop user and does not grant raw-disk access. Reconnect if permissions have
not taken effect. Sandboxed distributions need Host permission setup separately.
Physical installation through the new libusb path and Linux permission setup,
including current Intel/Apple Silicon Macs, remain pending.
See [ADR-0296](adr/0296-use-bundled-libusb-with-platform-access-setup.md).

Routine updates on a Classic with a verified bootloader use the Host's SCSI
interface. Close apps using the iPod before starting. Windows locks the Volume
through the system mass-storage driver. If opening requires administrator access,
one UAC prompt authorizes the bundled native helper to open that USB Volume.
The app then verifies identity, locks and transfers as the normal user; cancellation
stops the attempt. No separate helper download or elevated GUI is required.
macOS unmounts the selected partition and requests exclusive access through IOKit.
Linux asks UDisks2 to unmount the selected partition, holds the whole disk
exclusively and transfers through the kernel's SCSI generic interface. Linux may
prompt for desktop authorization. If the volume was unmounted and setup stops
before the upload, reconnect the iPod to mount it again. Physical firmware
uploads on macOS and Linux are still unverified.
[Windows volume access](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew#physical-disks-and-volumes).

The packaged app includes the firmware and bootloader assets.
Users do not need a C compiler, a separate DLL download or a firmware download.
Linux desktop authorization requires a running polkit agent and pkexec when the
user lacks direct USB access. A denied request stops setup before any write.

1. Connect the Classic normally, select it, and open **Device Summary**. Choose
   **Install unlocked bootloader**. The dialog identifies the selected device,
   shows the Menu and Select buttons on a Classic image, installs and verifies
   the loader, then explains how to reboot. To enter DFU, keep USB connected and
   Hold off. Hold **Menu + Select** (the center button) through the first black
   screen and the Apple logo. Release both at the **second black screen**.
   Re-select the iPod after it reconnects normally.
2. Choose **Install universal 2.0.5**. iOpenPod unpacks its included complete
   firmware, checks the release hash and retains it in persistent Host application
   data. Keep USB connected while it installs and the iPod restarts.
3. When the upload finishes, iOpenPod shows **Installation complete**. Close the
   dialog and let the iPod finish restarting with USB connected. Completion is
   based on the acknowledged upload and restart request.

Stock source releases 24/1.1.2, 33/2.0.1, 35/2.0.4 and 38/2.0.5, previous
family-specific loaders, shared 2.0.0 and the original family-33 v5b loader migrate to the
same loader executable. Its header authentication comes from the destination
iPod during DFU. Re-running setup recognizes the current shared loader without
rewriting it. Routine compatible OS updates require no DFU or per-device signing.

The firmware action requires current OS reports and qualified bootloader evidence.
**Bootloader Report** measures the actual plaintext loader once at startup, then
serves its marker, complete SHA-256 and SysCfg identity through normal USB.
Device Summary shows the measured version and hardware family with **Reported by
firmware** tooltips. A compatible current report allows updates on another computer without
DFU. Current failed, malformed or incompatible reports override any old receipt.
Encrypted loaders report their version as unavailable; a missing marker is not
proof of an OEM loader. The first report-capable release still needs installation
using the existing verified receipt or guided DFU setup.

Older firmware without this interface retains the same-computer receipt path,
with **Last verified in DFU** tooltips. That receipt cannot detect an external stock
restore with identical OS reports. Firmware 2.0.5 alone proves neither custom OS
nor unlocked loader. Hardware revisions 35/38 share model numbers; actual SysCfg
distinguishes them from the OS updater family. Before writing, the installer
rechecks current bootloader evidence in its retained SCSI Session along with
identity, mode, partition capacity and transfer limits. The report is a boot-time
measurement from the running firmware, not cryptographic attestation. Native tests
pass; physical validation remains outstanding. See [ADR-0287](adr/0287-report-measured-classic-bootloader-through-current-usb.md)
and [report evidence](research/classic-bootloader-report-2026-11-18.md).

## Included files and completion records

The complete OS, resources and directory are compressed into the application's
56,765,941-byte `firmware.zlib` asset. Its output is the complete
101,871,616-byte shared image. Preparation uses bounded decompression and the
pinned full-image hash. A damaged cache is rebuilt locally; a damaged bundle
requires repairing iOpenPod, never a download. See [the packager](../scripts/firmware/README.md).

The persistent firmware directory is `%LOCALAPPDATA%/iOpenPod/firmware` on Windows.
The prepared image is `shared/0.12.3-dev/firmware.bin`. Existing saved Apple IPSWs
are no longer used. The initial NOR copy and loader receipts remain under
`bootloader/<serial>`; firmware installation records are under
`installations/<serial>/operation.json`. The OS installer creates no additional
device recovery copies.

`app/firmware/shared_records.py` owns the typed installation states, saved JSON
codec and completion of older uploaded receipts. It performs no I/O. The
installer owns device operations and persists the same record schema and state
strings used by earlier builds. Fully acknowledged awaiting-boot,
reboot-in-flight and boot-verified receipts become complete automatically.

Cancellation is available before writing. A live writer cannot be canceled or
detached by closing its dialog. Unfinished bootloader records expose **Check
bootloader result**, including after app restart without an Active iPod.
Interrupted firmware uploads require the separate DFU recovery workflow.
If the complete upload and finalizer were acknowledged but USB loses the restart
reply, the installation completes and the receipt retains the pending restart
command. Explicit failed SCSI responses still appear as errors.

The bootloader's `iOpenPod-Bootloader-v1` identity record has schema/ABI 2, release
2.1.0 and a four-revision hardware mask. Full body hashes identify its code. Native
drivers retain real SysCfg; only a validated shared OS's copied compatibility
fields change. The OS reports family 38 on older Classics, so iOpenPod selects
the 2.0.5 firmware contracts while retaining the physical model/generation.
The complete image marks Apple's AUPD applied to preserve the unlocked loader,
and the normal-update protocol preserves the device-specific hash record.

## Parked prototype

The standalone experimental panel can show a separate recorded Mod Platform
Version, a supplied Firmware Mod Registry, and an **Include in next build** checklist.
Selecting Parachute Fixed includes Homebrew games automatically. Required
dependencies cannot be unchecked while their dependents remain selected.
**Review build** shows the Apple base, platform version, effective mods, and any
mods removed from the recorded installation. **Clear selection** explicitly
clears the requested set while retaining the mandatory platform core.

Selections survive same-device UI refreshes and language changes. A different
connection, firmware target, or installed registry resets the draft. Unknown
installed mods remain visible and prevent silently rebuilding without them;
Clear selection followed by review permits explicit removal.

The initial research catalog describes Parachute Fixed, Homebrew games, and
Classic Dark Mode. It is not a list of installable releases. Exact input profiles
currently cover the studied Classic 120 GB 2.0.1, Classic updater-38 2.0.5, and
Nano 3 1.1.3 inputs. That does not qualify a cross-family update or physical boot.
Unqualified devices receive an unavailable state in the standalone prototype.

The parked mod-selection panel does not compile or install selected mods. Current installed metadata
can be captured from `iPod_Control/iOpenPod/Firmware/installed.json` through Storage,
bounded to 128 KiB. Missing and unreadable registries remain distinct from an
observed installed platform. This helper is not invoked during ordinary device
loading or Sync.

## Build and registry contract

`iOpenPod.app.firmware` contains the Application Layer implementation:

- `models.py` defines immutable Apple inputs, mods, patches, plans, and builds.
- `planner.py` resolves deterministic dependency order and checks conflicts,
  exclusive hooks, image bounds, overlaps, input hashes, and expected original
  bytes. It produces new bytes without device access. A missing qualified recipe
  fails before returning an image; an empty recipe is explicitly metadata-only.
- `registry.py` reads/writes schema 1 and emits freestanding C registry data.
  IDs, names, versions, fingerprints, entry counts, size, and duplicate JSON keys
  are validated. Generated C quotes every UTF-8 byte to prevent source injection.
- `capture.py` reads optional installed-build records through a Filesystem Session.
- `catalog.py` records the initial exact research inputs and candidate mods.

The Firmware Build ID includes the Apple target/version/hash/size, platform
version, requested selection, resolved mod metadata, and patch preimages and
replacement bytes. Catalog iteration order and duplicated checkbox selections do
not change it. A recipe change changes the ID even if its author forgot to bump
the mod version. Built bytes have a separate output SHA-256.

The fixed-size composition engine is a tested foundation, not a complete native
linker or boot-container builder. Compiled payload placement, relocation, resource
generation, shared hook dispatch, heap reservation and companion interfaces need
target-specific build adapters. No currently bundled mod pretends that a patched
raw OSOS body is an installable firmware bundle.

## Continuing product scope

The remaining native work includes the Mods screen and embedded registry,
composing selected mods against the exact Apple base, and qualifying a complete
Classic boot bundle with a stock boot fallback. The independent platform version
and About row have already run on the selected Classic33. Nano targets
need independently qualified loaders and hooks. Host-side build checks and
emulator results do not substitute for physical boot, menu, playback, sleep,
USB, game lifecycle and recovery tests.

The installation workflow must separately support official Apple update
eligibility, immutable source acquisition, build review, initial bootloader
personalization, staging, readback verification, reconnect/re-identification,
commit, and recoverable cleanup. Publication records are written only after
verified installation; boot confirmation remains distinct. Third-party mod
distribution requires authenticated catalogs, pinned payload hashes, stable
compatibility declarations, attribution, and a developer package format.

The selected unsigned-OS policy preserves Apple's version and the authenticated
Apple boot path, while accepting an explicit custom container without publisher
signatures or per-device OS signing. Its unkeyed checksums detect corruption and
do not restrict who can author a build. DFU remains an initial bootloader and
recovery operation; routine custom OS updates use the normal USB transport.
See [ADR-0278](adr/0278-allow-host-built-unsigned-custom-firmware.md) and the
[implementation evidence](research/classic33-unsigned-boot-path-2026-11-17.md).

No product workflow imports firmware tools, account material, or device captures
from a sibling lab checkout. The complete common image is packaged as a compressed
asset. It contains Apple-derived code and resources, excluded from iOpenPod's GPL grant by its
[notice](../src/iOpenPod/assets/firmware/classic-shared/NOTICE.txt). The complete
image has no device identity or signing material. Personalized bootloader headers
remain local outputs. Users need no ARM compiler or external firmware package.
