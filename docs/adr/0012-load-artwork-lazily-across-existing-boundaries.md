# ADR-0012: Load artwork lazily across existing boundaries

- Status: Accepted
- Date: 2026-08-29

## Context

ArtworkDB records point into shared iTHMB files. An iPod Library may contain ten
thousand Tracks and enough artwork that eagerly reading, decoding, or constructing
Qt objects for every image would delay the first frame and retain excessive memory.
The same image also needs different source resolutions at standard, fractional, and
Retina display scale factors.

Artwork crosses all four primary boundaries without belonging wholly to any one of
them. Device Registry knows which formats a particular iPod supports, iPodDB knows
the binary record and pixel layouts, Storage is the only boundary allowed to read
the device filesystem, and iOpenPod owns selection, scheduling, caching, and GUI
presentation. Letting a parser open iTHMB paths or a delegate parse ArtworkDB would
violate the dependency and device-safety decisions already accepted.

## Decision

Artwork uses a lazy, typed pipeline that preserves the existing boundaries:

- A Device Profile owns immutable cover and photo format descriptors. Each
  descriptor includes its numeric format ID, dimensions, row stride, pixel format,
  and use. A Device Profile also carries an opaque packaged product-image name; only
  the GUI resolves that name to a Qt resource.
- iPodDB builds an immutable Artwork Index from an already-parsed ArtworkDB
  Database Document. It maps image IDs and iTunesDB Track database IDs to bounded
  iTHMB locations. Its iTHMB decoder accepts only bytes and an explicit pixel
  layout, and returns owned RGB888 bytes. It knows no Device Profile, Storage type,
  path, cache, or Qt object.
- Storage exposes an exact ranged read on a Filesystem Session. The operation uses a
  validated Device Path, rejects links and non-files, checks bounds, and verifies
  that file identity did not change around the read. Storage retains no iPod or
  artwork knowledge.
- The Application Layer loads ArtworkDB metadata while selecting the Active iPod,
  links Tracks by their 64-bit database IDs, chooses the smallest available
  Device-Profile format that satisfies the requested physical-pixel target, reduces
  the database filename to a validated leaf below `iPod_Control/Artwork`, and asks
  Storage for only that image range.
- `ArtworkController` performs iTHMB reads and decoding through a two-worker pool,
  deduplicates requests, rejects results from an obsolete Active iPod generation,
  and keeps owned RGB images in a 64 MiB least-recently-used cache. Cache state is
  cleared whenever Active iPod state changes.
- The GUI asks for artwork only while a virtualized item is painted or the player
  displays a Track. Track-table artwork is one real, configurable model column; its
  delegate therefore makes no request while that column or cell is outside the
  painted viewport. The GUI converts RGB bytes to detached `QImage` and `QPixmap`
  objects only on the GUI thread, uses Qt's bounded pixmap cache, and selects source
  artwork by physical pixels derived from Qt logical size and device-pixel ratio.
- Optional image-derived presentation colors are computed from immutable RGB bytes
  in a separate one-worker GUI-presentation pool. Pending analysis is capped, results
  enter an entry-bounded least-recently-used cache, and both pending and retained
  state are scoped to the Active iPod generation. Delegates only request a color and
  repaint when its asynchronous result arrives; they never analyze pixels while
  painting.
- Missing, unsupported, or malformed optional artwork leaves the iPod Library
  usable and displays the deterministic placeholder. A changed or disconnected
  Filesystem Session still fails closed.

## Consequences

The first Library frame depends on iTunesDB and compact ArtworkDB metadata rather
than every iTHMB image. Scrolling work scales with the visible viewport, Qt widgets
do not scale with collection size, and macOS Retina or Windows fractional scaling
can request a source that avoids unnecessary upscaling.

The pipeline contains two deliberately memory-bounded image caches plus an
entry-bounded derived-color cache when Colorful Mode is used, along with some
repeated cross-boundary types. New image formats require a Device Profile descriptor
and an iPodDB decoder test rather than GUI conditionals. Device disconnection or
selection can waste a decode or color analysis already in progress, but its
generation-tagged result cannot enter any live cache.

This decision covers read-only cover presentation. Artwork writes, iTHMB
allocation, image conversion policy, photo workflows, and transactional ArtworkDB
updates require separate decisions before they are enabled.
