# GUI Design Language

This is the working visual foundation for iOpenPod 2.0. It defines durable color,
type, spacing, shape, interaction, and large-library presentation rules. Individual
prototype pages remain replaceable, while their shared model/view and presentation
primitives are intended to be reusable.

The executable source of truth is
`src/iOpenPod/GUI/presentation/theme/tokens.py`. This document explains why those
tokens exist and how future widgets should use them.

## Research Translation

The Original iOpenPod was reviewed as visual research, following ADR-0004. Its
recurring design signal is more useful than any individual implementation:

- cool blue-gray foundations rather than neutral gray;
- one familiar iPod-blue accent;
- compact desktop density on a four-pixel rhythm;
- moderately rounded controls and panels;
- native platform typography and window chrome;
- artwork and data, rather than decorative effects, as the visual focus.

iOpenPod 2.0 carries those qualities forward in a smaller semantic system. It does
not carry forward the Original project's widget hierarchy, mutable theme catalog,
per-widget style strings, general-purpose decorative gradients, or scattered local
constants. The Player is the narrow exception: its stylesheet renderer may derive
subtle lighter and darker variants from the active semantic theme to distinguish
playback chrome. Optional Colorful Mode reuses the Original project's image-to-color
behavior through one typed presentation helper, but limits dynamic color to
collection-card fills and the active Track-list context bar.

## Visual Intent

iOpenPod should feel like a quiet desktop music utility: precise enough for device
work, familiar enough for a music library, and restrained enough that album art and
track data remain the strongest color on screen.

Depth normally comes from surface lightness and one-pixel separators. Avoid
decorative gradients, glass effects, colored shadows, and nested cards. The Player
may add low-contrast vertical gradients to its band, now-playing surface,
slider tracks, and round handles. The optional Round Track-list title bar also uses
opaque shading to make its native splitter handle feel rounded and grabbable.
Those effects remain theme-derived; they must not introduce an independent palette.
Use the active theme's accent for focus, links, and primary actions rather than as a
large saturated background treatment. Colorful Mode is an explicit user preference:
it adds quiet
artwork-derived card fills without replacing semantic selection, focus, status, or
action colors.

## Semantic Color

Every authored color is opaque. Transparency is reserved for temporary overlays and
effects, not named palette roles.

| Role | Porcelain (Light) | Slate (Dark) | Original iOpenPod (Dark) | Purpose |
| --- | --- | --- | --- | --- |
| `window` | `#F3F5F8` | `#12171D` | `#1A1A2E` | Application canvas |
| `surface` | `#FBFCFE` | `#1B2129` | `#212135` | Primary content surface |
| `surface_alt` | `#E9EDF3` | `#252D38` | `#252538` | Inset or alternate surface |
| `surface_hover` | `#F0F3F7` | `#2B3541` | `#303042` | Pointer hover feedback |
| `surface_pressed` | `#E1E7EF` | `#343F4D` | `#39394B` | Pressed or open feedback |
| `surface_selected` | `#DCE9F8` | `#203B59` | `#34344A` | Quiet selection background |
| `text` | `#20252D` | `#EFF3F8` | `#E9E9EB` | Primary text |
| `text_secondary` | `#535D6C` | `#B5BECA` | `#B2B2BA` | Supporting text |
| `text_disabled` | `#788393` | `#7F8A99` | `#8A8A96` | Disabled text and icons |
| `border` | `#CDD4DF` | `#374351` | `#353546` | Subtle separation |
| `border_strong` | `#8591A2` | `#606D7E` | `#6B6B7E` | Interactive boundaries |
| `accent` | `#176FD1` | `#69A9F2` | `#409CFF` | Selection and primary signal |
| `accent_hover` | `#0F61BC` | `#82BAF5` | `#60B0FF` | Accent hover state |
| `accent_pressed` | `#0B53A2` | `#4A92E3` | `#2189E9` | Accent pressed state |
| `accent_ink` | `#F8FBFF` | `#0C2238` | `#101C2A` | Text on accent fills |
| `focus` | `#0B5CAB` | `#8FC7FF` | `#74C0FC` | Keyboard focus |
| `scrollbar` | `#7B8797` | `#667386` | `#747486` | Resting scrollbar thumb |
| `scrollbar_hover` | `#5D6878` | `#8B97A8` | `#A1A1AD` | Hovered scrollbar thumb |
| `danger` | `#B32937` | `#FF8790` | `#FF7B7B` | Destructive or failed state |
| `warning` | `#865300` | `#F0B45F` | `#FCCF52` | Caution state |
| `success` | `#247642` | `#72CE8C` | `#67D879` | Successful state |
| `artwork_blue` | `#9CC7EE` | `#315B83` | `#355F8A` | Placeholder artwork field |
| `artwork_green` | `#9FCAB3` | `#35654E` | `#386A52` | Placeholder artwork field |
| `artwork_gold` | `#DDC37D` | `#75622F` | `#7A6630` | Placeholder artwork field |
| `artwork_coral` | `#DEA39C` | `#744944` | `#7A4D48` | Placeholder artwork field |
| `artwork_violet` | `#B9ACD8` | `#584B78` | `#5D507F` | Placeholder artwork field |
| `artwork_slate` | `#9BAABA` | `#415166` | `#46566C` | Placeholder artwork field |
| `artwork_ink` | `#34485D` | `#D7E6F5` | `#DFE8F3` | Placeholder artwork line work |

