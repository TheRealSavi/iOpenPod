# Classic dark mode: Calendar, playback controls and Search

Date: 2026-11-17. Scope: diagnose reported dark-mode defects in Classic 2.0.5
mod firmware 0.4.1 and qualify the narrow native text fixes in 0.4.2-dev.
No device was accessed during this investigation.

Calendar dates, weekday headings, Genius labels and Shuffle labels use custom
native drawing paths that bypass the ordinary TextView foreground hook. This is
a demonstrated defect, not a stale-cache hypothesis. Four additional call-site
hooks correct these paths. The selected Shuffle label needs its own color rule
because its new thumb is blue. Search input already uses ordinary TextView;
removing its previous white-paper exception lets the existing hook provide light
ink on the newly darkened field.

## Sources and reproduction

The exact Apple executable is the primary source. Names and resource structure
were informed by
[osos-lab at d2c8e357](https://github.com/lgreitis/osos-lab/tree/d2c8e357d58591bdaa70bb6be9da191f489554a6),
then checked against the pinned instructions and descriptors. The
[earlier native audit](classic-dark-mode-native-2026-11-17.md) explains bitmap
resource borrowing and rendering-time foreground mapping; the
[switching audit](classic-appearance-switching-2026-11-17.md) covers invalidation
and cache lifetime.

| Input | SHA-256 |
| --- | --- |
| Lab `Classic38FW/decrypted/osos.bin` | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |
| Prepared Apple 2.0.5 | `660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e` |
| Baseline 0.4.1 OS | `44e657c78b5cdbab200988d7f08aac1fe068d8f44e12b998e3b9c5f4bbd29fd3` |
| Baseline 0.4.1 payload | `6019c6cb67ee98900b2d12490d8fd85a7ae61ac866082347446872817500f81d` |
| Candidate 0.4.2-dev OS, build-1 | `497317234a8c1cfcefdedf5568b04c519c5dc52a8b1b793ffa5c745b35e3ce2f` |
| Candidate 0.4.2-dev payload, build-1 | `5a96c05fee3110bdd99b37a22527b8ef90dc759a47bd7036bfd9534710cf2bd4` |

The raw image maps file offset `0xaf98` to DRAM `0x08000000`; the prepared and
modded images use file offset `0xb798`. The probe loads the real compiled
payload at ELF symbol `__payload_start`, clears its declared zero region, and
selects Light/Dark through its actual `active` state.

The ignored reproduction script is
`.scratch/classic-dark-native-20261117/probe_calendar_controls.py`. It checks
both original image hashes and all four original call instructions. Run from
the application repository:

```shell
uv run .scratch/classic-dark-native-20261117/probe_calendar_controls.py
uv run .scratch/classic-dark-native-20261117/probe_calendar_controls.py --build .scratch/classic-dark-controls-20261117/build-1 --output .scratch/classic-dark-native-20261117/calendar-controls-build-1.json
```

The baseline exits with six failing Dark cases. The candidate executes its
installed branches without emulator-side patching and passes all 24 cases.
Adjacent JSON reports preserve the inputs and observed colors.

The probe executes native day-cell paint, weekday paint, the Genius label helper,
complete option-bar paint, and ordinary TextView paint. It supplies synthetic
objects and cached fields. Viewport binding, font lookup/metrics, date conversion,
background bitmap blits and final glyph rasterization are stubbed. Assertions
observe the native graphics context's resulting RGBA at `context+0x11`; these
are native instruction tests, not screenshots or complete GUI emulation.

## Confirmed call sites

Every original call below invokes `GraphicsContext_SetColor` at `0x08259b28`.
Its ABI is `r0 = graphics context`, `r1 = pointer to four RGBA bytes`.

| Purpose | Call address | Original ARM word | Original little-endian bytes | Native source of color |
| --- | --- | --- | --- | --- |
| Calendar day number | `0x081c0170` | `0xeb02666c` | `6c6602eb` | Pointer at day view `+0xf4` |
| Calendar weekday label | `0x081365e4` | `0xeb048d4f` | `4f8d04eb` | Calendar view `+0x104` |
| Genius slider label | `0x08196e24` | `0xeb030b3f` | `3f0b03eb` | Global black at `0x089d4f28` |
| Shuffle option label | `0x081e0930` | `0xeb01e47c` | `7ce401eb` | Option view `+0x1cc` or `+0x1d0` |

The first three use the ordinary appearance foreground mapping. The fourth
uses `iop_appearance_option_text`, whose extra Dark-only mapping converts
selected blue `#0071c4` to primary ink `#edf3f9`. Mapping it to the general
accent color would give insufficient contrast on the new blue selection thumb.
Other option colors pass through the ordinary foreground mapping. The actual
implementation is in
[appearance.c](../../scripts/firmware/classic_about/appearance.c), with checked
patch definitions in
[build_classic.py](../../scripts/firmware/build_classic.py).

## Calendar grid versus the Settings date card

Calendar View `0x0dad036c` contains a `calv` child `0x0dad036e`. Factory
`0x081d56e8` allocates `0x12c` bytes and calls constructor `0x08136af8`.
The native custom painter is `0x081363fc`. It draws seven weekday labels and
then paints the 42 day cells through a reusable child at parent `+0xec`.

| Calendar role | COLR resource | Original color | Parent cache |
| --- | --- | --- | --- |
| Weekday headings | `0x0dad0346` | `#666666` | `+0x104` |
| Active-month day | `0x0dad0347` | Black | `+0x108` |
| Inactive-month day | `0x0dad0348` | `#666666` | `+0x10c` |
| Highlighted day | `0x0dad034b` | White | `+0x110` |

The parent selects the cell bitmap and color together. At `0x081367cc`, it
stores the selected color pointer into the child's `+0xf4`. The child painter
`0x081bff58` draws the backdrop, formats the number with `%d`, calls the custom
color setter at `0x081c0170`, and dispatches text at `0x081c017c`.
None of this reaches the ordinary TextView color call.

The probe renders day 17 with cached black, gray and white, in Light/Dark/Light
order. It also executes the parent weekday loop and observes all seven labels.
Dark mode changes black to `#edf3f9`, gray to `#b7c6d5`, and preserves highlighted
white. Both Light passes reproduce the original colors. The parent restores its
temporary drawing-suppression byte `+0x101` after each paint.

The Settings date/time paper card is a different path: COLR `0x0dad030f` over
white BMap `0x0dad030b`. Its existing black-on-paper exception remains valid.
It should not be confused with the Calendar grid's custom day-number renderer.

## Playback controls

Genius View `0x0dad08fc` contains `slsw` child `0x0dad08fe`, created through
`0x0819658c` and constructor `0x08197068`. Its loader at `0x081966b8` uses
BMaps `0x0dad018d..018f` for the well, `0x0dad08c0` for the slider image,
`0x0dad08c1/08c2` for selected end/fill pieces, and `0x0dad08c3` for the icon.
The white control surface is bitmap artwork; changing ordinary panel fill
colors cannot darken it.

Its label helper `0x08196dd4(view, context, rect)` explicitly sets global black
at `0x08196e24`, then draws the string at `0x08196eb8`. Once the bitmap surface
is darkened, this custom call also needs the foreground hook. The native
Light/Dark/Light case confirms black/primary/black with the compiled fix.

Shuffle View `0x0dad0900` contains `opbr` child `0x0dad0901`. Factory
`0x081dfdc0` allocates `0x1d4` bytes and calls `0x081e0d1c`. The standard style
initializes unselected RGBA at `+0x1cc` to `252525ff`, and selected RGBA at
`+0x1d0` to `0071c4ff`; these are literal cached colors, not COLR lookups.
The complete paint function `0x081e06d0` selects between them using the option
index at `+0x124`, calls the setter at `0x081e0930`, and draws text at
`0x081e0974`. Both cached labels become primary ink in Dark mode, and their
distinct stock colors return in Light mode.

## Search field and the caret question

Search View `0x0dad0dd7` has ordinary text child `0x0dad0ddc`. Its original
descriptor uses FONT `0x0dad0037`, COLR `0x0dad00ce`, and source `0x087a`.
Native adapter `0x08266ef0` translates descriptor flags `3` into options
`0x849`, without the embossed-shadow bit `0x1000`.

Source `0x087a` binds service `0x7680`, property `0x7684`. Controller
`0x08125e94` reads this as a plain string property (type `0x53747220`) at
`0x08125ee0`, edits it
for character insertion/backspace, and publishes it at `0x0812614c`. No
separate caret color operation or appended caret was found in that path.
The input text reaches the existing foreground hook at `0x082872a8`.

The native probe executes ordinary TextView with options `0x849` and a cached
black foreground. It observes black/primary/black without modifying the cache.
The new candidate also leaves original descriptor word `0x0dad00ce` at
`0x08833294`, removing the previous rewrite to the paper-tag color.

The keyboard is a separate `kbrd` child, `0x0dad0ddd`. Its factory
`0x081d5e30` creates the composite and an inner view through `0x08204668`.
The inner glyph routine `0x08203e8c` has another custom color call at
`0x08203f2c`, but its constructor initializes both cached glyph colors to white.
This inspection did not establish a black-keyboard-glyph defect and does not
justify changing that call speculatively. It also does not establish that every
interactive cursor/selection state has been physically exercised.

## Result and limits

The confirmed ink defects are reproduced before the change and corrected by
the actual compiled candidate. Cached source colors survive unchanged and
render correctly when switching back to Light. The native checks do not
measure animation smoothness, hardware LCD appearance, or every language and
keyboard state. Bitmap palette changes and fallback artwork are separate
resource work; the text probe deliberately does not claim to validate their
final pixels.
