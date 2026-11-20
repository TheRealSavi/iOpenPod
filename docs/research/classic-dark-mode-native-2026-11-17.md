# Classic 2.0.5 appearance control and native rendering evidence

Date: 2026-11-17. Scope: native Settings integration, preference persistence,
redraw and color-cache qualification. This investigation did not access an iPod.
It does not establish physical display quality or successful persistence across
power loss.

This records the initial implementation and 0.4.1 refinements. The
[0.4.2 controls follow-up](classic-dark-mode-controls-2026-11-17.md) supersedes
the Search light-paper exception and qualifies Calendar/Genius/Shuffle drawing
paths missed by the ordinary TextView hooks.

## Inputs and evidence levels

The pinned upstream is
[osos-lab `d2c8e357`](https://github.com/lgreitis/osos-lab/tree/d2c8e357d58591bdaa70bb6be9da191f489554a6),
vendored in the neighboring firmware lab, under GPL-3.0-only. Its
[input manifest](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/firmware/apple.json)
targets the exact prepared Apple 2.0.5 input used here. Its addresses therefore
provide candidates for direct byte qualification; they are not guesses transferred
from 2.0.4.

| Input | SHA-256 | Mapping |
| --- | --- | --- |
| Lab `Classic38FW/decrypted/osos.bin` | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | File `0xaf98` maps to DRAM `0x08000000`; initial `0xaf98` bytes map to IRAM `0x22000000` |
| App `.scratch/classic-shared-205-20261117/osos-205-prepared.bin` | `660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e` | File `0xb798` maps to DRAM `0x08000000` |

The ignored reproduction script is
`.scratch/classic-dark-native-20261117/probe_native.py`, run with
`uv run .scratch/classic-dark-native-20261117/probe_native.py`.
It uses Unicorn 2.1.4, checks both complete input hashes and all listed hook
preimages, and executes the actual Apple ARM instructions. Filesystem service,
allocation and drawing boundaries are explicitly stubbed. Its adjacent
`native-contract-report.json` records 19 passing contract probes. Disassembly used
Arm GNU Toolchain 13.3.Rel1 `arm-none-eabi-objdump` against the same raw input.

## Settings action and property integration

These locations match the two pinned images byte for byte:

| Purpose | Runtime address | Prepared file offset | Expected original word |
| --- | --- | --- | --- |
| Primary Settings action slot | `0x089a3bf4` | `0x009af38c` | `0x0821daf4` |
| Secondary Settings action slot | `0x089a7c3c` | `0x009b33d4` | `0x0821daf4` |
| Settings property slot | `0x08997b60` | `0x009a32f8` | `0x081e11f4` |
| Preferences-load call | `0x08058808` | `0x00063fa0` | `0xeb010fa3`, BL `0x0809c69c` |

The action ABI is `int(controller, const char *action, uint32_t argument)`.
The native dispatcher at `0x0821daf4` uses `0xdeadbeef` as a capability query.
Actual execution confirms that a recognized stock action with this argument
returns 1 even with a null controller; it performs no model mutation. A real
`ToggleSetting_Shuffle` action loads the Settings model from controller `+0xb0`
and calls its model operation. An unknown action returns 0. A custom appearance
handler must respect the capability-query convention and forward all unrecognized
actions to the original function. Both action slots must be patched.

The property ABI is
`int(model, uint32_t type, uint32_t property, uintptr_t *out)`.
Native string properties use `0x53747220` (`Str `), bitmap properties
`0x424d6170` (`BMap`). Return 1 only for handled properties, and forward the rest.
Use distinct stable property IDs for the inline Light/Dark value and optional
preview text and image. These contracts agree with upstream
[Settings wrappers](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/payload/settings.c)
and [native helpers](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/payload/osos.h).

At `0x08058808` the caller passes its preference object at context `+4` to the
native load routine. The next instruction sequence ignores its return value,
stores 1 at context `+0xbef`, and reads context `+4`. A trampoline can call the
original routine and then load the separate appearance preference while
preserving ARM callee-saved registers and stack alignment. This is a static
call-site finding, not a boot-time integration test.

## Native Settings row construction

The existing
[upstream UI compiler](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/patching/ui/compiler.py)
already emits the appropriate native toggle. Its
[dark-mode UI description](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/payload/dark_mode.ui)
places it after Brightness. For an iOpenPod `Appearance: Light / Dark` control:

1. Clone the native Sound Check ITEM from `SettingsMenu_Items` (resource 65).
   Preserve its 152-byte body and edit the item ID at `+0x30` and title-source ID
   at `+0x68`.
2. The new title SORC includes the static string binding and an additional SORC
   block containing three little-endian words: `0x8900`, the new value property
   ID, and destination 10. Destination 10 supplies the inline value.
3. Insert the item after `SettingsMenu_ListItem_Brightness`, retaining the order
   and bytes of the remaining stock rows.
4. Append a chosen event to the Settings screen CEVT. Its payload is
   `string("list.pid.<decimal item ID>.chosen")`, byte ASCII `1`,
   `string("iOpenPod_Appearance_Toggle")`, and little-endian zero.
   Here `string` means a little-endian 32-bit UTF-8 length followed by that many
   bytes. The toggle action belongs in the controller-action field, not a
   `navigator` action.
5. If supplying a preview, clone the Brightness VLyt and SLyt. Change the VLyt
   title source at `+0x24`; image and caption sources use SORC words `0x8900`,
   the corresponding property ID, destination 1. Add the SLst entry and bind
   `delayedselected` to `navigator.SwitchLayout` for this preview.

The row/event format above comes from the pinned compiler and native resource
records; the contract probes do not claim a physical Settings-menu visual check.

## Persistence without changing Apple's Preferences layout

Use a dedicated small file below `iPod_Control\Device`, rather than assigning
meaning to apparently unused bytes in Apple's Preferences. The upstream uses
`CFWDark`, with four-byte `DRK0` and `DRK1` records; iOpenPod can own a separately
named, explicitly validated record. Missing, short or invalid records should
select Light. A recognized valid record should be the only way to enable Dark
during startup.

The following native wrappers were instruction-executed:

| Function | Address | Qualified ABI |
| --- | --- | --- |
| Open | `0x0804f784` | `int(path, 0x64617461, mode, &handle)` |
| Read | `0x0804f838` | `int(handle, buffer, bytes, 0, &actual)` |
| Write | `0x0804ff68` | `int(handle, buffer, bytes, 1, &actual)` |
| Close | `0x0804f6e4` | `int(handle)`; result always 0 |

`path` is a 16-bit volume followed immediately by `char text[258]`, total 260
bytes. Volume zero and backslash-separated relative text match the upstream
calling convention. Mode 1 opens read-only. Modes 2 and 3 both select the writable
constructor path in this wrapper; writable open accepts constructor status 7
as well as 0, while read-only mode rejects status 7. The probes confirm argument
marshalling, including the fifth actual-byte-count pointer passed on the stack.
The underlying filesystem itself is stubbed.

Write flag 1 calls native flush `0x0826f330` after a successful transfer through
`0x0826f394`. The wrapper discards the flush result and returns 0. Close calls
the handle's vtable `+4`, also discards that result and returns 0. These behaviors
were reproduced with nonzero stub results. Therefore successful wrappers and
full byte counts are not proof of power-loss durability. Readback can establish
immediate visibility of the complete record, but cannot prove stable-media flush.

For a live toggle, prepare all resources before writing the new record. Only
publish the new active appearance after a complete successful write; on failure,
retain the previous mode and release temporary work. This matches the ordering
in upstream
[dark-mode logic](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/payload/dark_mode.c)
and [preference helpers](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/payload/preferences.h).

## Redraw and cache boundaries

The Settings model notification method is vtable offset `+0x58`, called with
`(model, type, property)`. Upstream notifies `0x2a2a2a2a` (`****`) for the three
appearance properties. It also obtains service `0x7f00` through `0x081c7d44`,
requests interface 5, and notifies `Draw` (`0x44726177`) properties `0x7f0c` and
`0x7f0d` to refresh cached Now Playing icons. This notification pattern is an
upstream implementation finding, not independently qualified notification
coverage across every native view.

`0x08113600` obtains the native root view. Actual execution confirms that it
calls the service getter at `0x0813e204`, returns service `+0x1c` when present,
and returns null when absent. Upstream invalidates its rectangle via
`0x082655a0(root, root + 0x80)`. Static inspection shows this invalidation routes
through view/canvas geometry and dirty-region handling; it does not globally
reload every resource or reconstruct every view.

Several concrete cache behaviors prevent treating a COLR getter override plus
root invalidation as a complete live-theme mechanism:

- Native menu construction at `0x0817abbc` resolves COLR and stores background
  RGBA in the resulting view at `+0x90..+0x93`. This particular path repeats the
  low color byte into all three channels. Template construction at `0x081df77c`
  performs the full RGB conversion and stores the same fields. The value is
  materialized into the object; a later changed resource pointer alone cannot
  change it.
- Ordinary text foreground is stored at view `+0xf4..+0xf7`. Its refresh at
  `0x082881f8` copies four RGBA bytes from the Type-style object referenced by
  view `+0xfc`, style offset `+8`. Actual execution confirms that mutating those
  style bytes changes the next refresh without recreating the view. Flag `0x800`
  in view `+0xf0` suppresses this copy; the probe confirms that exception.
- An optional dynamic `Colr` (`0x436f6c72`, distinct from bank `COLR`) query occurs
  only with flag `0x2000`. Standard text refresh is therefore not a universal
  repeat of the original COLR bank lookup.
- Marquee draw `0x081a8dc8` takes foreground color from cached graphics contexts
  at view `+0x254`, stride `0x6c`. Its final foreground setter is the independent
  call at `0x081a8f0c`.

The above distinguishes native cache evidence from a proposed solution. A complete
semantic live switch still needs a qualified update path for constructor-owned
colors, cached Type styles and all other affected render consumers. Sending COLR
notifications has not been shown to reconstruct static fields. Injecting arbitrary
RGB tags into resources can leak into consumers outside hooked drawing paths and
is not qualified by this research.

## Embossed text is separate from foreground text

The native ordinary text draw at `0x082883f8` has two distinct passes. When view
flags `+0xf0` include `0x1000`, and the view is not selected, it constructs
literal `#dddddd`, alpha 255, on the stack and calls the graphics-color setter at
`0x0828844c`. It then draws the offset text through `0x082872f8`. This is the
embossed/shadow pass. It does not pass through the upstream foreground hook.

The following foreground pass copies cached view `+0xf4` to the stack and calls
`0x08287218`, whose final color setter is `0x082872a8`. Executing both native
functions with a draw-service stub yielded `ddddddff` followed by the supplied
foreground `123456ff`. Changing only the cached foreground to `e4e8efff` left
the shadow `ddddddff`. A dark foreground substitution therefore needs a separate
shadow decision to avoid a bright embossed fringe.

| Pass | Call site | Original word | Destination |
| --- | --- | --- | --- |
| Ordinary foreground | `0x082872a8` | `0xebff4a1e` | `0x08259b28` |
| Embossed/shadow | `0x0828844c` | `0xebff45b5` | `0x08259b28` |
| Marquee foreground | `0x081a8f0c` | `0xeb02c305` | `0x08259b28` |

Each call preimage is checked against both pinned images by the reproduction
script. Light-mode behavior should retain the original colors and pass ordering.

## Resource getter ABI distinction

Do not confuse the two resource APIs:

- Bank getter `0x08111d74` has four arguments: bank, type, ID, and a valid output
  byte-count pointer. Its prologue is `e92d40f8 e1a04000`. It writes through the
  fourth argument on successful lookup and several miss paths. The three-argument
  wrapper at `0x08111d64` provides its own stack byte-count pointer.
- Service getter `0x08268b64` has three arguments: service, type, ID. Its prologue
  is `e92d40f8 e1a05001`; it supplies the property-output pointer internally when
  invoking service vtable `+0x64`. This is the function actually hooked by
  upstream dark mode.

Forward all arguments and preserve the original byte count if hooking the bank
getter. A service-getter hook cannot be moved to the bank getter unchanged.

## Selected-row gradient and its singleton cache

The common view drawing routine begins at `0x08263530`. Its selected-row path
generates a gradient as individual lines, then composites the generated bitmap.
It does not use the rectangle fill hook at `0x0825ae9c`. The line API
`0x0825aa2c` forwards RGBA to `0x080dca50`; this was instruction-executed with
the final surface-line operation stubbed. An accent substitution that only
recognizes `#236cc4` or `#236cc5` in the fill wrapper misses this gradient.

There are two paths controlled by the native flag at `0x089d86cc`:

| Path | Gradient | Border | Final color-set call |
| --- | --- | --- | --- |
| Flag nonzero | Generated from `#09a4e1` toward `#0063d3` | `#96c5da` and `#004386` | `0x08263934`, original `0xebffd87b` |
| Flag zero | Generated from `#5898e8` toward `#2864d0` | `#2864d0` | `0x08263d7c`, original `0xebffd769` |

Both calls target GraphicsContext_SetColor at `0x08259b28`. Border color setters
are `0x082637e0`, `0x08263820`, and `0x08263c4c`. Interpolation uses integer
scanline arithmetic, so the final visible line need not equal the theoretical
bottom endpoint. The second palette lives at `0x089d4ee8` and `+4`; executing
the initializer block `0x082a7cb8..0x082a7cfc` confirmed its eight RGBA bytes.
Executing the separate initializer `0x082a7d18` established that globals
`0x089d4f18..0x089d4f28` are white, `#aaaaaa`, `#7f7f7f`, `#555555`, and black,
not the blue selection accent.

Both selection paths share a single static Bitmap at **`0x08a82324`**, obtained
through `0x0809353c`; the lazy-construction guard is at `0x089d4ee4`. The cache key
is only the four-word rectangle at bitmap `+0x98`, address `0x08a823bc`. The native
comparison `0x08298e0c(a, b)` returns 0 for identical four-word rectangles and 1
for a mismatch. It contains no palette, appearance or generation check. Changing
the appearance without changing the rectangle will otherwise reuse old pixels.

| Comparison call | Original word | Original destination |
| --- | --- | --- |
| First gradient path `0x08263730` | `0xeb00d5b5` | `0x08298e0c` |
| Second gradient path `0x08263c08` | `0xeb00d47f` | `0x08298e0c` |

Both call preimages are qualified against both input images. A narrow appearance
generation wrapper can force a mismatch when the cached appearance differs from
the active appearance, then defer to the native comparator when they match. This
avoids walking view objects or modifying ownership fields. A common generation
value suffices because the Bitmap is shared. The native empty rectangle still
causes the initial render.

The native singleton getter and comparator were instruction-executed. A further
probe executes the Bitmap rebuild at `0x081039c8` with allocation, free and surface
initialization boundaries stubbed: it frees the old owned pointer independently
of the old rectangle and replaces the comparison bounds with the requested
rectangle. Zeroing the old bounds can force a miss, but the narrow comparator
hook provides a cleaner separation from native object state.

Do not equate the first new gradient color setter with successful completed
rendering under allocation failure. Native rebuild writes the new rectangle
before attempting allocation, and its caller does not check a success result.
The final composite calls are `0x08263984` and `0x08263dd0`. Generation bookkeeping
and tests should state whether they establish normal drawing behavior or also
handle fault paths; these contract probes do not establish allocation-failure
recovery for the full GUI.

## Live BMap palettes and the native resource cache

**The native BMap cache retains pointers into resource storage. It does not copy
or permanently convert its indexed palettes during loading.** Consequently,
editing palette or direct-pixel bytes in the resident resource updates subsequent
drawing from the same cached object. No palette-generation hook is needed for
this cache. This does not redraw pixels already composited into another surface;
the existing GUI invalidation/redraw step is still necessary.

The exact pinned native path is:

1. `0x0828fdc0` checks cache byte `+8`. A nonzero byte returns immediately.
   Otherwise it requests `BMap` through `0x08268b64`, allocates a 68-byte graphics
   context, and initializes it through `0x0825af2c`. The Bitmap is embedded at
   cache `+0x0c`; the context pointer is retained at cache `+0xc4`.
2. `0x0825af2c` calls `0x08103984` to load the Bitmap and `0x0825aea4` to attach
   it to the context. Bitmap loading calls `0x0808932c`, which uses the original
   resource `+28` as payload whenever the payload length at `+24` is nonzero.
3. `0x080893d8` stores that pointer at Surface `+0`, equivalent to Bitmap `+4`.
   It stores stride at Surface `+4`, bit depth at `+8`, and format at `+0x10`.
   Indexed format `0x64` has 8-bit indices; `0x65` has 16-bit indices. The retained
   payload begins with a palette count, then that many ARGB words and the index
   plane. No palette allocation or copy occurs in these functions.
4. Cached drawing at `0x0828fe10` calls `0x08259568`, which eventually calls the
   surface blitter `0x080e67e0`. Its conversion dispatcher at `0x080a7c14` uses
   the retained Surface pointer. The indexed8-to-ARGB32 loop reads the selected
   palette entry at `0x080a88f4`; indexed16-to-RGB565 reads it at `0x080a8e20`.
   The per-pixel palette read uses the original resource storage each draw.

The ignored reproduction script
`.scratch/classic-dark-native-20261117/probe_bitmap_palette.py` checks both full
input hashes and byte equality of seven relevant native code ranges between raw
and prepared images. Its adjacent `native-bitmap-cache-report.json` records
**seven passing native drawing cases**: indexed8 to ARGB32, indexed16 to ARGB32
and RGB565, direct ARGB32 to ARGB32 and RGB565, and direct RGB565 to ARGB32 and
RGB565. These execute the actual cache loader and complete cached-draw wrapper.
Only the resource lookup, 68-byte allocation and mutex construction are stubbed;
the entire drawing operation runs without invoking a stubbed service.

Each case loads one synthetic 4×2 BMap, then changes its red palette entry or red
pixels to blue and back to red. All three renders match exact expected pixels;
the unchanged green pixels provide an independent check of indexing and stride.
Repeated cache access makes no additional resource request, allocation or Bitmap
reload, and the retained payload pointer and header remain unchanged. Thus these
probes distinguish borrowed palette/pixel storage from reload-dependent behavior.
The selected artwork inventory at inspection contained 80 indexed8, two indexed16
and 21 direct ARGB32 BMaps, all with the 28-byte native header.

A qualification detail matters: a synthetic indexed8-to-RGB565 draw using mode 0
enters Apple's grayscale lookup path at `0x080a887c`, not the indexed palette
path. The qualified indexed8 case therefore targets ARGB32 composition; this
investigation does not assert that every higher-level UI draw uses that target.
This finding is not a stale palette cache. Do not introduce a global palette
flush or reinterpret that grayscale table as an indexed resource cache.

## Follow-up: mask tint, light wells and analog clocks

This follow-up inspected the compiled appearance implementation as well as the
same pinned native inputs. It found one additional drawing path that bypasses
the original text and fill hooks: grayscale BitmapView foreground tint.

### Grayscale masks and the Disk Mode arrows

`BitmapView_CreateFromDescriptor` at `0x081943ec` reads background color ID from
image descriptor `+0x5c` and foreground tint ID from `+0x60`. The latter lookup
calls ResourceService_GetResource at `0x0819455c` (original `0xeb035180`). It
converts the numeric COLR into RGBA and invokes view vtable `+0x114`, whose
ordinary BitmapView implementation is `0x080ffffc`. This copies the RGBA into
view `+0x160`; it is cached, rather than looked up for every draw.

`BitmapView_Draw` at `0x0810012c` checks the loaded format at view `+0xb8`.
For formats 2, 4 and 8 it passes that cached RGBA to GraphicsContext_SetColor:

| Site | Original instruction | Destination |
| --- | --- | --- |
| Mask foreground call `0x0810020c` | `0xeb056645` | `0x08259b28` |

It then selects mode `0x21` and performs the bitmap blit. Consequently, changing
only text and rectangle-fill hooks leaves a black mask black on a darkened
surface. Recoloring mask bytes would incorrectly change coverage, not ink.

The following pinned resources make the distinction concrete:

| Resource | Stock RGB | Native use |
| --- | --- | --- |
| COLR `0x0dad0df2`, at `0x0873d22c` | Black | DiskMode image descriptors `0x0dad0e17`, `0x0dad0e18`, `0x0dad0e19` |
| COLR `0x0dad0e27`, at `0x0873d234` | Black | ChargingMode image descriptors `0x0dad0e38`, `0x0dad0e39` |
| BMaps `0x0dad0dfd..0x0dad0e0e` | 4-bit coverage | Animated synchronization arrows |
| BMaps `0x0dad0e33`, `0x0dad0e34` | 4-bit coverage | Charging/charged symbols over native battery artwork |

The Disk Mode tint is an actual missing dark-surface case. A permanent semantic
COLR tag `0x000002`, decoded only by the mask foreground call, lets already
constructed views retain identity through Light/Dark changes. The compiled
implementation maps tag 2 to exact black in Light and primary ink in Dark.
Other mask colors, including tag 1 for paper text, are forwarded unchanged.
The two other Disk Mode image descriptors can share the tagged tint safely:
indexed/color BMaps do not enter this grayscale-only tint branch.

Do not generalize that change to ChargingMode. Its masks overlay unchanged
battery artwork, not simply the dark page background. This investigation proves
the black tint path but does not establish a charging-icon contrast defect. The
same caution applies to clock hands, whose native contextual selection is
qualified below.

The ignored probe `.scratch/classic-dark-native-20261117/probe_mask_tint.py`
executes the native descriptor factory, cached BitmapView draw, grayscale alpha
blend and final pixel writes. During drawing only the base-background operation
and viewport-context lookup are stubbed. A synthetic 4-by-2 mask contains zero,
partial and full coverage so the test distinguishes ink changes from changes to
coverage or background pixels. The cached tag remains `00 00 02 ff` throughout
Light/Dark/Light; opaque pixels become exact black, primary ink, then exact black
again. Untagged black, white and paper tag 1 produce identical pixels in both
modes.

Its optional `--build DIR` mode loads the patched OS and relocated compiled
payload, reads addresses from the ELF symbol table, zeroes payload BSS, and
executes the actual compiled resource and mask hooks. It sets only the payload's
active-mode variable directly, isolating drawing from preference persistence.
The constructor starts with stock black COLR; the compiled resource hook supplies
tag 2. This is not a Python substitute for the compiled color mapper.

Compiled verification passed against
`.scratch/classic-dark-refine-20261117/build-2`:

- Patched OS SHA-256:
  `44e657c78b5cdbab200988d7f08aac1fe068d8f44e12b998e3b9c5f4bbd29fd3`.
- Payload SHA-256:
  `6019c6cb67ee98900b2d12490d8fd85a7ae61ac866082347446872817500f81d`.
- Report: `native-mask-compiled-report.json` beside the probe. Stock hook preimages
  remain checked against both original pinned inputs before execution.

### Search and calendar paper are bitmap-backed light wells

The Search template View `0x0dad0dd7`, native address `0x08832ea0`, contains six
image children. Their source records resolve to overlay BMaps
`0x0dad0175..0x0dad0177`, then the input-field left/right/middle BMaps
`0x0dad0197..0x0dad0199`. All three input pieces have opaque white center pixels.
They are native color bitmaps; the rectangle-fill hook does not modify their
pixels. They deliberately remain outside the dark artwork transform.

The input text is child `0x0dad0ddc`, with stock System_Text_Color at descriptor
`+0x70`, absolute word `0x08833294`. Replacing that word from `0x0dad00ce` to
`0x0dad0dcf` gives the entry its own black-ink identity. The keyboard descriptor
continues to use `0x0dad00ce`. Although COLR `0x0dad0dcf` is named
Search_Keyboard_Background_Color, its stock value is black, and this descriptor
replacement uses it specifically as entry ink. No View/VLyt color reference to
that ID existed in the original bank. COLR `0x0dad0dd0` is white but is not what
paints these bitmap-backed field centers.

The calendar exception COLR `0x0dad030f` is specifically
Settings_DateTime_DayNumeric_Color, not all Calendar application text. Its three
native text users are:

| Template | Day-number text child | Background image |
| --- | --- | --- |
| Settings calendar preview `0x0dad01e1` | `0x0dad0607` | `0x0dad030b` |
| Alarm pick-date `0x0dad0308` | `0x0dad030e` | `0x0dad030b` |
| Settings set-date `0x0dad061b` | `0x0dad061e` | `0x0dad030b` |

BMap `0x0dad030b` is Settings_DateTime_Calendar_Image, an indexed16 image with
opaque white paper in its center. The compiled artwork choices preserve this
image. Tag 1 therefore correctly retains exact black day numbers on the paper
while normal Calendar list/month text follows the ordinary dark text policy.

Native TextView_Draw passes cached RGBA `00 00 01 ff` to the existing foreground
hook at `0x082872a8`, verified by instruction execution. The native descriptor
adapter at `0x08266ef0` tests descriptor `+0x5c` bit `0x10` at `0x0826706c` and
sets option `+0x64` bit `0x1000` at `0x08267074` to request embossed text. Actual
execution on the four original paper-text descriptors yields:

| Text | Descriptor flags | Native text-option flags |
| --- | --- | --- |
| Calendar preview day number | `0x1` | `0x80c` |
| Alarm pick-date day number | `0x1` | `0x80c` |
| Settings set-date day number | `0x1` | `0x80c` |
| Search entry | `0x3` | `0x849` |

None requests the `0x1000` embossed-shadow bit by default. Preserving the native
light-paper shadow when tag 1 is present is therefore defensive contextual
consistency; these descriptors do not establish a currently visible embossed
paper-text defect. Dynamic overrides are outside that specific assertion.

### Analog clock ink has native day/night semantics

Analog clock hands use a separate renderer, not BitmapView's tint hook:

- Hour selection `0x0818e3f4` and minute selection `0x0818e4dc` construct both
  opaque black and opaque white RGBA values.
- Predicate `0x0818e614` chooses night when a night-face cache exists at view
  `+0xc8` and the hour is before 6 or at least 18.
- Face drawing `0x0818e494` uses that same predicate to select cached day face
  `+0xc4` or night face `+0xc8`.
- Hand rendering helper `0x0818e698` applies its selected color at
  `0x0818e768` (original `0xeb032cee`, calling `0x08259b28`).
- Seconds selection `0x0818e584` uses red for ordinary clocks and black for the
  stopwatch variant.

Instruction-executed probes at hours 5, 6, 12, 17, 18 and 23 confirm that hour
and minute colors match the corresponding day/night face selection. This is
positive evidence for preserving those native colors. A global black-mask
replacement would make light-face hands lose contrast, while ignoring native
night white would also be incorrect.

The combined reproduction script
`.scratch/classic-dark-native-20261117/probe_light_wells_clock.py` checks the
resource graph, white centers, actual descriptor-adapter flags, ordinary text
tag delivery, day/night face/ink decisions and seconds-hand variants. Its report
is `native-light-wells-clock-report.json`. Font lookup and final glyph/clock-hand
rasterization are stubbed for these selection contracts; the findings do not
claim a full-screen render or a physical display observation.

## Remaining qualification

These findings qualify native ABI and specific cache/shadow behavior. They do not
validate the complete new iOpenPod appearance payload, all languages, every screen,
LCD contrast, repeated live switching, or restart persistence. Those require the
compiled payload tests and physical checks associated with the eventual firmware
build. Hardware installation was outside this investigation.