Primary and secondary text meet WCAG contrast floors on both `window` and
`surface`. Accent ink is paired explicitly with every accent fill. Strong borders,
focus, and scrollbar thumbs meet the non-text contrast floor against their normal
surfaces. A widget must never infer its own lighter or darker color from these
values, except for the Player renderer's documented depth treatment. That derivation
is private to the Player stylesheet, starts from the active `ThemeTokens`, and does
not extend or bypass the theme protocol.

Text actions use semantic `ActionButtonKind` variants owned by the shared Theme
Module. `secondary` is the visible default, with a surface fill and strong boundary;
`primary` carries the accent fill; `quiet` is reserved for low-emphasis actions in
an already-obvious action context; and `danger` marks destructive actions with
danger-colored text and border. `IconButtonKind` gives icon-only actions the same
semantic vocabulary and adds `subtle` for supporting controls that sit beside a
more prominent peer. The Player uses a flat transport row: Previous and Next are
subtle, Play/Pause is quiet with normal text emphasis, and all three retain 44-pixel
hit targets without visible button outlines. Every kind shares global hover,
pressed, focus, and disabled treatments, while loading, error, and success use the
global `ActionButtonState` contract. Dialogs and pages select these semantic values;
they do not assign string properties directly or reproduce button colors or QSS
locally.

Nested editor groups alternate `surface_alt` and `surface` by depth. The alternation
communicates containment rather than sibling order: depth zero uses the alternate
surface, depth one uses the primary surface, and every deeper level continues the
same parity. A one-pixel semantic border preserves the boundary in every theme.

### Original iOpenPod Palette Choices

Settings → Appearance offers independent Light and Dark theme choices. Auto uses
the saved theme for the Host's current appearance. Porcelain and Slate remain the
defaults.

| Theme | Appearance | Canvas | Content surface | Accent |
| --- | --- | --- | --- | --- |
| Catppuccin Latte | Light | `#EFF1F5` | `#E7E9EF` | `#1E66F5` |
| Catppuccin Frappé | Dark | `#303446` | `#34384A` | `#8CAAEE` |
| Catppuccin Macchiato | Dark | `#24273A` | `#282B3F` | `#8AADF4` |
| Catppuccin Mocha | Dark | `#1E1E2E` | `#222333` | `#89B4FA` |
| Dune Plover | Light | `#F5EEDC` | `#F7F1E3` | `#456D67` |
| Sea Glass | Light | `#EDF6F7` | `#E7F1F2` | `#167C9C` |
| Gravity | Dark | `#030507` | `#0E1D2E` | `#A9D8F5` |
| Northern Lights | Dark | `#0B1726` | `#102439` | `#78E0A4` |
| Orchid | Dark | `#111018` | `#252231` | `#C56BD8` |

