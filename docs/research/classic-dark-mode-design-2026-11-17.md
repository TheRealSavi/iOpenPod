# Classic Light / Dark appearance: design and validation

This audit records appearance through 0.4.3-dev, including **Settings → Appearance**
directly after Brightness. The bundled 0.5.0-dev retains this appearance behavior
and adds [main-menu preview artwork](classic-now-playing-preview-artwork-2026-11-18.md);
the build sizes and hashes below describe the 0.4.3-dev audit image.
Center cycles its inline **Light / Dark / Auto** value, with a native sun/moon preview.
Light is the default. Extras → Mods lists **Light / Dark Appearance**.
This changes the Classic firmware, independently of iOpenPod's desktop theme.

**Auto** follows the iPod's adjusted Firmware Calendar: Light from **07:00**
inclusive until **18:00**, then Dark overnight. It retains the Auto label and
saved choice while its sun/moon preview follows the effective theme. Existing
Light/Dark preferences keep their meaning. Missing preferences still select
Light; invalid clock readings retain the current theme until a valid reading.

The native clock model's existing UI-queue timer reevaluates Auto, normally at
minute boundaries or twice per second while its detailed clock is active.
There is no additional timer or wake request. On the next delivered clock tick,
the current Firmware Calendar handles manual time changes and time elapsed
during sleep. Automatic transitions write no preferences and repaint only when
the effective theme changes; manual modes skip automatic clock reads entirely.
See [Auto's native clock and queue evidence](classic-auto-appearance-2026-11-17.md).

## Visual decisions

Keep the Classic's layout, small native type, blue selection and familiar artwork.
Use charcoal rather than pure black for the main list. Give raised chrome a
lighter blue-gray tone, preserve highlight direction, and draw embossed text
shadows separately from the foreground. Do not invert a completed frame.

| Role | RGB | Purpose |
| --- | --- | --- |
| Main surface | `#12181F` | Lists, idle clock and artwork surroundings |
| Raised surface | `#1F2934` | Control chrome and secondary panels |
| Main text | `#EDF3F9` | Small native labels |
| Secondary text | `#B7C6D5` | Metadata and less prominent labels |
| Muted glyph | `#788B9E` | Unrated stars, distinct from native white rated stars |
| Accent text | `#77C2FF` | Values and links on dark surfaces |
| Selection, lower stop | `#2368A3` | Retains separation from the main list |
| Selection, upper stop | `#2C70AD` | Restrains brightness behind selected text |
| Text shadow | `#060A0F` | Replaces the light-theme embossed shadow |

After the Classic's RGB565 quantization, primary text on the main surface is
16.11:1, secondary text on the raised surface is 8.64:1, and the least favorable
primary-text/selection pair is 4.63:1. Every one of the 119 actual native gradient
steps is checked. Selection fill remains at least 3.10:1 against the main list.

These targets draw on [WCAG text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
and [non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html).
They are design benchmarks; the backlit LCD's brightness, viewing angle, age and
physical response are not measured by an sRGB calculation. The semantic treatment
also follows [Apple's dark-mode guidance](https://developer.apple.com/design/human-interface-guidelines/dark-mode).

### Artwork and contexts

- Header bands, preview backgrounds and panel surfaces retain the direction of
  their gradients. Shadows remain darker than the surface they describe.
- Lock and battery symbols reuse Apple's native black-status-bar artwork,
  including low-battery red. They are fitted into the existing allocations.
  Plug/charging glyphs keep that artwork's coverage with lighter ink.
- Scrollbars, calendar cells, control wells, progress tracks and fills have
  separate roles. Progress fills use a brighter blue than menu selection and
  stay above 3:1 against the brightest track shade after RGB565 quantization.
- Idle clock digits and playback symbols get light ink on the main surface.
- Now Playing's large shuffle symbol uses secondary ink, the volume-lock glyph
  uses primary ink, and unrated stars use muted ink. After RGB565 quantization,
  muted ink contrasts 5.06:1 with the main surface and at least 3:1 with rated
  white stars. Original geometry, indices and alpha remain unchanged.
- Stopwatch's tinted bands have explicit fill mappings; they are not mistaken
  for white or left behind as pale panels under light text.
- Album artwork, photographs, videos and game graphics retain their pixels.
  Built-in missing-cover, empty-library and media/search placeholders use
  charcoal backdrops and lighter native symbols. Their geometry, alpha and
  palette indices remain intact. Cover Flow's surrounding clear color and
  reflection background change independently of personal cover art.
- Genius and Shuffle use blue thumbs over dark wells, with light arrows and
  labels. Their labels have separate native drawing paths from ordinary text.
  The selected Shuffle label's original blue ink is mapped to primary ink so
  it remains legible on the blue thumb.
- Search uses a raised charcoal field with light text. The Settings calendar
  illustration retains light paper and black ink. Calendar grid numbers are a
  separate context: primary/secondary light text over their dark cells, keeping
  the native white selected-day text.
- Grayscale native BMaps are coverage masks, not grayscale photographs. Do not
  recolor their byte planes; that changes opacity and shape. The connected
  screen's sync arrows instead use a dedicated cached-tint tag and draw hook.
  Clock hands and battery overlays retain their native colors because their
  day/night faces and bright battery artwork remain unchanged.
- Bootloader/recovery screens before this OS starts are outside this mod.

Resource previews decode the actual native BMaps and compiled transformations.
They are not complete firmware screenshots. Physical checks still need Settings,
long scrolling labels, music lists, Now Playing, idle clock, Cover Flow, Search,
Calendar, Stopwatch, battery states and the connected screen, in both modes.
No claim of exhaustive screen coverage follows from the offline palette checks.

## Native integration

The build checks the original prepared image SHA-256 and each hook preimage.
See [the native contract investigation](classic-dark-mode-native-2026-11-17.md)
for addresses, ABIs and instruction-executed evidence.

Important findings that determined the implementation:

1. Apple caches many colors in view instances. A resource-getter-only theme does
   not establish live switching. Foreground/fill transformations run in the
   qualified drawing paths instead.
2. TextView's embossed shadow is a separate draw call. Changing only the text
   foreground leaves a bright shadow designed for the original light surface.
3. Selection gradients use line drawing, bypassing the rectangle-fill hook.
   Both native gradient paths and their borders have dedicated hooks.
4. The selection bitmap cache compares only rectangles. The comparison hook
   also checks the active appearance so existing selections regenerate.
   Generation is recorded when drawing begins; this does not make Apple's
   bitmap allocation path fault-atomic.
5. Native file wrappers discard some flush/close errors. A successful full write
   is followed by a readback before changing the visible mode. This checks
   consistency but cannot promise power-loss persistence.
6. Native bitmap caches borrow original palette/pixel storage. Seven
   instruction-executed cache/render probes demonstrate red/blue/red palette
   changes without reloading. Indexed8, indexed16 and the relevant composition
   paths were exercised; a normal view redraw is still necessary to replace
   already composited screen pixels.
7. BitmapView masks have a separate cached tint and bypass the text/fill hooks.
   Only the sync-arrow COLR receives tag 2; the qualified mask hook renders exact
   black in Light and primary ink in Dark, preserving alpha. The native constructor
   and draw path with compiled hooks pass Light/Dark/Light without a resource
   reload. Untagged black, white and paper ink remain unchanged.
8. The TextView shadow hook receives `TextView+0xA4`, with cached foreground at
   context offset `0x50`. Paper tag 1 now preserves the native light shadow when
   embossing is requested. The actual Search/date-paper descriptors do not set
   the emboss flag; this prevents an inconsistent future combination rather
   than establishing a visible defect in the present layouts. Native TextView
   drawing with the flag enabled passes both tagged/ordinary text matrices.
9. Physical feedback exposed four custom label paths missed by TextView hooks:
   calendar day cells, weekday headers, Genius and the Shuffle option bar.
   Qualified call-site hooks resolve cached foregrounds for the active mode.
   The actual native routines and Search TextView pass 24 Light/Dark/Light cases.
   See the [controls investigation](classic-dark-mode-controls-2026-11-17.md).

The preference is a 12-byte little-endian record at
`iPod_Control/Device/iOPAppearance`: `IOP1`, mode 0 (Light), 1 (Dark), or 2 (Auto), and its bitwise
complement. Missing/corrupt/short records fall back to Light. A failed change
retains the current mode and displays **Not saved** until a successful attempt.
Apple's own Preferences format is untouched.

## Switching and RAM budget

The 0.4.3-dev switching audit executes 258 three-way user actions through the
compiled ARM toggle. After each action, all 139 resource changes match the exact
expected Light or Dark bytes. Returning to Light restores the original bank;
the linked constants remain unchanged. Every successful action requests a full
root repaint and notifies the Settings value/preview and Now Playing icon
properties. Missing playback services are handled. Preference handles are closed
after both successful and failed I/O. Native file and notification services are
adapted in this probe; this is not a measurement of the entire running OS heap.

Independent instruction probes confirm that the full-screen invalidation reaches
the live owner view's paint method. The actual marquee drawing path changes
Light/Dark/Light while reusing byte-identical cached glyph pixels and context,
with no allocation. It applies the active foreground color during mask drawing.
These checks avoid assuming that changed resource colors automatically repaint
previously composited pixels.

The separate native selection-cache probe executes Apple's full selected-view
drawing control flow with the compiled appearance hooks. Both gradient paths at
160- and 320-pixel row widths pass 128 alternating-theme renders followed by
128 same-mode draws each. A theme change rebuilds the selection; its old owned
bitmap and temporary gradient bitmap are freed. Subsequent same-mode draws reuse
the cache without allocating or regenerating the gradient. At 320 by 22 pixels,
that native path retains 14,080 pixel bytes and peaks at 42,240 during rebuild;
these are the existing selection buffers, not a new full-screen theme cache.
Allocator and raster endpoints are modeled, while native lifetime decisions
execute. This does not establish allocation-failure recovery.

The measured fixed footprint for **all included mods**, not only appearance, is:

| Storage in RAM | Bytes | Lifetime |
| --- | ---: | --- |
| Page-rounded linked payload, scratch and BSS | 110,592 | Entire OS session |
| Registered resource data copied by native resource service | 22,773 | Registered resources |
| Appearance's mutable state, included in linked BSS above | 16 | Entire OS session |

The first two rows total 133,365 bytes (130.2 KiB), before native allocator and
resource-map metadata or ordinary view objects. The 4 MiB Mod Memory Region is
a maximum capacity; OS startup reserves only the 108 KiB actually used here.
There is no second full-screen framebuffer or duplicated complete artwork set
for appearance. The 168,055 affected artwork bytes use 77,637 bytes of compressed
XOR packets in the linked payload. Literal, repeated-byte and repeated-word
packets decode directly into the original bitmap storage. Switching allocates
no theme buffer and does not reload the resource bank; ordinary rendering does
no decoding. The expanded coverage adds 32 KiB to the fixed reservation compared
with 0.4.1. Test budgets cap stored artwork packets at 80 KiB and
the appearance-specific increase in copied resource data at 24 KiB.
Auto adds four mutable bytes and 332 initialized payload bytes over 0.4.2;
the page-rounded reservation remains 110,592 bytes.

Reproduce the compiled-action test with firmware-lab's
`uv run scripts/probe_classic_appearance.py --app APP --stock PREPARED --build BUILD --out REPORT`.
The independent selection/lifetime probe is
`uv run scripts/probe_classic_selection_cache.py --build BUILD --out REPORT`.
Neither opens a device. See [switching contracts](classic-appearance-switching-2026-11-17.md)
for the separate native window and cached-view investigation.

## Reproduction and tests

Build with the existing prepared 2.0.5 input and original complete firmware member:

```powershell
uv run python -m scripts.firmware.build_classic `
  --osos PATH/TO/osos-205-prepared.bin `
  --firmware PATH/TO/Firmware-38.9.0.5 `
  --compiler PATH/TO/arm-none-eabi-gcc.exe `
  --version 0.4.3-dev --homebrew-eapps --dark-mode --out PATH/TO/new-build

uv run pytest tests/iOpenPod/app/test_classic_appearance.py `
  tests/iOpenPod/app/test_classic_deltas.py `
  tests/iOpenPod/app/test_classic_mod_menu.py
```

The companion firmware-lab script `scripts/probe_classic_appearance.py` runs
against `--app`, `--stock`, `--build` and `--out` arguments. It does not access a
device. It executes the compiled ARM payload, original startup relocation/BSS
clear from two source addresses, and the native rectangle comparator. Native
file and graphics service boundaries are modeled.

Checks include:

- Complete Settings row preservation, source bindings, preview layout, controller
  action, names and native resource installation (56 resources).
- Exact bitmap restoration, repeated same-mode application, invalid mode rejection
  and unchanged bitmap allocation geometry.
- Missing, short, malformed and invalid preference records; six I/O failure paths;
  action support queries without mutation; fallback to original Settings methods.
- Foreground/shadow separation, alpha preservation, 119 selection stops, cache
  transitions, clear colors and reflection blending.
- Actual native TextView drawing through the compiled text/shadow hooks, for
  tagged light-paper ink and ordinary text through Light/Dark/Light.
- Contrast checks on the transformed Now Playing glyph pixels; these failed
  against the original three assets and pass with the new semantic roles.
- ARM calling-convention preservation of r4–r11 and SP.
- Calendar/Genius/Shuffle/Search native rendering with cached colors retained;
  actual bitmap center/arrow contrast; packet boundary and odd-address coverage.
- Auto's six boundary times and all 24 hours, retained policy/preview, clock
  changes, invalid clock values, failed saves, startup selection and 120 steady
  Auto polls without extra redraws or preference writes. Manual polling performs
  no clock reads. Native calendar conversion and actual timer dispatch are
  independently qualified in the Auto investigation.

The 139 targeted bitmaps use 77,637 bytes of compressed reversible deltas. The 2026-11-17
candidate uses 104,520 initialized mod bytes and 110,592 reserved RAM
bytes including scratch/BSS. The complete image remains 101,871,616 bytes, with
SHA-256 `ab637fa796bab12aab7ed2f5d88f5036fc021726ae9fb9d977db508b47d785ca`.
Two independent builds reproduce this hash. The packaged asset is 56,750,335
bytes; 193 focused firmware, installer and GUI tests pass against it. Ruff,
strict Pyright, full-project Mypy, Markdown and locked-dependency checks pass.
Hardware display, live redraw and persistence have not yet been tested for this
release. Existing physical evidence for earlier firmware must not be described
as a test of this dark-mode build.
