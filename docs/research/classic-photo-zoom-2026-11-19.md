# Classic 2.0.5 photo zoom and pan

Mod Platform Version **0.10.0-dev** includes **Photo Zoom and Pan 0.3.0-dev**.
The user controls are documented in [Firmware mods](../firmware-mods.md).
Magnification samples the native 720 × 480 F1067 rendition when available,
with the 320 × 240 F1024 LCD rendition as a fallback. F1066 is the 64 × 64
thumbnail; earlier versions of this mod magnified F1024, not F1066.

## Input and navigation

The stock `PhotoBrowse_Large` layout (`SEVT 0x0dad0a58`) maps Center and
Play/Pause releases separately to `HandleBrowseSlideshow`. The template event
for Menu invokes `HandleBrowseSmall` and pops the screen. In full-size browser
mode the mod consumes the requested physical inputs before those actions run.
The two Photos controller event slots are `0x089956d0` and `0x0899fe8c`.
The original dispatcher handles normal browsing, including Play/Pause at fit
after the user leaves zoom mode. Album grids and slideshows use other model modes.

Version 0.9.0-dev enters zoom/pan on Center release. While active, Center pans up
using physical switch bit 0. Menu release resets a changed view or exits at fit.
Menu presses, holds and repeats are consumed, so only the physical release resets
or exits. Right, left and down retain their existing physical switch bits.

### Physical Center release

The user reported that Center started a slideshow after installing 0.8.0-dev.
The completed Host installation record identified that release and matched the
bundled image hash. The original button fixture supplied phase 7 as a release.
On the Classic, the switch producer at `0x08192538` emits `kDwn` for the press
and the space-padded `kUp` for the release. The native message table at `0x083e4980` constructs
phases 6 and 13 for these messages. Phase 7 comes from `kAut`, the auto-repeat
message. The stock button formatter gives phases 7 and 13 the same event name.
The 0.8.0-dev hook passed phase 13 to the stock Center slideshow action.

Version 0.8.1-dev toggles or resets zoom on phase 13 and consumes Center
auto-repeats. A directional release finishes the elapsed pan interval and
cancels the timer. Directional auto-repeats allow the hold to continue.

The native wheel report decoder at `0x0805f684` records angular position and
the five physical switches. The accumulator at `0x08093718` unwraps 96 positions
per revolution. The event reader at `0x08289490` obtains relative motion,
contact serial and angle together. The mod uses angle differences within a
contact and relative motion to resolve coalesced turns. A lifted finger can
touch down elsewhere without introducing a jump. Each physical position changes
magnification by 1/96 of the fitted size. Four clockwise revolutions reach 500%.

A directional button-down arms a 25 ms one-shot timer owned by the native
Photos model. The model handles its event at `0x08995724`. Elapsed microseconds
determine distance at **one screen pixel per 5 ms**. Fractional time carries
between callbacks, including across clock wrap. Button-up applies the last
partial interval and stops the timer. Each callback checks the physical switch
bits so a lost release also stops motion. The native controller transition and
full-size view entry discard the session, and album and photo identity scope
the zoom to its current photo.

## Drawing

The renderer follows the Photos model's `Rect/0x8482` lookup to the selected
album's F1024 dimension getter. The native getter reads the content dimensions
from the photo's rendition record. These dimensions distinguish LCD padding
from black pixels belonging to the photo. When the record is unavailable, the
renderer uses the stock blit and retries the lookup on the next paint. Each axis
stays centered while the magnified image fits and stops at the image edges once
the image fills that axis.

On 0.8.1-dev the user confirmed Center entered and exited the mode, but the
displayed image stayed at fit. That release hooked the ImageView blit at
`0x080f76c4`. The offline fixture also selected that ImageView directly, so it
missed the failure on the full-size screen.

The bundled `PhotoBrowse_Large` screen layout selects `SSin 0x168` and
`View 0x0dad0a3c`. Its single `imag` control uses the native factory at
`0x081943ec`, which constructs a BitmapView. The layout binds the control to
the Photos model's current image through `SORC 0x5df` (`Draw/0x8482`).
The control is untiled. Its paint method at `0x0810012c` submits the bitmap at
`0x081002e4`. Version 0.8.2-dev intercepts that call for the current Photos
bitmap during magnification. It samples the current photo into an eight-row
RGB565 strip and submits it through Apple's existing clipped blit. Fit uses the
native image directly. The strip and column map occupy 5,760 bytes, independent
of magnification. The complete build reserves 126,976 bytes of mod RAM, two
4 KiB pages more than 0.7.0-dev.

A 20 × 20 pixel magnifier tile appears four pixels from the bottom and right
screen edges while the mode is active. Its white glyph and charcoal background
are drawn through the native clip after the photo. It reuses the render strip
and requires no extra pixel allocation. Entry and exit invalidate the screen
even at 100%. Reset keeps the tile visible. The indicator also appears when
photo dimensions are temporarily unavailable.

## Offline qualification