These palettes were translated from the Original iOpenPod's bundled
`src/iopenpod/themes/*.json` definitions into fixed `ThemeTokens`. They retain the
original canvas, content surface, alternate surface, and accent colors. Hover,
pressed, selection, supporting text, boundaries, scrollbar, and status colors are
adapted to the shared contrast floors. Placeholder artwork uses muted variations
of each palette's supporting colors. Every palette consumes the same metrics,
typography, palette builder, stylesheet renderer, and Colorful Mode recipes; no
Original iOpenPod files are loaded at runtime.

## Metrics

All spatial values are Qt logical pixels. Qt maps them to physical pixels for the
current screen.

| Family | Values | Use |
| --- | --- | --- |
| Spacing | `2, 4, 8, 12, 16, 24, 32, 40, 64` | One four-pixel rhythm with a two-pixel optical correction |
| Controls | `32, 36, 44` | Compact, regular, and large or touch-safe |
| Touch target | `44` | Minimum for touch-reachable actions |
| Standard icon | `18` | Icons beside desktop body text |
| Icon button | `36` | Regular desktop icon-button box |
| Combo indicator | `36` | Stable square indicator slot |
| Scrollbar | `10` | Compact interactive extent |
| Scrollbar handle | `36` | Minimum handle length |
| Control radius | `8` | Buttons, fields, and small controls |
| Panel radius | `12` | Top-level grouped surfaces |
| Pill radius | `999` | Semantic pills only, never ordinary controls |
| Sidebar | `256` | Stable source-list width |
| Player | `0 / 68` | Fully collapsed idle / active compact full-height Player band |
| Player center surface | `≤ 1,200` | Fluid now-playing well with a centered wide-window cap |
| Playback pane | `360` | Fixed Queue, History, and Lyrics pane width |
| Playback row | `64` | Three-line Queue or History delegate row |
| Queue artwork | `44` | Painted Track cover or placeholder |
| Track-table artwork | `28` | Reduced cover inside a dense table row |
| Page header | `56` | One compact title row with page-owned actions or browser controls |
| Source lists | `272 / 280 / 176 / 320 / 4` | Standard / artwork-bearing default widths, minimum / maximum widths, and splitter handle |
| Collection source row | `60` | Two-line Artist or Genre identity and album/Track summary |
| Album card inset / caption gap | `6 / 6` | Original-informed optical spacing around artwork and text |
| Album artwork | `168` | Painted grid artwork square |
| Album card | `180 × ≥228` | Original-informed width and minimum height; captions may increase it |
| Photo browser | `220 / 340 / 4` | Album pane, inspector pane, and thin splitter handle widths |
| Track list handle/header/row | `44 / 40 / 36` | Grabbable context boundary and dense table rhythm |
| Playlist banner / artwork tile | `≥152 / 88` | Metadata-safe context height and bounded cover ribbon |

The regular control is intentionally compact for mouse and keyboard use. Use the
44-pixel tier when a control is likely to be touched or when it is the primary
action in a sparse view. Do not scale these values manually for Retina or other
high-density displays.

## Application Shell and Item Views

The main shell uses an Original-informed desktop structure: a persistent Player,
source-list Sidebar, and one content stack. The Player defaults to the top edge, and
the global Player position setting can move that same runtime surface to the bottom
edge without recreating its playback state. The Library page uses an album grid
above a Track table with a vertical splitter. This macrostructure is recognizable,
but its implementation follows Qt model/view boundaries rather than reproducing the
Original widget tree.

The shell keeps the Player and its Queue/History/Lyrics pane outside the workspace stack.
The main window owns one persistent status bar outside both the page and workspace
stacks. Pages publish application status; they do not own, hide, or replace that bar.
Sync replaces the Library browser, including its Sidebar, while playback controls,
status messages, backup progress, and the active-status list remain available through
scanning, media selection, and Review. The status bar stays below the central shell
with either Player position, including when the idle Player is collapsed.

