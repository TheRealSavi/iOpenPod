# Classic firmware emulation feasibility

Research date: **2026-10-11**. Source inspection only: no emulator was launched,
no firmware was downloaded, and no physical iPod was modified for this assessment.

## Assessment

Running Classic 120 GB firmware is plausible, but adapting the installed
`siggifly/ipod-emulator` would require a new machine implementation. Similar menus
do not imply similar hardware. The installed revision models the PortalPlayer
Video family; Rockbox assigns the Classic to Samsung S5L8702 and compiles it for
ARM926EJ-S. [Installed machine][machine], [CPU core][cpu],
[Classic configuration][rb-config], [Classic compiler target][rb-build].

Our positive timed-artwork experiment used **`iPod_20.1.3.ipsw`** with a synthetic
boot handoff. It must not be relabeled as a tested 5.5G firmware result merely
because the emulator supports that generation too. The upstream catalogue lists
the enhanced Video family separately as `iPod_25.*`, and the 120 GB Classic as
`iPod_33.*`. Catalogue entries establish known download identities, not executable
machine support. [Local experiment](ipod-emulator-experiments.md),
[Pinned firmware catalogue][catalogue].

## What changes at the hardware boundary

| Area | Installed Video emulator | Classic requirement/evidence |
| --- | --- | --- |
| Processor | ARM7TDMI interpreter, explicitly ARMv4T, no MMU and only a coprocessor stub. [Core][cpu]. | Rockbox selects ARM926EJ-S; its startup accesses CP15 cache/control operations. A compatible CPU and control-state implementation is required. [Build][rb-build], [Startup][rb-start]. |
| Machine | PortalPlayer bus with ATA DMA, PCF50605 power chip, Wolfson WM8758 and BCM video service model. [Machine imports][machine]. | S5L8702 interrupt, clock, timer, memory and peripheral interfaces. Rockbox selects different I2C, LCD and CS42L55 audio hardware. [Configuration][rb-config], [Startup][rb-start]. |
| OS entry | Our lab supplies a Video boot handoff and loads Video OS bytes. [Experiment](ipod-emulator-experiments.md). | A Classic OS image and its expected initialized memory/peripheral state; the reviewed Classic QEMU implementation has a separate handoff routine. [Classic machine][qemu-machine]. |
| Playback fidelity | Existing lab evidence is one Video firmware configuration. | A Classic menu alone would not validate playback position, chapter selection or artwork scheduling. These need independent controls and physical comparison. |

**Engineering inference:** the reusable parts include fixture generation, FAT
images, captures and experiment bookkeeping. Replacing the CPU alone is
insufficient; firmware also depends on the new memory map and peripherals. This
is an emulator port, with no defensible completion estimate from this inspection.
Upstream itself places Samsung devices in later work. [Hardware scope][hardware].

## A more relevant existing implementation

Source inspection found [davidmonterocrespo24/qemu-ipod-classic][qemu-readme], pinned
here at **`1c33be87c7e97b56053142ae9d7f0686feaed504`**. Its machine source selects
QEMU's ARM926 CPU and implements a distinct Classic memory map and boot handoff.
This is concrete emulator code, although we have not built or reproduced its
results. [Machine implementation][qemu-machine].

The author reports Apple RetailOS navigation and a Now Playing display. The
documented setup needs a decrypted Classic `osos` image; the documented acquisition
chain uses physical hardware and emCORE. No such installation or extraction has
been attempted here. Their example uses `Firmware-24.9.1.2`, which does not establish
compatibility with the user's 120 GB firmware. [README][qemu-readme].

Most relevant to this investigation, the project's playback report says the
**guest elapsed-time display remains at 0:00**, pause cannot resume, and track
changes fail. MP3 decoding is supplied by the Host. These are unresolved problems
in the very playback path that a timed-artwork experiment would exercise. A
failure to change images there would be inconclusive. [Playback report][qemu-player].

There is also an optional `HLE_NP_OVERLAY` implementation that draws a Host player
over the framebuffer. Its own comments identify it as a substitute UI. It must
remain disabled when studying firmware display behavior; screenshots alone are
insufficient unless all such options are recorded. [Overlay implementation][overlay].

## Recommended next steps

1. Resolve the current artwork question on the working physical Classic using
   controlled media-category and artwork-view comparisons. Chapter navigation now
   working is a useful independent observation, not proof that its image path
   shares the same conditions.
2. If Classic emulation is pursued, audit and reproduce the existing QEMU Classic
   target before building a second S5L8702 implementation inside the Video emulator.
3. Require a baseline where the actual guest playback position advances and a
   known working chapter/artwork sample behaves like physical hardware. Then trace
   the firmware's ArtworkDB selection and image reads. Keep the exact firmware,
   boot handoff, media codec, media category, display view and emulation shortcuts
   in every experiment record.

These are proposed experiments, not completed tests. This assessment does not
establish that Classic timed artwork is limited to podcasts or audiobooks, or that
ALAC is excluded.

[cpu]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/arm7tdmi/src/lib.rs
[machine]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/lib.rs
[hardware]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/HARDWARE.md
[catalogue]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/firmware.rs
[rb-config]: https://github.com/Rockbox/rockbox/blob/b819e910007795e51bf2a3d429574be7d52c4827/firmware/export/config/ipod6g.h
[rb-build]: https://github.com/Rockbox/rockbox/blob/b819e910007795e51bf2a3d429574be7d52c4827/tools/configure
[rb-start]: https://github.com/Rockbox/rockbox/blob/b819e910007795e51bf2a3d429574be7d52c4827/firmware/target/arm/s5l8702/crt0.S
[qemu-readme]: https://github.com/davidmonterocrespo24/qemu-ipod-classic/blob/1c33be87c7e97b56053142ae9d7f0686feaed504/README.md
[qemu-machine]: https://github.com/davidmonterocrespo24/qemu-ipod-classic/blob/1c33be87c7e97b56053142ae9d7f0686feaed504/hw/arm/ipod_classic/ipod_classic.c
[qemu-player]: https://github.com/davidmonterocrespo24/qemu-ipod-classic/blob/1c33be87c7e97b56053142ae9d7f0686feaed504/wiki/20-classic6g-reproductor.md
[overlay]: https://github.com/davidmonterocrespo24/qemu-ipod-classic/blob/1c33be87c7e97b56053142ae9d7f0686feaed504/hw/arm/ipod_classic/ipod_classic_np_overlay.c
