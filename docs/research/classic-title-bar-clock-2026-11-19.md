# Classic 2.0.5 title-bar layouts

**Title Bar Clock 0.1.1-dev** ships in Mod Platform Version **0.12.3-dev**.
Apple's **Settings → Date & Time → Time in Title** controls it. When enabled,
the full-width bars align the title to the left and the native local time to the right.

## Layout inventory

The prepared 2.0.5 OS contains 149 view templates and 338 screen layouts.
Four templates combine a screen title with status indicators. Following the
screen layout (`SLyt`) through its instance list (`SSin`) finds them in 322
distinct screen layouts. Counts below are distinct screen layouts per variant.
A screen can use more than one. The resource bank also defines a partial-width
variant with no direct screen-layout reference.

| Native template | Layout variant | Screen layouts | Title and clock with Time in Title on |
| --- | --- | ---: | --- |
| White menu `01a1` | Full `01a7` | 74 | Left title, status icons, right clock |
| White menu `01a1` | Half `01a8` | 126 | Native title/time rotation inside the 160-pixel pane |
| White menu `01a1` | Partial `01a9` | 0 | Native title/time rotation inside the 230-pixel pane |
| Now Playing `020c` | Default `020d` | 70 | Left title, status icons, right clock |
| Now Playing `020c` | Charging `08d6` | 3 | Left native label, right clock |
| Now Playing `020c` | Video `08d7` | 5 | Left video title, right clock on the overlay |
| Now Playing `020c` | Radio `08d8` | 4 | Left native label, status icons, right clock |
| Now Playing `020c` | No play state `08d9` | 1 | Left album-grid title, right clock |
| White Now Playing `05ee` | Default `05ef` | 39 | Left title, status icons, right clock |
| Genius Mixes `0757` | Multiple mixes `0761` | 1 | Left mix title, right clock |
| Genius Mixes `0757` | Single mix `0762` | 1 | Left mix title, right clock |

Resource IDs in the table share the prefix `0x0dad`. The different templates
supply different alignment, text and status-image sources. The five variants of
the centered Now Playing template reuse its children and change their bindings
or visibility to suit the screen.

The photo album grid (`0x0dad0a57`) uses the no-play-state variant. The
full-size photo (`0x0dad0a58`) has no title bar. Stopwatch running and stopped
(`0x0dad0d48`, `0x0dad0d47`) use the centered default. Its menu
(`0x0dad0d4f`) uses the half-width bar and its session summary (`0x0dad0d51`)
uses the full-width white menu bar. The Genius introduction (`0x0dad083c`)
also uses the white menu bar. The two mix browsers have their own template,
which also owns the description and page indicator. Video playback shows the
clock in the native overlay (`0x0dad0979`). The underlying video-and-subtitle
layout (`0x0dad0978`) has no bar.

## Native implementation

Each template gains a native trailing-aligned TextView with a five-pixel right
margin and intrinsic width. It uses the bar's text color, Apple's status-bar font
and native clock source `SORC 0x292`. This reads string `0x80ae` from clock model `0x8080`
and uses the same localized time format (`0x11`) as Apple's alternating title.
The clock model supplies minute-change notifications.

The layout lookup at `0x08178374` selects a clock layout for each of the nine
full-width variants when the native preference getter returns true. All nine
place the title at x6 and align the clock text to x315 on the 320-pixel screen.
The indicators sit five pixels before the measured clock text. The title ends
before the indicator group. The radio variant reserves room for an indicator Apple
constructs after the title. The left-constraint application at `0x08175d30`
also sets Apple's TextView alignment byte for the two natively centered
families. Turning the setting off restores their centered text and original
bounds. The title keeps its original screen binding, including later changes.
The alternating-title getter recognizes an active clock by the title's left
constraint. Genius Mixes supplies its title directly.

### Clock spacing correction, 2026-11-24

The user reported excess space between the battery icon and time. Version
0.1.0-dev anchored the clock's left edge at x244, reserving 71 pixels regardless
of the time string. A native rectangle-solver replay with a 30-pixel text width
reproduced 41 pixels of unused leading space in addition to the intended gap.

Version 0.1.1-dev uses Apple's intrinsic-width constraint (resource edge 7),
keeping the right edge at x315. Indicators remain anchored five pixels before
the clock's left edge. The title's left constraint now references the fixed
right edge of the clock, so varying text width leaves the title at x6 and still
identifies the clock layout to the title proxy. This changes only resource
constraints and version strings; native hook code, payload size (157,332 bytes)
and reserved RAM (167,936 bytes) are unchanged.

The updated native probe fails against 0.12.2-dev and passes 77 layout checks
against 0.12.3-dev: eleven variants, each with off/on/off reuse and five supplied
intrinsic text widths (30, 46, 59, 71 and 84 pixels). It verifies exact spacing,
the fixed title origin, nonoverlapping visible indicators and stock restoration.
It executes Apple's TextView sizing at `0x08287a64` and width-constraint update
at `0x08264074` for 45 clock measurements, including width changes on reused
views. Text and glyph measurement are supplied; the widths are probe inputs,
not measurements of particular localized strings.
Physical LCD spacing and minute-rollover validation remain outstanding.

## Qualification

The [resource tests](../../tests/iOpenPod/app/test_classic_title_clock.py)
check the screen inventory, title bindings, clock source, original overrides
and packaged mod. The firmware lab's `scripts/probe_classic_title_clock.py`
executes the compiled resource installer, the three new native hooks, Apple's
preference getter, both title-proxy phases and the native rectangle solver.
The original release passed 33 off/on/off checks across 11 variants with reused
child views; the spacing correction expands this to the 77 checks above. The probe
supplies the model values and intrinsic icon sizes, verifies that the title,
icons and clock fit their assigned regions, checks left alignment and restoration
of the stock alignment on each reused title, and checks the localized format
selector. LCD appearance, localized text widths, minute rollover and video
overlay transitions still need a physical check.

Two 0.12.3-dev release builds with ARM GNU 13.3.rel1 produced identical complete images.
The prepared OS SHA-256 is
`660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e`.
The 101,871,616-byte release image SHA-256 is
`9656d06f3552da7ad23eef3ed7b994435e9aa92b2e53997e9d254f88522d5b9f`.