The firmware lab's `scripts/probe_classic_photo_zoom.py` runs the built ARM code,
the photo controller, native wheel decoder, timer insertion and cancellation,
album dimension getter, BitmapView paint and clipped color blit. Fixtures provide
wheel reports, rendition records and patterned RGB565 photos. A
controlled clock and event delivery make regular and delayed holds repeatable.
The button regression feeds raw switch bits to the native wheel decoder and
button driver. It delivers their messages through the native UI task and both
Photos controller types, and observes the stock slideshow player entry. The
fixture supplies the loaded layout's action lookup from its bundled SEVT bytes.
The display regression resolves the bundled screen, constructs its view through
the registered factory and loads its bitmap through the Photos property getter.
The test window accumulates damage through the native invalidation routine.
The simulated display pump dispatches that damage through the view's paint
method and the native window surface attachment. On 0.8.1-dev a full clockwise
turn reaches 200% in memory and queues a repaint, but the displayed pixels stay
at fit. On 0.8.2-dev the same wheel samples magnify the displayed pixels.
At 200%, each physical direction moved the viewport exactly 25 pixels during a
125 ms hold and two more pixels in the last 10 ms before release. Every pixel
matched the expected viewport. Play/Pause starts the slideshow after exit.

```powershell
uv run ../ipod-firmware-lab/scripts/probe_classic_photo_zoom.py --build PATH/TO/build
```

All 77 full frames matched an independent pixel reference across 320 × 240,
119 × 240, 320 × 91 and 1 × 240 images. A separate dirty-rectangle test checked
the pixels inside the clip and every surrounding pixel. Input cases included
clockwise and counterclockwise revolutions across zero, lift and retouch,
two coalesced revolutions, irregular timer intervals, four sustained edge hits,
release, a missing release, late delivery after leaving, and Menu reset/exit.
Physical Center holds pan upward through both controller types. The tests check
every indicator pixel at fit and while zoomed, repeat handling on Menu, complete
removal on exit and a dirty rectangle crossing the icon.
The renderer also recovered when a missing rendition record became available.
An unrelated bitmap drawn through the same call kept its original pixels during
an active pan. The photo-only and artwork-diagnostics builds passed the same
display tests. Now Playing artwork tracing also passed on the combined diagnostic
build. The boot-report and relocation checks passed on the assembled release.

The prepared input SHA-256 is
`660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e`.
The complete bundled image is 101,871,616 bytes with SHA-256
`eeac9095f05ca7d1077075cf9d805899cc0cf0d317fe105275c8a856943892a9`.
On-device controls, loading performance and LCD output on 0.10.0-dev await confirmation.

## Higher-resolution source in 0.10.0-dev

The native format factory at `0x080fad18` maps selector 3 to F1024 and selector 5
to F1067. The latter is a 720 × 480 planar I420 buffer: 345,600 luminance bytes,
86,400 Cb bytes and 86,400 Cr bytes. Its descriptor reports a 1,080-byte row size,
12 bits per pixel and format tag `0xc420`. This agrees with the host's existing
F1067 catalog entry and I420 decoder. The stored row size includes chroma;
the individual Y rows contain 720 bytes. Conversion uses limited-range BT.601.

Photos registers selector 5 at `0x081c2ca8`. The full-size browser's cache
configuration previously requested selector 3 alone. The qualified instruction
at `0x081c23bc` now passes 5 as the secondary selector instead of -1.
The native configuration layers at `0x08221550` and `0x081e6938` reach the policy
constructor at `0x08212188`, which appends selectors 3 and 5 in order. Other
browser modes keep their existing cache configuration. This uses Apple's cache
and background loader; the paint hook performs no direct file read.

Each magnified paint acquires selector 5 for the current album index through
`0x0822178c`. The native reference is retained until the final strip has been
copied, then released through `0x08393de0`. The readiness check at `0x08277508`
accepts states 4 and 5. Native image methods `0x080f9bf4` and `0x080f9c5c` return
the surface and format. The surface's buffer accessor `0x08181154` returns the
pixel pointer and actual byte length from its native memory block. The hook
requires a complete 518,400-byte buffer, the expected descriptor and valid
F1067 content dimensions from the album. Missing, pending, malformed or
unavailable entries fall back to F1024, with another lookup on the next paint.
No source pointer survives a paint or bypasses the native reference lifetime.

The viewport and pan limits continue to use the fitted LCD content dimensions.
Sampling maps that viewport into the high-resolution content rectangle, excluding
its centered padding. This preserves the displayed proportions even when TV and
LCD renditions have different pixel aspect ratios or rounded dimensions. Fit
still uses Apple's original LCD blit. The eight-row RGB565 strip is reused for
I420 conversion, so there is no additional mod-owned full-image buffer. Apple's
cache holds the additional rendition. The release reserves 131,072 bytes of mod
RAM, one 4 KiB page more than 0.9.0-dev, for the larger compiled payload.

The lab's `scripts/probe_classic_photo_highres.py` runs the patched caller,
native configuration layers and cache-policy constructor, observing ordered
selectors `[3, 5]`. Raster tests run the native image virtual methods, readiness
check, memory-block buffer accessor, reference release and BitmapView blits;
fixtures supply only cache entries and photo records. Thirty-three frames cover
200% and 500%, padded and full-width TV rasters, portraits, panoramas, narrow
images and every held-pan edge. Each output pixel is compared with an independent
decimal BT.601 reference within integer-conversion and RGB565 quantization limits.
Dirty rectangles preserve every surrounding pixel. Cache references remain pinned
through all 30 strip blits and return to their original count after each paint.
Missing records, pending states, null surfaces/pixels, short buffers, invalid
dimensions and wrong descriptors select the LCD fallback. Newly available and
replaced cache buffers affect the next paint without resetting zoom.

```powershell
uv run ../ipod-firmware-lab/scripts/probe_classic_photo_highres.py --build PATH/TO/build
```

The original 77-frame control/display suite also passes with no F1067 available.
Boot-report startup, overlapping relocation, mod/native BSS and expanded firmware
directory checks pass on the complete release. These are offline results;
physical loading latency and pan frame rate remain unmeasured.