During playback, the Player uses three horizontal zones. Equal-width edge zones size
to the larger control cluster rather than taking a percentage of the window. This
keeps the now-playing surface exactly centered while allowing it to consume the
available space between the controls up to a 1,200-pixel maximum. Wider windows turn
the excess into equal breathing room on both sides of the surface. The
Player band uses the alternate semantic surface so it reads as application chrome
rather than page content. The now-playing surface spans the band's complete height,
uses the primary surface, and is separated from the edge zones by one-pixel vertical
rules rather than a rounded floating card.
With no current Track, the Player contracts completely and returns its space to the
Library. Transport, metadata, artwork, volume, and Queue controls appear only once a
current Track makes them relevant. The height transition follows the Host style's
widget-animation preference and otherwise completes immediately.
Previous, Play/Pause, and Next form a vertically centered cluster anchored to the
left edge. Mute and a flexible volume slider sit on the right beside the Queue toggle,
which remains anchored at the far-right edge. Play/Pause has the strongest glyph
weight, Previous, Next, and mute are supporting controls, and every icon action
retains a 44-pixel hit target. The volume slider's empty track uses the strong semantic
border role so it stays visible against the alternate Player surface. Title and
subtitle labels derive their height from the active font metrics and elide
horizontally, so larger Host fonts and long metadata do not clip glyphs vertically.

The Queue toggle reveals a fixed-width pane beside the body content rather than over
or within the full-width Player. Queue and History tabs use `QListView`
with painted delegates. Pending Queue entries include 44-logical-pixel artwork and
a separate 44-logical-pixel trailing remove target. Missing covers use the shared
deterministic placeholder, while asynchronously loaded covers repaint only their
visible rows. Keyboard users can remove the focused entry and reorder it with
Alt+Up or Alt+Down. Opening reserves the pane's final body width once, then slides
the pane surface through that clipped slot. Closing releases the width only after
the slide finishes. This prevents a Library grid relayout on every animation frame;
tab and row state changes remain immediate and unanimated.

The History tab offers a quiet Clear History button above the list. Clearing removes
all retained Playback History entries without changing the current Track, playback
position, or pending Queue. The button is disabled while History is empty, and new
Track starts populate it again.

The Lyrics tab is scaffolded as a read-only plain text box with a coming-soon
placeholder. It has no lyrics loading or playback integration. Its intended display
is ordinary scrollable text without synchronized highlighting or automatic scrolling.

Queue actions appear together in the shared Track context menu and Playlist toolbar.
Play Next uses a list-and-arrow glyph pointing into the top of the Queue; Add to
Queue retains its label and uses the corresponding glyph pointing into the bottom.
Play Next inserts the selected occurrences at the front, while Add to Queue appends
them. Both preserve selection order and duplicates without interrupting the current
Track. If playback is idle, the first queued Track starts immediately.

The Browser header is deliberately one line: it names the current tab and then
provides that tab's controls. It does not repeat album or Track totals. Album and
Track searches retain independent query state so switching tabs does not silently
change the meaning of entered text.

Every application page uses the same compact Page Header primitive. A page may add
only actions that operate at page scope; it may not enlarge the title role, add a
second header row, or recreate the header's height, margins, and separator locally.

Settings groups its existing controls into Appearance, Library, Backups, and About
tabs, with a Linux tab only on Linux Hosts. The shared Page Header, tab bar, and
automatic-save note stay visible while each category scrolls independently.
Switching tabs retains each category's scroll position and control values; theme
and language changes update the page without resetting the selected category.

Secondary source navigation uses one Source List rail primitive. The rail owns its
inset heading-and-count row, semantic surface and separator, list scrolling, and
rounded hover, selection, and focus treatment. Photos, Podcasts, Backups, and future
source-driven pages supply their own model and, when content needs it, their own
delegate; they do not reproduce the rail layout or item-state styling. Photos,
Podcasts, and Backups place that rail in a horizontal splitter so its default width
is user-resizable down to the shared minimum. A narrower rail remains valid when a
multi-pane browser needs to preserve its primary canvas.

Artist and Genre list mode uses that same rail beside the album grid. Each
virtualized row pairs the collection name with explicit album and Track counts, so
the list communicates scale without forcing a selection. The current collection is
marked by a quiet semantic fill, while every collection name uses a consistent bold
weight and keyboard focus retains its independent two-pixel ring. Grid cards use the
same summary wording, and the current collection stays synchronized when the user
switches between grid and list mode.

