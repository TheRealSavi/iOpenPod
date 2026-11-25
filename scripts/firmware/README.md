# Common Classic 2.0.5 OS

The offline builder creates one OS image for Classic families 24, 33, 35 and 38,
using Apple's exact 2.0.5 base. It retains Apple's version and adds the independent
Mod Platform Version to the native About page. No device identity, signing key,
DFU call or per-device OS authentication is part of this build.

The current output is **0.12.3-dev**, including unsigned eapp manifests,
the read-only native **Extras → Mods** list and **Settings → Appearance** with
persistent Light/Dark/Auto selection, main-menu Now Playing artwork, Bootloader Report,
long MP4 audio repairs, Photo Zoom and Pan, Title Bar Clock, and Mono Audio. It requires
the shared **2.1.0** bootloader.
The current-track preview retains a native thumbnail reference and now selects
its drawing mode from the actual dynamic bitmap format. The user confirms correct
behavior on 0.6.7-dev. Version 0.6.8-dev omits temporary artwork diagnostics while
retaining those fixes and Bootloader Report.
See the [drawing-mode evidence](../../docs/research/classic-now-playing-render-mode-2026-11-18.md).
Older per-family loaders deliberately reject the new schema-2 `CLSC` target.
The compiled bootstrap, BSS reservation and About hook have passed native
emulation. The preceding 0.2.0-dev common OS booted on one physical family-33 MB565
Classic after installation through normal USB. The user confirmed About versions,
menus/clickwheel and headphone playback; the other families remain untested.

## Build

### Maintainer source map

| Module | Responsibility |
| --- | --- |
| `classic_target.py` | Exact prepared input identity and initialized native address ranges |
| `classic_patches.py` | Typed native hook recipe, ARM encoding, whole-plan validation and patch provenance |
| `classic_resources.py` | Bounded resource directory/block codecs and native initialization workspace limit |
| `classic_menu.py` | Included-mod records, Mods menu composition and resource-header generation |
| `classic_appearance.py`, `classic_bitmaps.py`, `classic_deltas.py` | Appearance resources, bitmap handling and reversible encoding |
| `classic_preview_artwork.py` | The isolated Now Playing preview binding/layout override |
| `classic_title_clock.py`, `classic_about/title_clock.c` | Native clock views, layout selection and screen title bindings |
| `classic_about/long_audio.c` | Validated MP4 audio chunk seeking and checked sample-table reads |
| `classic_about/boot_report.c` | Bounded early-startup NOR measurement and native SysInfo XML report |
| `classic_about/` | Native resource installer, appearance hooks and linker layout |
| `build_classic.py` | Input qualification, composition, compilation and build artifacts |
| `package_classic.py` | Package only the app's pinned complete release |

Add native hooks to the typed recipe instead of writing directly to the image.
The patcher checks original bytes and complete address spans, rejects overlapping
ownership, and validates the entire plan before applying it to a copy. Its
provenance preserves the existing manifest fields and ordering. An intentionally
shared hook must have one recipe entry, not sequential overlapping patches.

Resolve native resources by directory type/ID, including when payload bytes are
duplicated. Resource extensions preserve the complete stock prefix; explicit
replacements retain their separate meaning. The generated header exports the
workspace bound used by both the Python validator and native scratch allocation.
Do not raise it without rechecking linked RAM use.

Unit tests under `tests/iOpenPod/app/test_classic_*.py` cover codecs, patch rejection,
native resource composition and appearance data without a compiler or device.
ARM probes provide separate native-execution evidence; unit tests alone do not
prove on-device behavior. Runtime image preparation, installation receipts and
transport remain in `src/iOpenPod/app/firmware` and Storage, outside this builder.

The optional `--bootloader-report` mod measures the plaintext NOR bootloader once
before Apple's OS entry, using bounded read-only SPI operations and streaming
SHA-256. It retains 136 bytes and publishes them through Apple's SysInfo XML
writer without hardware reads during USB requests. Host parsing requires current
transport bytes; both the complete loader hash and marker must match before an
update is enabled. It is boot-time firmware evidence, not remote attestation.
See [report evidence](../../docs/research/classic-bootloader-report-2026-11-18.md).

The optional `--long-audio` composition includes **Long Audio Playback** and
**Fast Audio Seeking**. It corrects three 64-bit timestamp comparisons and hooks
only the audio phase of a native seek. It validates tables before changing state,
uses bounded linear table walks and rejects partial window reads. Unsupported
layouts retain the original seek. No heap cache or new timer is allocated.
See [setter/getter audit and native tests](../../docs/research/classic-long-audio-fixes-2026-11-18.md).

