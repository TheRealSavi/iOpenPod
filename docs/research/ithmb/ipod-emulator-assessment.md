# ipod-emulator as an iTHMB research instrument

Research date: **2026-10-11**. This is a **source review**, not an independently
booted or validated emulator. No emulator was run and no firmware was downloaded.
Sources below are pinned to `siggifly/ipod-emulator` commit
[`d39e850ac07baa28abbdd8b00b77b834a757b5e1`][revision]. Upstream measurements remain
upstream reports, even where the implementation agrees with their description.

Subsequent installation and local runs are recorded separately in
[Local iPod emulator experiments](ipod-emulator-experiments.md). This assessment
retains its original source-review scope.

A later [Classic feasibility assessment](classic-emulator-feasibility.md)
compares the different CPU/peripheral platform and identifies a separate QEMU
Classic implementation. Its documented playback limitations remain material to
timed-artwork research; its existence does not extend this Video emulator's scope.

## Assessment

The project is a promising instrument for tracing the **iPod Video 5G/5.5G
firmware's artwork reader**. It is not yet an independent oracle for physical
display behavior. Its boot research reports genuine Apple RetailOS execution,
while its VideoCore model supplies synthesized service replies and copies surfaces
to the emulated panel itself. The useful boundary is therefore the Apple ARM code
and its input/output buffers **before** the synthetic display service. This is an
assessment of suitability, not evidence that an ArtworkDB fixture has already
worked. [Boot matrix][matrix], [VideoCore implementation][video].

It cannot directly settle the F1061 dispute in issue #178. iOpenPod's current
catalog assigns the Video generations cover formats **1028 and 1029**; the reported
F1061 observations concern Classic and nano devices. Successful Video emulation
would provide a useful additional firmware sample, not validate another family's
format interpretation. [iOpenPod catalog][catalog], [issue evidence](issue-evidence.md),
[upstream scope and future devices][roadmap].

## What executes, and what is supplied

| Layer | Evidence at the reviewed revision | Consequence for artwork research |
| --- | --- | --- |
| Apple RetailOS | The project reports boots of Apple firmware, including `iPod_20.1.3` and `iPod_25.1.3`; the latter required a corrected generated firmware-partition layout. [Boot matrix][matrix], [fixed drive-builder defect][drive-fix]. | A traced parser decision can be evidence about the exact firmware bytes run. Reaching a menu does not establish artwork coverage. |
| Original Apple bootloader | A real NOR dump supplies Apple's loader and diagnostics. [README][readme]. | Use a matching real dump when investigating behavior that depends on Apple's actual initialization. |
| Synthetic NOR | `nor.rs` says that Rust supplies initialization, the handoff block, OS loading, and the jump. Its generated reset vector is not executed; the image principally supplies identity data. [NOR implementation][nor]. | A synthetic run executes genuine OS code after an emulated boot handoff. It is not evidence that Apple's bootloader accepted that model/firmware pairing. |
| VideoCore / BCM2722 | `Bcm` models the host protocol, not a VideoCore CPU running `vmcs.bin`. The reply handler allocates handles/surfaces; `show_surface` copies RGB565 rows at the supplied pitch and clips to the panel. [VideoCore implementation][video]. | A correct-looking screenshot can conceal an unsupported coprocessor operation, compositing rule, or timing dependency. Inspect the ARM-produced pixels and service requests separately. |
| Other shortcuts | The active ledger retains synthesized BCM replies, a supplied boot handoff remap, and a constant audio sample rate. GUI clock adaptation is separate from the explicitly pinned CLI clocks. [Active bypass ledger][ledger]. | Record the front end, boot path, clock, and active flags; do not compare runs with different initialization or timing as though only the artwork changed. |

The BCM limitation is specific, not a claim that the whole display is invented.
The code receives firmware-generated surfaces, but services them with its own
allocator and presenter. The ledger also identifies synchronous replies and
chosen service values; its later hardware measurements show that the real
handshake register changes state where the model returns a fixed ready value.
Those measurements were made under Rockbox, so they do not establish the complete
RetailOS VideoCore service directory. [Reply/presentation code][video],
[display assumptions][display-assumptions], [hardware addendum][bcm-hardware].

## Coverage and provenance limits

The **197 model rows** and **66 retrievable firmware releases** advertised in the
README describe identity/catalog and download coverage. They are not a matrix of
197 emulated devices or 66 validated boots. The boot research centers on real and
synthetic Video 5G/5.5G configurations; the roadmap distinguishes known models from
models that boot and leaves nano/Classic expansion as future work.
[README][readme], [boot matrix][matrix], [roadmap][roadmap].