The Playlist page uses its context area as a quiet artwork banner rather than an
empty slab. A deterministic, right-weighted ribbon tiles at most twelve
representative album covers from the complete selected Playlist. Playlist Folders
use the same recursive Track projection shown by their table. The banner does not
change when local search filters the table, because search does not change Playlist
membership. Missing or pending covers use the shared album-key placeholder, and
asynchronous loads repaint only banners that reference the changed artwork ID.
Cover opacity remains subordinate to metadata in every theme, controls retain their
semantic opaque surfaces, and the ribbon has no decorative animation.

In the split Library view, the Track context and local Track search form the actual
`QSplitterHandle`. The title names the selected album, or all Tracks, without a row
count. Dragging any non-control part of that surface resizes the views; using its
search field filters only the Tracks already in context. The handle disappears with
the album panel in full Track-list mode, leaving only the Browser header and table.

Large collections must never allocate one persistent child widget per Track or
album. Prefer these primitives:

- immutable application-facing snapshots and stable item identifiers;
- `QAbstractItemModel` implementations under `iOpenPod/app/models`;
- proxy models for view-specific filtering and sorting;
- `QListView` or `QTableView` for viewport virtualization;
- `QStyledItemDelegate` for per-item custom painting;
- one model reset for whole-snapshot replacement, followed later by proportionate
  incremental signals where workflows require them.

In the Sync Workspace, Group by Selection adds full-width Selected, Mixed, and
Deselected rows to Host Library card grids. Each row uses a disclosure arrow and can
be collapsed independently. Empty groups are omitted, selection changes move cards
between groups immediately, and the grouped projection preserves delegate-backed
viewport virtualization rather than creating persistent card widgets.
Expanding and collapsing a grid section slides its cards beneath the fixed header
over 200 ms, with the following sections moving alongside them. Repeated activation
reverses the slide. The view uses at most two viewport-sized snapshots, commits the
group state immediately, and releases the snapshots when the animation finishes.
Scrolling, resizing, or changing the model interrupts the transition and reveals
the live grid; scroll clamping that moves the header uses the immediate layout.

Use native `QHeaderView` movement, resizing, selection, accessibility, and sorting
behavior before introducing a custom header. Avoid initial sorts that are not
required to communicate the source data: a large Library should reach its first
frame in natural order and sort when the user asks.

Sync Review uses the Original iOpenPod's stacked, collapsible action groups. Each
compact header pairs a shared tri-state checkbox with an action symbol, title,
description, selected count, total count, and disclosure control. Add, Remove,
Update, and Needs attention use the existing success, danger, accent, and warning
roles; labels carry the meaning independently of color. Empty groups are omitted.
Each expanded group contains one virtualized table capped at eight visible rows,
preserving bounded widget allocation for large Libraries. The persistent workspace
footer holds Select All, Select None, Expand All, Collapse All, the selected total,
Edit Selection, Cancel, and the reserved Sync Selected action. Review choices update
the shared storage estimate. All sizes, surfaces, typography, focus, and button
states use the existing Theme Module; no separate Review palette is introduced.

The Track-list title bar has a global **Flat** / **Round** appearance preference.
Flat retains the straight-edged treatment and is the default. Round takes its
rounded upper corners and pill-shaped search field from the Original iOpenPod.
Its borderless, opaque gradient lights an upper shoulder and shades the lower face
of the same color, keeping depth and a solid boundary against the Track table
instead of fading back to the table surface. Every gradient stop preserves primary
text contrast. It uses the active theme's accent, or artwork-derived color when
Colorful Mode has one available. Both styles retain the same title, search,
and native splitter dragging; changing style takes effect immediately without
resetting the search, table columns, or splitter position.

Album artwork in the Track table is a real `TrackColumn`, not a view-injected
decoration or synthetic leading cell. It participates in the same header movement,
visibility persistence, reset behavior, and Add Column menu as every metadata
column. Its delegate paints a centered 28-logical-pixel cover in the 36-pixel row.
Because requests originate only from delegate paint calls, a hidden or off-screen
artwork cell does not load or decode an image.