The optional `--photo-zoom` mod handles click-wheel events in the full-size
photo browser, pans with a native UI timer while a button is held, and draws
the visible F1024 photo through the native clipped blit. See the
[input, geometry and native tests](../../docs/research/classic-photo-zoom-2026-11-19.md).

The optional `--title-bar-clock` mod places local time in the right corner of
full-width title bars when Apple's **Time in Title** setting is on. Its native
TextView fits the measured time, keeping the preceding status indicator five
pixels away without a fixed-width clock reservation. See the
[layout inventory and native checks](../../docs/research/classic-title-bar-clock-2026-11-19.md).

The optional `--mono-audio` mod adds **Settings → Mono Audio** below Sound Check.
Its default is Off. The common final stereo mixer applies the saved preference to
headphone, analog dock and USB dock playback. See the
[route trace and ARM probe](../../docs/research/classic-mono-audio.md).

### Reproduce a release

Use the pinned prepared `osos.bin` (10,634,496 bytes, SHA-256
`660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e`) and
the original `Firmware-38.9.0.5` member (95,735,808 bytes, SHA-256
`9450c5b51f8785d41c1eef041eac3c7a521d0b325d730f591759b49d041086aa`).
The prepared input contains a 0x800-byte format-2 header around the previously
decrypted Apple body, with its length at offsets 12, 16 and 20. It is not the
encrypted IPSW member or a device's NOR capture. Input hashes and instruction
preimages are checked before patching.

The maintainer build currently uses ARM GNU 13.3.rel1 for Windows:

```powershell
uv run python -m scripts.firmware.build_classic `
  --osos PATH/TO/prepared/osos.bin `
  --firmware PATH/TO/Firmware-38.9.0.5 `
  --compiler PATH/TO/arm-none-eabi-gcc.exe `
  --version 0.12.3-dev --homebrew-eapps --dark-mode --now-playing-artwork `
  --bootloader-report --long-audio --photo-zoom --title-bar-clock --mono-audio `
  --out PATH/TO/new-output-directory
```

The directory must be new. It retains source hashes, compiler version, exact
patches, native symbols and the following artifacts:

- `osos-common.im3`: unsigned schema-2 common OS with CRCs.
- `firmware-common.bin`: common OS plus the latest resource/directory layout.
- `manifest.json`: included-mod records, resource hashes and native addresses.
- `shared-image.json`: common image identities and hardware scope.

The intermediate `osos-about-unsigned.bin` is for native analysis. It is not the
final bootable container. Use `osos-common.im3` with the shared loader.

For a behavior-preserving cleanup, build with the same input, compiler, version
and flags, then compare `firmware-common.bin` with the current bundled release.
Its complete SHA-256 must still match `shared_release.IMAGE_SHA256`; compare the
patch records and generated data too. Source hashes will change, but native
output, included mods and payload/RAM use must not. The 2026-11-18 builder cleanup
reproduced the pinned 0.5.0-dev firmware byte-for-byte, without changing the bundle
or its release identity.

## Layout and installation boundary

The complete member expands the OS slot to **16 MiB**, keeping its start and
resource bank fixed and moving the intact AUPD/hash tail later in the existing
firmware partition. The directory records the new offsets, OS length and applied
AUPD status; Apple's signed NOR updater must not replace the custom loader.

The **Mod Memory Region** starts at `0x08b3c000` and supports **4 MiB total** for
code, constants, initialized data, scratch and BSS. Its actual use is reserved
from Apple's heap, rounded to pages. The current 157,332-byte initialized payload,
scratch and BSS reserve 167,936 bytes (41 pages). Native BSS and exception stacks
retain their original locations. The startup copy handles overlapping buffers
and initializes mod BSS. Oversized builds fail at link time.

Pass repeatable `--mod-source PATH/TO/mod.c` (or `.S`) arguments to link additional
sources. Call or hook the new code explicitly; linking alone does not activate a
mod. Additional source hashes and disk/RAM use are recorded in the build manifest.
Bootloader **2.1.0** must be installed through DFU once, including on Classics
already using 2.0.0. Later builds within these bounds use normal USB updates.
See [expanded-space evidence](../../docs/research/classic-expanded-mod-space-2026-11-17.md).

