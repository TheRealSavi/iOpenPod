# Classic appearance changes and Now Playing artwork

## Report and scope

After installing 0.6.2-dev, the user reports the earlier menu-preview loss is
mostly fixed. The custom Now Playing menu artwork still disappeared after a
Dark → Light switch, while ordinary right-side menu previews continued working.
Preserve the visibility-context fix and investigate appearance refresh separately.

Version **0.6.3-dev** corrects a missing artwork notification. It is a candidate
for this remaining physical symptom, not a claim that its intermittent device
sequence has been reproduced completely.

## Native contract and correction

`appearance.c` notified playback properties `Draw/0x7f0c` and `Draw/0x7f0d` after
successful Settings actions and effective Auto transitions. Those refresh the
playback controls. Neither matches the preview's `Draw/0x7f05` artwork binding.
A root repaint does not reset a BitmapView's ready flag or borrowed context.
The 0.6.2-dev visibility hook cannot help an attached view that receives no
visibility transition during this refresh.

The correction sends `Draw/0x7f05` through the same current playback model before
the control notifications. Apple's observer at `0x08265a2c` matches this property
and invokes the native invalidator, `0x081000bc`. That releases the view's
68-byte context and clears readiness; the next load queries the artwork source.
The callback does not release model-owned pixels or clear the shared model cache.

Manual preference failures still send no playback refresh. An absent playback
service is harmless. Auto ticks with no effective transition still do nothing;
manual modes perform no Auto calendar reads. Successful manual policy changes
retain the existing refresh behavior, including a policy change with the same
effective theme. No timer, retained pointer or new image allocation is introduced.

## Native regression

The retained lab probe executes the compiled appearance action, preference
read-back validation, Auto poll, actual native view observer, loader, destructor
and RGB565-to-ARGB8888 blit. It supplies file I/O, the service registry, time and
observer delivery at explicit boundaries. Provider image replacement is injected
while the view stays attached; this models a stale-image condition rather than
emulating the complete artwork worker or Settings navigation sequence.

From the iOpenPod repository:

```powershell
uv run ../ipod-firmware-lab/scripts/probe_classic_appearance_artwork.py `
  --build .scratch/classic-appearance-artwork-20261118/release `
  --out .scratch/classic-appearance-artwork-20261118/native-release.json
```

Against the preceding `.scratch/classic-artwork-lifetime-20261118/build-1`, the
same probe fails on Dark → Auto daytime Light:

```text
provider_queries: 0
rendered: 000000ff000000ff000000ff000000ff
AssertionError: Appearance change left Now Playing artwork stale
```

Adding only the missing notification changes this to one provider query and four
replacement green pixels. Light → Dark and Auto transitions at 07:00/18:00 also
pass. An initial 64-cycle stress run released all 72 allocated contexts. The
final retained probe paints after each policy change: its default 16 cycles
release all 57 allocated contexts, with one 68-byte context live at most.
Repeated paint does not reload, a temporarily unavailable source can recover,
and shared image memory is never passed to the free boundary.

The existing lifetime probe still passes 512 hide/show cycles with 518 allocations
and 518 frees. The native binding/getter probe also passes, including matching
image-ID cache reuse, both no-art fallbacks and track-change notifications.
The application release, composition and firmware workflow checks pass 232 tests;
Mypy passes all 1,598 source files.

This proves the missing notification and its view-level correction. It does not
prove that the injected replacement is what occurred on the user's iPod. In
particular, a stale matching-ID bitmap inside Apple's model would be a separate
condition; this correction deliberately does not reset that unproven state.
Physical Dark → Light and ordinary menu-preview checks remain necessary.

## Bundled candidate

- Apple version: **2.0.5**; Mod Platform Version: **0.6.3-dev**.
- Light / Dark Appearance: **0.1.5-dev**; Now Playing Preview Artwork: **0.1.1-dev**.
- Bootloader remains **2.1.0**.
- Build directory: `.scratch/classic-appearance-artwork-20261118/release`.
- Prepared OS SHA-256:
  `218603dd95c399f4b39698e5eacf4db9aeb30dc09b0fe60a0bd245dbbc54c43b`.
- Payload SHA-256:
  `40932040a8056ff5c80483a6d7d188c4875fb9d0588232767e53bc2cc06cfc06`.
- Full firmware SHA-256:
  `97a1ae6f321b037b18af52a028335e4c173f60e0ac86b159a62f33e1c5fb24a5`.
- Complete image: **101,871,616 bytes**; bundled compressed asset: **56,752,611 bytes**.
- Initialized payload: **109,904 bytes**, 20 more than 0.6.2-dev.
- Reserved Mod Memory Region: **114,688 bytes**, unchanged; no added retained state.

The app pin, historical release map, offline asset and notices include this
candidate. No connected device was accessed or flashed during this change.
