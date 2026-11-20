# Classic appearance switching and cache lifetime evidence

Date: 2026-11-17. Scope: Light/Dark switching in the shared Classic 2.0.5
firmware, redraw behavior and additional RAM use. No device was accessed.

The audited 0.4.1 implementation does not need a new cache-flushing mechanism
based on the native paths exercised here. Its existing rendering hooks update
cached text and mask colors at drawing time, bitmap edits remain visible through
borrowed resource pointers, and the selection gradient deliberately regenerates
when its appearance generation changes. Native instruction probes demonstrate
these contracts; they do not demonstrate every physical screen transition.

## Inputs and evidence boundaries

The primary source is the exact Apple executable. Address labels were seeded by
[osos-lab at d2c8e357](https://github.com/lgreitis/osos-lab/tree/d2c8e357d58591bdaa70bb6be9da191f489554a6)
and qualified against the pinned inputs. See the
[earlier native audit](classic-dark-mode-native-2026-11-17.md) for the resource,
color, text-shadow and masked-bitmap contracts.

| Input | SHA-256 | Runtime mapping |
| --- | --- | --- |
| Lab `Classic38FW/decrypted/osos.bin` | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | File `0xaf98` to DRAM `0x08000000` |
| Prepared Apple 2.0.5 | `660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e` | File `0xb798` to DRAM `0x08000000` |
| Audited 0.4.1 `osos-about-unsigned.bin` | `44e657c78b5cdbab200988d7f08aac1fe068d8f44e12b998e3b9c5f4bbd29fd3` | File `0xb798` to DRAM `0x08000000` |
| Audited 0.4.1 `payload.bin` | `6019c6cb67ee98900b2d12490d8fd85a7ae61ac866082347446872817500f81d` | ELF symbol `__payload_start` |

The compiled input directory is
`.scratch/classic-dark-refine-20261117/release`. The ignored reproduction script
`.scratch/classic-dark-native-20261117/probe_switching.py` accepts `--build DIR`;
its adjacent `native-switching-report.json` records seven passing contracts.
It executes native ARM instructions and the actual compiled foreground hook.
The script supplies synthetic objects, rectangles and coverage pixels, and stubs
locks, the root getter, viewport binding, owner paint callback and marquee rebuild
predicate. It does not emulate a complete booted GUI or font rasterization.

## What the switch invalidates

The current
[Appearance action](../../scripts/firmware/classic_about/appearance.c)
saves and verifies the preference, applies the new appearance, notifies its value
and preview properties, notifies Now Playing properties `0x7f0c` and `0x7f0d`, and
invalidates the root view rectangle. It does not reconstruct the entire UI.

The native root getter `0x08113600` resolves the UI context through `0x0813e204`
and returns its `+0x1c` root pointer. Native `View_InvalidateRect` at `0x082655a0`
has ABI `void(view, rect)` and performs these operations:

1. Requires `(view[+0x48] & 0x1800) == 0x800`, using `0x082990d8`.
2. Returns if view byte `+0xa0` suppresses drawing, or global byte `0x089d4ee0`
   is zero.
3. Intersects the requested rectangle with view bounds `+0x80` and, when present,
   parent clip bounds `parent+0xd0`.
4. Resolves the containing window through `0x08299080`: use view `+0x3c`, or
   follow parent `+0x34`; the root fallback resolves virtual method `+0x5c`
   and takes its `+0x104` window.
5. Converts coordinates through `0x0828355c`, then calls
   `Window_InvalidateRect` at `0x082843ac`.

`Window_InvalidateRect` unions damage into window rectangle `+0xdc`, holding the
lock at `+0xd4`. Root byte `+0x101`, and the corresponding owning root byte, can
suppress this operation. It queues damage; it neither paints synchronously nor
walks child cache objects. The native probe confirmed the full `240 x 320` damage
rectangle and each suppression condition, with no allocation.

The later native window painter `0x08284240(window, rect)` invokes the live
owning view's virtual paint method at `+0x70`. For windows without a single owner,
it iterates the collection at `window+0x7c` and invokes the same method on its
members (`0x08284330..0x08284378`). The probe executes the owning-view branch and
records the complete dirty rectangle reaching that callback. The collection
branch is static disassembly evidence, not a full descendant-traversal test.

The native root painting loop `0x08113664` iterates windows through the collection
at `root+0xe8`, clips queued rectangles to window bounds, and calls the same
window painter at `0x08113704`. It skips suppressed windows. Consequently a root
invalidate is suitable for repainting the live visible UI; it should not be
described as eagerly rebuilding every hidden screen or every derived bitmap.

## Cached views that remain current

| Cache | Why switching can update it | Evidence |
| --- | --- | --- |
| Ordinary text and panel RGBA fields | Final text/fill hooks map cached original colors using the current mode | Native text and shadow probes in the earlier audit |
| Indexed and color resource bitmaps | Native bitmap objects retain pointers into the resource's palette/pixel data; the switch edits those bytes in place | Seven native cache/load/draw cases in the earlier audit |
| Disk Mode arrow mask tint | Cached semantic tag `0x000002` is resolved by the compiled BitmapView tint hook on each draw | Native constructor and Light/Dark/Light cached render probe in the earlier audit |
| Long scrolling text | The marquee draw selects its final foreground on every composite | Native compiled probe below |
| Selected menu row gradient | The existing theme-generation comparison forces the singleton bitmap to regenerate once per mode change | Native selection stress probe below |

For an existing marquee, `MarqueeTextView_Draw` at `0x081a8dc8` uses cache records
at `view+0x248`, stride `0x6c`, with the graphics context at record `+0x0c`.
It reads the original cached foreground through `0x0829877c`, selects the selected
foreground where appropriate, calls the patched setter at `0x081a8f0c`, then
composites using draw mode `0x23` at `0x081a8f38`. Short strings fall back to the
ordinary TextView painter at `0x081a8fbc`.

The probe constructs a native owned 8-bit bitmap using `0x08103d48`, attaches its
context to an already populated marquee cache and draws it in Light, Dark and
Light again. The first and third output byte strings are identical; Dark differs.
The source coverage bytes and entire cache record remain byte-identical throughout.
No cache regeneration or allocation occurs during those draws. The cached bitmap
therefore need not be regenerated merely to change its foreground color.

Native cache construction at `0x081a8648` compares dimensions and font depth before
reusing its bitmap. On a mismatch it destroys the previous bitmap through virtual
method `+4` at `0x081a874c`, before allocating a replacement at `0x081a8754`.
This is static lifetime evidence; the switching probe exercises reuse, not native
font rasterization or this reallocation branch.

## Now Playing notifications and layout transitions

Now Playing notifications `Draw/0x7f0c` and `Draw/0x7f0d` are narrow property
refreshes, not global image-cache flushes. Apple's own code emits the same pair
at `0x081ef168..0x081ef198` and `0x081992ec..0x08199320`. The property getter
`0x081eda2c` resolves these IDs through `0x081ee4b8` to playback-state-dependent
bitmap resources, including `0x0dad086b`, `0x0dad086e`, `0x0dad086c` and
`0x0dad086f`. This supports retaining the two notifications without broadening them
to an expensive arbitrary model refresh.

Native `BitmapView_InvalidateBitmap` at `0x081000bc` is a separate, stronger
operation: it clears cache-valid byte `+0xa1`, destroys the graphics context
at `+0x15c` through `0x0825b038`, frees that context through `0x082a1730`, and
zeros the pointer. Visible views with flag `0x10` can immediately reload/resize;
all paths request view invalidation afterward. This audit does not prove that
every hidden binding receives each model notification, and does not require that
claim for borrowed bitmap data or rendering-time color hooks.

The [Appearance event definition](../../scripts/firmware/classic_appearance.py)
uses `navigator.SwitchLayout` for `delayedselected`, to select the preview pane.
Its `chosen` event calls the appearance action. Repeated toggles on the selected
row do not themselves request a new layout transition or allocate another screen
snapshot.

Static native transition evidence:

- `UI_TransitionToLayout` at `0x0817518c` can return early when the same layout
  is selected, unless the layout definition's byte `+8` requests refresh
  (`0x08175214..0x08175240`). Calling it is therefore not a reliable general
  cache-flush operation.
- Transition paths 2 and 3 can allocate a bitmap object of `0xb8` bytes and a
  window of `0x130` bytes. The bitmap uses format `0x1888` and the old view's bounds
  (`0x081755d4..0x0817564c`). Full-screen color pixels belong to this existing
  Apple transition machinery, not to the Appearance toggle.
- For the common old-layout branch, `0x08175698` calls the live window painter
  before `0x08175700` copies its pixels into the transition surface. There is a
  layout-type-5 exception which skips this explicit repaint. This exception has
  not been shown to cause a stale Appearance frame.
- Transition completion logic at `0x081798ec` validates its generation, clears
  transition state and posts event `0x2503`. This audit did not completely trace
  ownership and destruction of every transition surface. It makes no claim that
  all transition allocations were counted or freed by the marquee/window probe.

The minimal evidence-supported action is to keep the existing root invalidation
and targeted hooks. A whole-tree destruction/rebuild or a forced transition
would add allocation and state-management work without fixing a reproduced
defect. Rapid toggles during a native animation, deferred rendering while drawing
is suppressed, and returning from special offscreen layouts remain physical UI
validation cases.

## Bounded memory and repeated switching

The parent audit ran the lab's durable
`scripts/probe_classic_selection_cache.py` against actual `0x08263530`, the compiled
hooks, native bitmap resize/free and a tracked allocator. Its report is
`.scratch/classic-appearance-switching-20261117/selection-initial.json` in iOpenPod.
Both gradient branches and both 160- and 320-pixel row widths passed 128 alternating
mode renders plus 128 same-mode cache-hit draws per case.

| Row width | Peak tracked pixel bytes | Retained singleton pixel bytes | Allocate/free calls per case |
| --- | --- | --- | --- |
| 160 | 21,120 | 7,040 | 256 / 255 |
| 320 | 42,240 | 14,080 | 256 / 255 |

The retained allocation is the current native selection bitmap, not an
accumulating per-toggle object. The second draw in the same mode makes zero
allocation, free or gradient-color calls. These counts cover the exercised
selection pixels, not total firmware heap usage.

The companion actual compiled-action stress test performed 256 successful
toggles, checked every patch byte after each toggle, ended in byte-exact Light
resources and kept the compiled payload immutable. The parent audit also measured
77,824 bytes of payload/static reservation and 22,768 bytes of registered resource
payload. These fixed costs must be distinguished from the short-lived native
selection drawing buffers and Apple's pre-existing layout-transition surfaces.

No production change was justified by this follow-up. The evidence supports
keeping version 0.4.1 while adding the regression coverage and these documented
limits; it does not replace a physical test of the complete GUI scheduler.