The boot matrix is a chronological laboratory notebook with retractions and
superseded tables. Its final September 23 addendum reports a physical 30 GB 5.5G
with firmware 1.3 and `HwVr = 0x000B0011`, correcting the earlier conjecture
`0x000B0010`; the reported NOR matches the reference 5G outside its identity page.
That is evidence about those sampled units, not all capacities, revisions, or
firmware versions. [Final hardware addendum][hardware-addendum].

Version matters. The latest published release observed on the research date was
**v0.4.0, published August 17, 2026**; the reviewed source declares **0.5.0** and
contains later fixes. Reproducing a current source claim with the older release
would confound the experiment. Documentation can also lag code: the README calls
WM8758 entirely unmodeled, while current source implements a codec register
recorder. This does not establish audible playback; it shows why current code and
dated addenda must accompany broad README claims. [Release][release],
[workspace version][version], [README][readme], [codec recorder][codec].

USB is not implemented, so this is not an iTunes-over-USB compatibility test.
The project does provide file injection into FAT32 images, memory/register/read
tracing, and panel captures. Its known-bugs document also records an animated GIF
encoding artifact that was absent from raw frames. Use raw pixel dumps or lossless
frames for comparisons. [README][readme], [development tools][developing],
[capture artifact][gif-bug].

## Proposed first experiment

This is a proposed protocol, **not a completed measurement**. The existing image
injection and tracing tools make it plausible, but locating the artwork parser and
following its file reads may require additional instrumentation.
[Development tools][developing].

1. Pin the emulator commit, build, exact Apple firmware/resource hashes, NOR origin
   or synthetic recipe, disk image hash, boot mode, clocks, and flags. Work only on
   disposable image copies; retain an immutable starting image.
2. Establish a positive control with a small, known-working **Video** library:
   matching iTunesDB, ArtworkDB, and F1028/F1029 files. Include asymmetric corner
   markers, row/column gradients, and solid colors. First prove that the firmware
   reaches the relevant artwork screen and actually reads the fixture.
3. Trace ArtworkDB parsing and iTHMB ranges into ARM memory. Record which filename,
   offset, length, dimensions, and padding fields influence reads and decoded
   pixels. Capture the pixels before upload, the BCM request payloads, and the
   final lossless panel image as separate observations.
4. Change one property per copy: row padding, visible dimensions, neighboring slot
   contents, MHNI length/allocation, or a second shard reference. Keep a control
   that changes nothing. A display failure alone cannot identify the responsible
   field; corroborate it with the trace and the last successful processing stage.
5. Repeat a useful result with an independently prepared fixture, then on a
   physical Video device with recorded firmware. Test additional firmware builds
   separately. A future Classic/nano experiment needs a demonstrated implementation
   of those devices before it can address F1061.

Report conclusions in three layers: **this firmware read/produced these bytes in
this emulator**, **this emulator displayed these pixels**, and **this physical
device displayed the same fixture**. Agreement across those layers increases
confidence; none permits silently generalizing to all devices sharing a model
name or format ID. This follows the dossier's existing
[evidence standards](validation-and-open-questions.md).

[revision]: https://github.com/siggifly/ipod-emulator/commit/d39e850ac07baa28abbdd8b00b77b834a757b5e1
[readme]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/README.md
[matrix]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/research/17-the-boot-matrix.md
[roadmap]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/ROADMAP.md#after-10
[nor]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/nor.rs#L7-L52
[video]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/hw/video.rs#L585-L672
[ledger]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/research/04-bypass-ledger.md#L27-L56
[display-assumptions]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/research/04-bypass-ledger.md#L125-L280
[bcm-hardware]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/research/04-bypass-ledger.md#L993-L1051
[hardware-addendum]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/research/17-the-boot-matrix.md#L1188-L1232
[drive-fix]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/KNOWN-BUGS.md#L57-L103
[release]: https://github.com/siggifly/ipod-emulator/releases/tag/v0.4.0
[version]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/Cargo.toml#L20-L26
[codec]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/hw/wm8758.rs#L1-L19
[developing]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/docs/DEVELOPING.md#L71-L138
[gif-bug]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/KNOWN-BUGS.md#L2193-L2209
[catalog]: https://github.com/TheRealSavi/iOpenPod/blob/b246a6c26c1402c79b690febdcb914862ce0a8bc/src/device_registry/data/catalog.py#L245-L261
