# ADR-0204: Edit and preview artwork through Chapters

- Status: Accepted
- Date: 2026-10-28
- Extends: ADR-0138 and ADR-0202
- Supersedes: ADR-0138's free-form display-time editor controls

## Context

Artwork Display Times already survive reading, editing, and preparation, but the
editor presents them separately from named Chapters. Users must copy timestamps
between tabs, and Host playback continues showing the initial cover. Native
Chapter research establishes eligibility and ordinal alignment requirements;
editing milliseconds alone does not establish that a device will display the
intended Chapter image.

## Decision

Use the current Chapter metadata draft to label artwork choices by ordinal and
title. Empty Chapter slots are selectable. Use a Cover choice when there is no
Chapter at zero, and require a zero-time image before authoring later images.
Remove the free-form seconds input. Preserve existing unmatched groups and the
special retained key `0xFFFFFFFF` as explicitly labeled choices. The special key
remains inspectable, but cannot receive newly authored pixels. Individual removal
uses existing complete-sequence validation; it cannot leave a multi-image sequence
without a zero-time image.

Chapter titles, starts, additions, and removals update the artwork selector in the
same dialog. Changing Chapter metadata does not implicitly move or delete saved
images. An unmatched image remains available for inspection or deliberate removal.
Ambiguous or invalid Chapter lists do not become artwork assignment targets.
Mixed selections require an explicit shared artwork decision, and a shared Chapter
list is available only when the selected lists agree or the user edits them.

The Chapters table includes an Artwork column. Selecting a thumbnail opens that
Chapter's slot in the Artwork tab. Both edits remain part of the same
revision-checked Library Draft and are discarded on cancellation. Thumbnail
painting requests only visible rows, using shared provider caches for retained
images and a bounded pixmap cache for staged pixels. It does not mutate metadata
or read device files directly.

Host playback selects the greatest ordinary Artwork Display Time less than or
equal to the playback position. It shows a placeholder before the first image or
when the selected group is unavailable. Backward seeks, scrubbing, Track changes,
and provider invalidation recalculate selection. The sentinel has no Host playback
schedule. Cache keys continue distinguishing artwork identity, exact time, and
resolution; a late result for another time cannot replace the selected image.

Applied artwork edits preview immediately, before saving the Library. The
application artwork loader receives an immutable snapshot of the Library Draft's
negative artwork identities before updated Tracks reach views. It resolves owned
pixels on the existing worker pool and delegates retained group references to the
device loader using their original positive identity and exact source time. The
presentation request and result contracts accept nonzero identities; zero remains
the absent-image sentinel. Device and database identities remain positive.

Changing draft assets invalidates artwork generations and caches, including when
loading, resetting, or disconnecting a Library. Reusing a temporary identity cannot
display pixels from a previous draft. Unrelated metadata edits do not flush the
artwork cache. This preview path performs no device mutations.

The Player's Chapter index requests each visible Chapter's exact image group,
showing an empty placeholder when absent. It does not substitute an earlier or
future image. Native first-start value one maps to the zero-time image in Chapter
selection. Ordinary collection and Library covers retain their default behavior.

## Consequences and validation

The editor exposes meaningful Chapter names while preserving irregular retained
timelines. Existing native eligibility and alignment diagnostics remain relevant:
Host preview is an application policy, not an emulation of firmware refresh timing.
No physical-device acceptance is inferred from it.

Tests cover repeated Chapter edits, unmatched group retention, mixed selections,
draft cancellation and reset, thumbnail navigation, lazy visible-row requests,
forward and backward playback, scrubbing, missing and special groups, stale
results, Track changes, and translated controls. Existing save and preparation
contracts continue to validate authored groups and retained references. Additional
tests exercise Apply-to-Player preview, retained source keys, worker resizing,
draft replacement, temporary identity reuse, and late results after invalidation.
