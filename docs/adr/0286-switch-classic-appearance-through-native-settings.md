# ADR-0286: Switch Classic appearance through native Settings

- Status: Accepted
- Date: 2026-11-17

Provide **Settings → Appearance → Light / Dark / Auto** as a native controller action
and inline value, placed after Brightness. Default to Light and retain Apple's
original version. Record the included mod in Extras → Mods. The setting is
independent of the desktop application's appearance.

Compile the theme into the hash-qualified shared 2.0.5 OS. Use explicit native
bitmap roles, original dark-status artwork where appropriate, and qualified
foreground, shadow, selection-gradient, fill and reflection call sites. Preserve
photographs, user album artwork, games and coverage masks. The Settings calendar
illustration remains light paper with black ink. Do not implement a
final-framebuffer inversion or a global color-setter hook.

Embed compressed reversible byte deltas against original bitmap storage. Keep bitmap
geometry and native allocations intact; indexed status counterparts may change
palette entries and index bytes inside the original allocation. Apply changes on
the native Settings/UI thread. Routine rendering performs no theme-file I/O,
allocation or decompression. Restore original bytes when returning to Light.
Extend the native selection bitmap's rectangle-only cache comparison with the
current appearance, without changing its owner pointers or allocation metadata.

The firmware owns a separate, versioned 12-byte
`iPod_Control/Device/iOPAppearance` preference. Validate its magic, mode and
complement. Missing, invalid and short records select Light. Write, close and
read back the new record before changing the displayed mode; show **Not saved**
on failure and retain the active mode. Apple's file wrappers discard some
flush/close errors, so this is not a power-loss durability guarantee. This native
firmware preference does not add a desktop device-write path outside Storage.

Use sRGB contrast after RGB565 quantization as a design check: primary/secondary
text on main surfaces targets 7:1, selected text at least 4.5:1, and the selection
fill at least 3:1 against the list. These are engineering benchmarks, not a claim
of calibrated physical-LCD accessibility conformance.

The build remains optional via `--dark-mode`. Include it in 0.4.0-dev using the
expanded Mod Memory Region and existing bootloader 2.1.0 requirement. Native
instruction tests and resource previews establish offline evidence; physical
visual validation remains a separate step.

The 0.4.1-dev refinement keeps native coverage-mask bytes intact and tags only
the connected-screen sync-arrow tint. A qualified BitmapView draw hook resolves
that cached tag for the active appearance. Untagged clock/battery overlays retain
their native colors. Tagged light-paper text retains its native embossed shadow
if a layout requests one. Current Search/date-paper descriptors do not enable
embossing; this is a context rule, not a confirmed visible defect in those layouts.

The 0.4.2-dev amendment follows physical user feedback: the Search field and
built-in media/search/missing-cover placeholders now receive dark surfaces.
This replaces the earlier decision to preserve these as light illustrations.
Retain native symbol geometry and shading, independently of personal artwork.
Calendar grid numbers and weekday labels, Genius labels and Shuffle options
have qualified draw hooks; they bypass the ordinary TextView path. The selected
Shuffle label needs light ink on its blue thumb. Search returns to the ordinary
cached text color and drawing hook. Only the Settings calendar paper keeps the
light-surface exception.

Store artwork XOR differences as literal, repeated-byte and repeated-word
packets, decoded directly into the original resource storage at startup or a
mode change. This reduces static RAM for RGB565 placeholders without allocating
an uncompressed delta buffer. The trusted packets are generated from qualified
inputs and tested against the native decoder. Rendering does no packet decoding.

The 0.4.3-dev amendment adds **Auto**, cycling Light → Dark → Auto → Light.
Keep the selected policy separate from the effective Light/Dark render state.
Auto uses the iPod's adjusted **Firmware Calendar**, with Light from 07:00
inclusive to 18:00 exclusive and Dark at all other valid times. An unavailable
or invalid calendar retains the effective theme until a valid reading arrives.
Default remains Light. The existing preference accepts mode 2 for Auto;
previous mode 0/1 records retain their meaning. Scheduled transitions do not
rewrite preferences, and manual modes perform no automatic clock reads.

Reuse the native clock model's UI-queue timer delivery for reevaluation,
preserving its original handler and scheduling. Do not introduce a new wake
timer or modify bitmaps from hardware-clock callbacks. Read the actual current
calendar at each Auto tick, including after sleep or a manual clock change.
Notify the current Settings preview and playback models and invalidate the
root only when the effective theme changes. Borrow current model references
for each notification; do not retain controller pointers across their lifetimes.

See [native contracts](../research/classic-dark-mode-native-2026-11-17.md) and
[theme design and validation](../research/classic-dark-mode-design-2026-11-17.md).

The 0.6.1-dev correction includes the World Clock row gradient in the existing
surface role. Preserve its alpha and index plane and the separate day/night face
and hand artwork. Native cached rendering observes the in-place palette change
without another cache or allocation; total reserved RAM is unchanged. See
[clock-row regression evidence](../research/classic-dark-mode-clocks-2026-11-18.md).
