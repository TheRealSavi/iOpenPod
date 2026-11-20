# Classic menu artwork lifetime

Date: 2026-11-18. Candidate: Mod Platform **0.6.2-dev**, Now Playing Preview
Artwork **0.1.1-dev**. No device was accessed or flashed.

## Physical report and remaining uncertainty

The user reports that scrolling through many albums in Cover Flow leaves ordinary
menu artwork previews and the main-menu Now Playing artwork missing. Cover Flow
and the full Now Playing screen continue working. Opening the full Now Playing
screen and returning does **not** repair the previews.

The native probe reproduces a narrower lifetime defect: a hidden BitmapView
retains its drawing context when the provider retires its pixels without a
property-change notification. Showing it again paints retired pixels. This does
**not** establish which Cover Flow event produces the physical failure, or prove
that every affected menu preview uses this BitmapView class. Keep the reported
Cover Flow regression open until the candidate passes that sequence on hardware.

## Pinned inputs and candidate

| Artifact | SHA-256 |
| --- | --- |
| Original logical 2.0.5 OS | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |
| Prepared stock 2.0.5 | `660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e` |
| Candidate prepared OS | `330f3682cf85e7f8f18cac393af20f7890501f8aaf2037c0edc26092a00a12c6` |
| Candidate payload | `746c1fcb55c2612628c0f9e46f67a2a5f09215785cbd791e5153d4974ab9a619` |
| Candidate complete firmware | `4a28fcb0fbc649fe99e3793807764343fbc6b85e26c57e538cb284d84a9572eb` |

Raw offset `0xaf98`, or prepared offset `0xb798`, maps to DRAM `0x08000000`.
Static analysis used the pinned executable in the read-only Classic38 Ghidra
project. Working exports and the candidate build are retained in the ignored
`.scratch/classic-artwork-lifetime-20261118/` directory.

## Ownership and native behavior

The main-menu mod still binds `VCvs 0x162` to the native Now Playing model,
`Draw/0x7f05`. That model's bitmap is at `model + 0x18c`. Its getter
`0x081eda2c` can borrow the player's decoded pixels, or use the native no-art
fallback. The separate retained synchronous image is owned through the model's
reference at `+0xcc`; its cached image ID is at `+0x3b4`. A preview must not free
these shared objects when it disappears.

`BitmapView_LoadBitmap`, `0x08100020`, borrows that bitmap and allocates one
68-byte graphics context at `view + 0x15c`, marking `view + 0xa1` ready. Repeated
loads return immediately while ready. The context stores the bitmap pointer at
`+0x1c` and copies its bounds into its clipping rectangle at `+0x34`.

`0x081000bc` invalidates the view and releases its context, not the model or its
pixels. Matching property events reach this path through `0x08265a2c`. The
visibility callback `0x08100318` does not invalidate this cache. On showing an
auto-sized view it calls LoadBitmap, which returns early for an already-ready
view; a fixed-size view takes the same early return during its next paint.

Provider eviction exists independently of view notifications: session budget
reduction `0x081e64b0` can call `0x081e63cc`, which traverses image records via
`0x0811446c` and invokes their `+0x24` eviction method. `0x082777d8` releases the
decoded representation and invokes `0x080f9c64`. These static paths motivated the
cache-replacement fixture; the probe does not execute that whole worker sequence.

Ordinary album-list artwork uses a separate session obtained through
`0x0820068c`, queried by `0x082005bc`; selection setup/cleanup is
`0x08169e40` / `0x08169fdc`. Cover Flow owns a session at its model `+0xe0`,
stopped through `0x0813803c` → `0x08216940` when its controller exits.
Do not conflate these sessions with one shared image buffer or assume that
restarting playback repairs all menu artwork.

## Candidate change

The optional Now Playing artwork mod replaces exactly one vtable entry:
`0x089889a8`, originally `0x08100318`. `iop_artwork_visibility` handles the base
BitmapView visibility callback. For dynamic `Draw` sources only, it clears
readiness and destroys/frees that view's graphics context before passing the
visibility transition to Apple's original implementation. Static `BMap`
resources keep their original caching behavior.

Both hide and show clear stale state. A hidden view allocates nothing; a fixed
rectangle reloads lazily at paint, while Apple's auto-size path loads on show.
The wrapper deliberately avoids the generic invalidator, whose visible-view
branch can reload immediately during cleanup. It does not retain model pointers,
free shared pixels, restart sessions, flush global caches, or add timers.

The hook affects base BitmapViews bound to dynamic sources, including the new
Now Playing preview; subclasses with a different visibility callback are outside
this change. The initialized payload grows by 108 bytes to 109,884 bytes, with no
new retained state or image buffer. The 114,688-byte page reservation is unchanged.

## Native regression and limits

The retained lab probe runs the candidate's actual vtable, compiled wrapper,
Apple visibility/load/cleanup routines and native RGB565-to-ARGB8888 blit:

```powershell
uv run ../ipod-firmware-lab/scripts/probe_classic_preview_lifetime.py `
  --build .scratch/classic-artwork-lifetime-20261118/build-1 `
  --out .scratch/classic-artwork-lifetime-20261118/native-lifetime.json
```

Against `.scratch/classic-clock-dark-20261118/release` (0.6.1-dev), the same
command fails with `Menu preview reused retired artwork after hide/show`.
The output remains four black pixels, with one query, one allocation and no
release. The candidate queries again and draws all four replacement green pixels.

Additional cases pass: 512 hide/show cycles, duplicate hide, no per-paint reload,
fixed-size lazy loading, an unavailable provider remaining retryable, two views
sharing one model without releasing each other's context or bitmap, and static
bitmap caching remaining unchanged. All 518 allocated contexts are freed; peak
ownership is 68 bytes for one view and 136 bytes for two. The existing binding,
fallback, event and geometry probes also pass.

The provider injects cache replacement; GUI layout/repaint boundaries are stubbed.
There is no full Cover Flow scroll simulation, disk I/O, worker scheduling or LCD
validation. Thus this is a tested lifetime correction and a **candidate** for the
reported symptom, not a verified resolution of that complete hardware bug.

## Subsequent device feedback

The user reports 0.6.2-dev is mostly fixed. The Now Playing menu preview still
failed once after Dark → Light, while the ordinary right-side menu preview and
other artwork continued working. This is partial physical confirmation of the
lifetime change, not proof that every Cover Flow sequence is resolved. The
follow-up appearance refresh correction is documented in
[its own regression note](classic-appearance-artwork-refresh-2026-11-18.md).