The album grid uses deterministic placeholder art until lazy device artwork is
available. Artwork remains behind a stable provider. When Colorful Mode is on, the
provider analyzes requested artwork outside the GUI thread and retains dominant RGB
values in an entry-bounded least-recently-used cache. It exposes those values to
Library-card delegates and the active Track-list context bar only. Delegates
composite that value over the semantic card surface for an opaque fill and
strengthen the fill for hover or selection. Missing or pending art keeps the normal
semantic treatment. Every selected Library card also retains a solid accent outline
with Colorful Mode on or off, independently of hover and keyboard focus. An inset
dashed focus ring identifies the current keyboard item without replacing selection
or covering artwork and captions. Delegates request only visible covers, size the
request in physical pixels for the current display scale, and repaint the viewport when an
asynchronous image or color result arrives. RGB, derived-color, and Qt pixmap caches
are cleared when the Active iPod generation changes.

Album delegates retain a fixed card width and a uniform, font-derived card height
with a 228-logical-pixel minimum. The `QListView` assigns equal-width layout cells for
the current viewport and resynchronizes their uniform height when Host font metrics
change. Centering each card in its cell distributes the visible columns evenly
without abandoning batched layout, uniform item sizes, or delegate painting. Cell
sizing reserves the active style's vertical-scrollbar extent even while that
scrollbar is hidden, and every layout batch ends on a complete row. Those invariants
keep row spacing stable across scrollbar transitions, viewport resizes, accessibility
font changes, and large collection boundaries.

## Typography

Qt's Host-provided General and Title fonts fill the body and display roles. The mono
role prefers an installed modern platform face, such as SF Mono, Cascadia Mono,
Consolas, Noto Sans Mono, or Menlo, before falling back to the Host Fixed font. This
keeps glyph coverage, rendering, and platform character intact on macOS, Windows,
and Linux. A bundled brand family may replace a role later only as an explicit
dependency and licensing decision.

Type sizes use positive point values derived from the Host body font. The general
scale is a major third (`1.25`): small, body, heading, and title. Two dense-library
surfaces keep explicit minimum roles translated from the Original project: table
column headings are at least 12pt semibold, while collection-card titles are at
least 14pt semibold over 12pt medium metadata. The Track-list context title uses the
general title size at bold weight. These roles remain Host-relative when the native
body font is larger. Data columns should use tabular number features when their
chosen font supports them.

## Platform and High-DPI Behavior

The Theme Module divides responsibility deliberately:

- `QPalette` supplies fundamental application and state colors;
- token-rendered QSS supplies focused widget treatments that native engines do not
  expose consistently;
- the Host style retains window chrome, text rendering, input behavior, menus, and
  accessibility semantics;
- vector paths and multi-resolution image assets remain crisp at each device pixel
  ratio. The current glyph provider prepares common 1×, 1.5×, 2×, and 3× pixmaps in
  one `QIcon`; custom artwork paint code stays in logical coordinates and lets the
  Qt backing store supply physical pixels.

See ADR-0009 for the logical-pixel and native-display-metric decision. Custom paint
code should read the widget palette and device pixel ratio rather than importing
theme constants or multiplying layout geometry.

## Interaction Contract

Interactive widgets account for default, hover, keyboard focus, pressed, disabled,
loading, error, and success states as applicable. State must not rely on color
alone. Focus appears immediately and does not alter control geometry. Hover is
quiet; pressed is visibly deeper; successful synchronous actions are normally
silent.

Use Host-semantic cursors rather than custom cursor artwork: pointing hand for
enabled button-like controls and clickable album items, I-beam for editable text,
vertical resize for the Library splitter handle, and the ordinary arrow for disabled
or non-interactive surfaces. A cursor may clarify an existing interaction, but must
not be the only indication that the interaction exists.

Text expansion is expected. Layouts must survive longer translations, right-to-left
direction, larger Host fonts, and 200% display scaling without clipped labels or
fixed text widths.

## Ownership

`GUI/presentation/theme` is one deep Theme Module. Its public concepts are semantic
tokens, appearance-mode and exact-theme selection, palette construction, stylesheet
rendering, and contrast-safe recipes for dynamic color.
Widgets request semantic roles through the palette, object properties, or shared
theme helpers. They do not embed hexadecimal colors or reproduce platform and
high-DPI policy locally.

Any change to this foundation should update its invariant tests and receive visual
checks in Light and Dark modes at 100% and 200% scale. Prototype page composition
may change, but reusable models, delegates, controls, and presentation modules should
be evolved deliberately instead of copied into page-local alternatives.
