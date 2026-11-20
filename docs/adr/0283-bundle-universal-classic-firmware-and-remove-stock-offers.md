# ADR-0283: Bundle universal Classic firmware and remove stock offers

- Status: Accepted
- Date: 2026-11-17
- Supersedes: ADR-0282's resource download and OS-only asset; ADR-0230's stock firmware offers

Offer exactly two firmware workflows in Device Summary: **Install unlocked
bootloader** and **Install universal 2.0.5**. These install the Universal Unlocked
Bootloader 2.0.0 and Universal Classic Firmware 2.0.5, with Mod Platform Version
0.2.0-dev, respectively. Universal means Classic updater families 24, 33, 35 and
38; it does not include other iPod families. The guided DFU, selected-device
binding, normal-USB upload, no-replay receipts and post-boot confirmation from
ADR-0282 continue unchanged.

Remove Apple's firmware catalog, stock Restore/Update buttons and package
downloader from the application. Opening Device Summary makes no firmware
network requests. The observed updater family and current firmware version
remain visible for device identification. Research documentation and offline
stock-image qualification utilities retain the evidence behind the transport;
they do not constitute additional product actions.

Package the complete previously tested firmware member, including the common OS,
resources and directory, as `assets/firmware/classic-shared/firmware.zlib`.
Its 56,692,489 compressed bytes replace the earlier 3,932,558-byte OS-only asset.
The decompressed image remains 95,735,808 bytes with SHA-256
`05b1d49671a42f190ed7f8bbd62c2f8b38e54749cb8261c39904dbef851ecff4`.
The maintainer packager accepts only that pinned release; it does not accept an
arbitrary firmware image for distribution.

Preparation uses bounded decompression, checks complete framing and the pinned
length/hash, and retains the image in the existing persistent Host cache. An
intact cache is reusable; a damaged cache is rebuilt from the bundle. When the
bundle is needed, a missing or damaged asset fails locally, with no network fallback. A fresh installation
with an empty cache therefore works offline. Existing downloaded IPSWs remain
user data but are no longer read by either workflow. No device-specific signed
header, identity or secret is distributed in the firmware image.

The distribution is roughly 53 MB larger in exchange for being independent of
Apple's firmware servers from first use. The complete image contains Apple code
and resources, which retain their ownership and are excluded from iOpenPod's GPL
grant by the asset notice. This changes packaging and presentation, not the
tested bootloader/OS executable bytes or the scope of physical validation.
