# ADR-0054: Browse Photos through a lazy three-pane UI

- Status: Accepted
- Date: 2026-09-14
- Extends: ADR-0012, ADR-0019, and ADR-0053

## Context

The common Library contract and Device Coordinator can project Photos and lazily
decode a suitable iTHMB representation, but the Photos route is still a placeholder.
The browser needs to scale to device-sized collections, preserve the established
Library visual language, show Photo Album membership, and let a user inspect each
stored device format without granting the GUI filesystem or PhotosDB authority.

The Original iOpenPod provides useful interaction evidence: Photo Albums on the
left, a shared grid in the center, and a preview and metadata inspector on the right.
Its direct device reads, page-owned worker state, and raw Photo database objects do
not fit the current boundaries.

## Decision

- The Photos route uses one horizontal three-pane splitter. It presents a synthetic
  All Photos row plus retained user Photo Albums on the left, a virtualized Photo
  grid in the center, and one read-only Photo inspector on the right. The master
  Photo Album remains domain state rather than a duplicate source-list row.
- The grid reuses `EqualizedGridView`, shared Library card geometry, batched layout,
  uniform item sizing, and delegate-only painting. A Photo-specific delegate keeps
  non-square images aspect-fit and requests pixels only for painted cards.
- The grid follows the shared Library card selection gestures: ordinary extended
  selection, Shift-drag box selection from empty space, and clearing selection when
  empty space is clicked without Shift. Dragging selected Photos publishes one
  revision-bound, in-process Photo selection; no Photo drop target is registered yet.
  Right-click preserves a selected group or selects the pointed Photo and opens a
  Photo-specific menu whose actions remain disabled placeholders until their
  workflows are designed. ADR-0057 replaces the add/remove-album placeholders with
  one user-Photo-Album membership dialog.
- `PhotoController` performs asynchronous, deduplicated Photo loading with a
  Connection-Generation scope, a bounded request cap, and a byte-bounded RGB
  cache. When that cap delays a painted request, a capacity notification makes the
  visible grid and inspector retry rather than leaving a permanent placeholder.
  `PhotoPixmapProvider` owns GUI-thread `QImage` and `QPixmap` conversion and clears
  its cache and presentation state with the controller generation.
- `PhotoRequest` may name an exact format ID. An omitted format lets iPodDB choose
  the smallest suitable display representation; a named format must resolve to that
  exact retained representation. Exact-format cache entries are independent of
  display size because their stored source bytes do not change when the inspector
  is resized.
- The inspector orders format choices by descending image area and then format ID.
  It shows one large aspect-fit preview plus grouped Photo, Storage, selected-format,
  and all-format metadata derived only from the semantic `PhotoLibrary`. A missing
  or failed stored format has an explicit unavailable state and can be retried by
  clicking its selected format button again.
- Photo Album and Photo selection survive same-generation draft refreshes by stable
  IDs when those records remain in context. A new Workspace generation resets both
  selections even when another Active iPod reuses the same numeric IDs. Active iPod
  changes also invalidate pending pixels. Splitter proportions use one typed global
  setting.

## Consequences

Large Photo Libraries do not create a widget per image or eagerly decode iTHMB
files. Switching formats cannot accidentally return another equal-sized format, and
late results from an obsolete Active iPod cannot enter the live presentation cache.
Duplicate Photo occurrences repaint together without scanning the entire model for
each completed image.

The UI adds Photo-specific list models, a delegate, controller, pixmap provider, and
inspector, while preserving one semantic Library seam. ADR-0055 later added export,
ADR-0056 added bounded full-resolution preview, and ADR-0057 added reversible user
Photo Album membership edits. Photo asset addition/removal and album creation remain
separate workflows.
