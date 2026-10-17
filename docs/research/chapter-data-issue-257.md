# Chapter data compatibility: issue 257

Investigated on 2026-10-17 against `f6c50adf` and the local release tags.

## Report and version discrepancy

[Issue 257](https://github.com/TheRealSavi/iOpenPod/issues/257) reports that
chapters are inspected and copied correctly but a Classic 6th generation ignores
them after Sync with 2.0.12. The reporter counted 24 `chap` entries without a
`hedr`, compared with 19 entries and a `hedr` from 1.68.1. No database snapshots
were attached when investigated. The different entry counts also mean these are
not identical chapter-input comparisons.

Commit `33ccaa1578da1660fb4b026366c99c0d701ec3d0` added the terminal `hedr` on
2026-10-11. It is already an ancestor of the `v2.0.12` tag
(`81245da2`, 2026-10-13). Both that tag and the investigated checkout supply it
when authoring new chapter data. The existing public Library preparation tests
for adding chapters and repairing earlier chapter bodies passed before changes.

Thus the missing-`hedr` symptom has not been reproduced in this checkout. Retained
data from an older writer or an installed build that differs from the release tag
remain possible explanations, not established causes. Unchanged chapter data is
deliberately retained even during unrelated edits, under ADR-0006. An upgrade or
an unchanged Sync does not itself request a chapter edit.

The new 24-chapter video-import regression was also replayed against isolated
source archives, using the same locked environment and current test harness:

- `b246a6c26c14`, immediately before the October 11 fix, fails with 24 `sean`
  children and no `hedr`. Its `sean` size is 1,490 bytes; with the 12-byte preamble
  the payload is 1,502 bytes, matching the reported size for these chapter titles.
- `v2.0.12` passes the terminal-atom and child-count assertions, then fails on
  the header-byte difference described below.

This reproduces the historical omission and verifies the release-tag distinction;
it does not identify the reporter's installed executable or retained source data.

## Reproduced binary difference

The Original iOpenPod 1.68.1 chapter writer emits the big-endian `sean` field at
atom offset `0x08` as `1`. The 2.x shared definition defaulted it to `0`, including
after the terminal-atom fix. A fixed reference generated with synthetic input
from the unmodified Original writer exposed this mismatch through the public
Library preparation API:

```text
uv run pytest tests/iPodDB/library/test_chapter_writing.py -q
12 failed: at payload byte 23, 0x00 != 0x01
```

The tests exercise both new imports and existing Tracks, audio and video, a single
chapter, non-ASCII and supplementary-plane titles, and 24 chapters. Before the
fix, every case already contained a final `hedr` with the correct child count.
The complete bodies match the Original fixtures after changing the shared
`sean` authoring default to `1`. The existing explicit repair of the recognized
older shape now sets that field as well as adding `hedr`.

Source evidence:

- [Original iOpenPod 1.68.1 chapter writer][original] writes `sean` field `1`,
  chapter names as UTF-16BE, and a 28-byte terminal `hedr` with fields
  `(1, 0, 0, 0, 1)` after its size and marker.
- [libgpod's chapter writer][libgpod] emits the same fields.
- [foo_dop's chapter writer][foo-dop] also emits a terminal `hedr`, but writes
  `0` in that `sean` field. Consequently, the field's firmware meaning and the
  claim that `0` alone causes navigation failure are not established. The fix
  restores the project's Original compatibility baseline; it is not hardware
  proof of the report's proposed cause.

## Preservation and verification

The shared definition changes the default for newly constructed headers. Parsed
values remain explicit, and low-level serialization does not normalize them.
The existing Library repair remains limited to an explicit chapter edit and its
recognized earlier shape. Opaque atoms suppress repair and retain their bytes.
No-op saves and unrelated title edits preserve the chapter body byte-for-byte.

The fixtures in `tests/fixtures/writing/chapters-original.json` record their source
commit, file hashes, synthetic inputs, and complete payloads. They require no
Original iOpenPod runtime dependency and contain no captured user database data.

Physical chapter navigation still needs a test on the reported Classic. The
reporter's before/after database snapshots and exact installed build would resolve
the missing-atom/version discrepancy. A useful comparison would use identical
chapter inputs and inspect the actual saved MHOD type 17 before testing playback.

## Validation results

- `uv lock --check`, Ruff formatting and linting, Rumdl, and Mypy passed.
- The 15 focused chapter cases passed, including complete Original-byte
  comparisons and no-op, unrelated-edit, and opaque-atom preservation.
- `uv run pytest tests/iPodDB -q`: 1,547 passed.
- `uv run pytest -q`: 5,919 passed, 14 skipped, one failure. The failure was
  `test_finished_color_jobs_release_images_after_cache_eviction` in
  `tests/iOpenPod/GUI/presentation/test_artwork_provider.py`, timing out while
  waiting for cached artwork images to be released. The same module also failed
  at the same assertion against an isolated, unmodified `f6c50adf` source archive,
  after passing in earlier runs. This is an existing intermittent failure outside
  chapter writing; it was not changed as part of this investigation.

[original]: https://github.com/TheRealSavi/iOpenPod/blob/de300074a25f6f327b54a7141720e5fbff9d5c5b/src/iopenpod/itunesdb_writer/mhod_writer.py
[libgpod]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L4176-L4222
[foo-dop]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/chapter.h#L169-L188