Before any upload, the installation workflow must check actual firmware-partition
capacity and preserve the device's hash record. The existing normal-mode
finalizer resolves its destination from the newly written directory. Installed
partition bytes therefore contain device-specific state outside the common OS.
No partition table or music filesystem changes are part of composition.

This builder does not send firmware to an iPod. Device Summary now has a separate
Install universal 2.0.5 action, following Install unlocked bootloader.
It uses the normal-USB transport to install the complete shared member. These are
the only firmware actions; both work offline. All four Classic families are enabled
by project-owner direction; physical evidence still covers only family 33.
See the [physical trial](../../docs/research/classic-shared-205-os-layout-2026-11-17.md#physical-family-33-trial).

## Package the runtime release

After building the pinned release, package the complete device-independent image:

```powershell
uv run python -m scripts.firmware.package_classic PATH/TO/firmware-common.bin
```

The packager validates the complete image's length and pinned SHA-256 before writing
`src/iOpenPod/assets/firmware/classic-shared/firmware.zlib` (56,765,941 bytes). The
asset includes the OS, resources and directory. It contains Apple-derived code
and resources and carries a separate notice; they are not covered by iOpenPod's
GPL grant. A new release requires explicitly updating the pinned complete-image
identity in `app/firmware/shared_release.py`.

At runtime, `SharedFirmwareRelease` unpacks this asset with bounded decompression
and checks the complete image. No IPSW, catalog request or network fallback is
involved. The 101,871,616-byte image must have SHA-256
`9656d06f3552da7ad23eef3ed7b994435e9aa92b2e53997e9d254f88522d5b9f`.
It is retained under `firmware/shared/0.12.3-dev/firmware.bin`. A valid cache is
reused; a corrupt cache is rebuilt locally. The first installation also works
offline. The application needs no compiler, firmware-lab checkout,
prepared Apple OS or per-device OS authentication. The Windows installer uses
Storage's retained SCSI Session, journals commands without retries, and completes
after the acknowledged upload and restart request.

See [OS/layout evidence](../../docs/research/classic-shared-205-os-layout-2026-11-17.md),
[bootloader source](../bootloader/README.md) and
[ADR-0281](../../docs/adr/0281-share-classic-os-and-bootloader-artifacts.md) and
[ADR-0282](../../docs/adr/0282-install-shared-classic-firmware-from-device-summary.md) and
[ADR-0283](../../docs/adr/0283-bundle-universal-classic-firmware-and-remove-stock-offers.md).

## Native Light / Dark appearance

`--dark-mode` includes Settings → Appearance, its independent preference,
semantic artwork roles and qualified drawing hooks. It is selected for the
bundled release; omitting it leaves these resources and call sites unchanged.
The native Mods list follows the same composition flag. No external theme files
or startup download are required. See [appearance design](../../docs/research/classic-dark-mode-design-2026-11-17.md)
and [native contract evidence](../../docs/research/classic-dark-mode-native-2026-11-17.md).

The 0.4.2-dev refinement includes Genius/Shuffle skins and custom label hooks,
Calendar day/weekday text, a dark Search field and native fallback artwork.
Its 139 bitmap changes occupy 77,637 compressed XOR bytes. A streaming native
decoder applies these to the original bitmap storage at a mode change, without
allocating an image buffer; rendering does no decompression. Light mode restores
the exact original bytes. See the
[controls audit](../../docs/research/classic-dark-mode-controls-2026-11-17.md).

The 0.4.3-dev **Auto** option selects Light from 07:00 inclusive to 18:00
exclusive, using the iPod's adjusted Firmware Calendar. Its persisted selection
is separate from the effective theme. The existing native clock UI-queue timer
reevaluates it; no new timer, wake request or scheduled preference write is added.
Invalid clock readings retain the effective theme. Native clock conversion,
timer dispatch and compiled policy checks are recorded in the
[Auto audit](../../docs/research/classic-auto-appearance-2026-11-17.md).

## Main-menu Now Playing artwork

`--now-playing-artwork` includes **Now Playing Preview Artwork** in Extras → Mods.
It binds the main-menu preview image to Apple's current Now Playing artwork
source while retaining its title, artist and album. The native model supplies
artwork loading, fallback images and track-change notifications; the mod does
not add another decoder or artwork cache. It is independent of appearance.

The original main-menu action always selects the layout named
`NoNowPlayingArt`. That layout normally binds a static proxy. This mod changes
its image binding and unique layout, without replacing the controller or player
behavior. Native 128 × 128 artwork sits at x176/y35 with a seven-pixel gap above
the title. No resampling is required. Two resources and the new Mods entry add
596 initialized payload bytes and 532 registered resource bytes versus 0.4.3-dev;
the 110,592-byte page reservation is unchanged. See
[native geometry, cache and refresh evidence](../../docs/research/classic-now-playing-preview-artwork-2026-11-18.md).

Version 0.6.2-dev additionally replaces the base BitmapView visibility callback
for dynamic `Draw` sources. It frees only the view's borrowed drawing context
on hide/show, then uses Apple's loading/repainting path. Static resources retain
their cache. This adds 108 initialized bytes and no retained state or pixel buffer;
that release's 114,688-byte reservation is unchanged. The cache-replacement replay
and 512 lifetime cycles pass; the user reports that the Cover Flow issue is mostly
fixed. See [lifetime regression evidence](../../docs/research/classic-menu-artwork-lifetime-2026-11-18.md).

Version 0.6.3-dev adds `Draw/0x7f05` to appearance-change notifications so an
attached Now Playing preview also refreshes its borrowed context. It adds 20
initialized bytes, no retained state and no additional reserved RAM. Native
manual/Auto switch tests pass; the remaining Dark → Light failure still needs
physical validation. See [appearance refresh regression](../../docs/research/classic-appearance-artwork-refresh-2026-11-18.md).

Version 0.6.6-dev also wraps the exact Now Playing model's `Draw/0x7f05` getter.
It follows Apple's retained-thumbnail loading recipe with an additional null
resource check, using the model's existing reference and artwork ID. Repeated
queries reuse one 128-square RGB565 thumbnail; track changes replace it through
native reference counting. Video keeps the original live-frame provider. The
captured flat-buffer replay fails on 0.6.5 and passes on this build; it does not
emulate the full Podcasts UI. See [retention evidence and limits](../../docs/research/classic-artwork-diagnostics-2026-11-18.md#retained-thumbnail-candidate-066-dev).

Version 0.6.7-dev replaces the format read at `0x081001f0` with `artwork.S`'s
qualified instruction hook. For `Draw/0x7f05` only, it reads the current context's
bitmap format instead of the embedded static bitmap format. This keeps color
artwork out of mask mode after the embedded format becomes stale. Real masks,
static sources and other properties preserve their original behavior. The hook
does no allocation or image write; total reserved RAM stays unchanged. See
[physical capture and native regression](../../docs/research/classic-now-playing-render-mode-2026-11-18.md).

## Unsigned eapp manifests

`--homebrew-eapps` selects the native unsigned reader at the game-manifest
call site. It changes one ARM instruction, verifies the original bytes, and
records `org.iopenpod.homebrew` version `0.1.0-dev` in build provenance. It does
not change executable Verify/DRM checks or the bootloader. Omit this option
for a control build with Apple's signed-manifest requirement. The exact release
and native-code verification are recorded in the
[homebrew evidence](../../docs/research/classic-homebrew-eapp-manifests-2026-11-17.md).
Physical game launch is still untested.

## Native Mods menu

`classic_menu.py` generates **Extras → Mods** from `included_mods()`, the same
records stored in both build manifests. It lists the independent version string,
About row, unsigned game manifests, and menu itself. A control build without
`--homebrew-eapps` omits that mod from the list as well as omitting its patch.
Rows are read-only. The stock Games template also owns the gear image child,
so the native ROM iterator registers it. Highlighting Mods makes the gear
visible in the preview pane. Returning to Games restores the dice and count.
Pressing the center button on Mods opens the native full-width list.

Resource cloning and event encoding adapt the GPL-3.0-only UI compiler in
[osos-lab](https://github.com/lgreitis/osos-lab/tree/d2c8e357d58591bdaa70bb6be9da191f489554a6/patching/ui).
There is no runtime or build dependency on that checkout. See
[native menu evidence](../../docs/research/classic-mod-menu-2026-11-17.md) for
addresses, verification, limitations and the remaining physical check.

## Optional artwork diagnostics

The current bundle omits `--artwork-diagnostics` after the user confirmed the
drawing-mode correction on 0.6.7-dev. This removes all artwork trace hooks,
snapshot state and XML fields, while preserving the functional artwork fixes
and Bootloader Report. The flag remains available for developer builds, off by default,
and requires both preview artwork and boot reporting. It adds bounded native
view/source snapshots to normal USB SysInfo without image buffers, timers or
device-file writes. See [diagnostic schema and evidence](../../docs/research/classic-artwork-diagnostics-2026-11-18.md).
