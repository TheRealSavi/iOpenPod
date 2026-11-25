# Classic native Extras → Mods menu

The 0.2.2-dev shared 2.0.5 release adds a read-only native list of the included
Firmware Mods. Its entries, in order, are Mod Version String, Mod Version in
About, Unsigned Game Manifests, and Mod Menu. The builder uses the same typed
records for this list and both build manifests. A control build without the
homebrew patch omits its list entry. No desktop selection behavior was enabled.

## Native resource path

The exact prepared Apple OS remains SHA-256
`660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e`.
The English bank is at prepared-file offset 4,249,716, with header
`(3, 97056, 27)`. `ITEM 2` contains the nine original Extras entries;
`CEVT 0x0dad01cc` contains their eighteen selection/preview events.
Both are extended without changing the original entries or events.

The new screen/layout/table/entry IDs are `0x0cf00010` through `0x0cf00013`.
Other private resources allocate from `0x0cf00020`. Native aliases
`iOpenPod_Mods_Screen` and `iOpenPod_Mods_Layout` let the Extras chosen event
invoke `navigator.PushScreen`. Delayed selection switches to the existing
`Extras_Screen_Default`, clearing the previous item's preview. Menu up invokes
`navigator.PopTopScreen`; holding Menu invokes `navigator.PopToMainScreen`.

The page clones Notes' full-width alternate list layout (`SLyt 0x0dad09fb`),
retaining the original View/VLyt templates. New instance bindings select the
Mods title and new ITEM table. Rows use native text-only type 2 and have no chosen
action. The screen uses the same generic settings-list controller as the upstream
UI compiler. The compiled initialization hook installs the resources and
re-registers View children and ITEM visibility after the stock initializer.

The source-format reference is [osos-lab's UI compiler](https://github.com/lgreitis/osos-lab/tree/d2c8e357d58591bdaa70bb6be9da191f489554a6/patching/ui),
read from the pinned local checkout. The adapted code retains GPL-3.0-only
attribution; no checkout dependency is shipped.

## Memory and image bounds

Duplicating the entire stock Extras tables exceeded the existing OS slot.
Instead, the hook copies their original resident bytes into a 2,560-byte reserved
workspace, appends the new records and updates their counts. The native resource
setter makes an owned copy before the workspace is reused. Its ROM-bank path at
`0x08112288` allocates/copies resource data; the setter entry is `0x08111e20`.

The appended code/data occupies 4,064 image bytes, leaving 2,848 bytes before
AUPD. The NOLOAD workspace is completely written before use. Both heap-floor
literals now point to `0x08b3e000`, reserving two pages beginning at `0x08b3c000`.
Native BSS clear and downward-growing exception stacks retain their bounds.
No bootloader change, firmware-directory relocation or additional native code
patch site is needed.

Complete firmware SHA-256 (95,735,808 bytes):
`85c66c324fbe4a8042591bcf4302a376e90336d9c1493f761e4d22614561f42d`.
Common OS SHA-256:
`57199684ade8e992a82c35fb4e1324e2e29c47fadc9c9e73b87570d4c6826c58`.
The compressed bundled image is 56,693,412 bytes.

## Verification and limits

- Resource tests traverse the generated screen/list/title graph, independently
  decode the complete event streams, check all original Extras entries/events,
  check visible read-only rows and ensure only built mods appear.
- `ipod-firmware-lab/scripts/probe_classic_mod_menu.py` executes native relocation
  from both `0x08000000` and `0x09000000`, native BSS clear, and the compiled hook.
  Registers, stack, canaries, heap floor, aliases and all 28 installed resources
  pass, including reuse of initially nonzero workspace memory.
- Original initialized OS bytes outside the previously qualified patch sites
  remain identical, including the unsigned-manifest instruction from 0.2.1-dev.
- A second build reproduces the complete firmware hash. The release also passes
  the native unsigned-manifest and Parachute import-resolution probes; the stock
  control still rejects the absent detached signature.
- Bundled-image tests check the current version, menu labels/aliases and manifest
  patch. Installer tests preserve both 0.2.0-dev and 0.2.1-dev receipts, including
  pending installations that must finish verification without another upload.
  The focused menu/release/install/shared-image/GUI run passes all 89 tests;
  full-source Mypy, targeted Ruff, Markdown lint and lock validation pass.

The ARM probe adapts allocation, resource-name services and visibility indexing.
It does not emulate the complete UI or render the screen. Physical verification
of Extras → Mods, scrolling and back navigation remains outstanding. This
increment built and bundled the release; it did not write to a connected iPod.

## Mods preview in 0.12.1-dev

Highlighting Mods now selects `iOpenPod_Mods_Preview` through the same
`delayedselected` event used by the stock Extras rows. Pressing the center
button still pushes the Mods list. The preview clones the Games screen layout
(`SLyt 0x0dad01dc`) with private instance IDs. Its private template keeps the
image frame from `View 0x0dad019c` and omits the Games count. Its image source
resolves a private `IMAG` and indexed `BMap` containing the 142 × 87 gear asset.

Resource tests trace the highlighted row to the gear, compare its decoded RGBA
pixels with the source PNG, and check the stock Extras entries and variants.
The compiled ARM initialization probe installed all 131 resources in the full
build. With a test resource provider returning the embedded bitmap, the native
BitmapView at `0x08100020` and blitter at `0x08259568` rendered the gear on
light and dark backgrounds. Every RGB channel was within two levels of the
composited PNG, including the antialiased edges and transparent center. Two
builds reproduced the bundled image byte for byte. An on-device visual check
remains open.

## Blank gear on hardware in 0.12.1-dev

The 0.12.1-dev preview was blank on the user's iPod. The earlier pixel test
supplied the gear directly to BitmapView. It missed the step that makes the
image child available to the screen. On a ROM bank, the native template and
child registries enumerate IDs from the original directory. A private `View`
can be fetched by ID, but its children never enter that index. The native
registration loop at `0x08194df0` indexed the stock dice and skipped the
0.12.1-dev gear child `0x0cf00050`.

In 0.12.2-dev the gear is a separate image child appended to the stock Games
template. The Games layout shows the dice and count. The Mods layout shows the
gear in the same frame. Both layouts set visibility for every child so that
returning to Games restores its preview. The Mods highlight event uses the
same flag as the nine stock Extras highlight events.

The firmware lab's `scripts/probe_classic_menu_previews.py` executes the
compiled installer, native ROM iterators, child registration, resource-service
lookup and bitmap drawing code. Its child-index check fails on 0.12.1-dev.
With 0.12.2-dev the probe resolves the correct images for Games, Mods and
Games again, and renders the gear and Mono Audio icon on light and dark
backgrounds. It supplies the heap, name and index slots, and reads visibility
from the active layouts. Physical display verification of 0.12.2-dev is pending.
