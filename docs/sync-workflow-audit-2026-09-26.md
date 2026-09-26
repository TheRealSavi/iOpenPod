# Host scan and Sync audit — 2026-09-26

This review follows folder discovery through cleanup. It preserves the local
ADR-0082/0083 and progress changes that were already present. Tests publish only to
virtual Storage volumes; the connected physical iPod was inspected read-only.

## Findings and changes

| Step | Finding | Result |
| --- | --- | --- |
| Enumerate Host folders | One inaccessible subfolder aborted later sibling traversal; directory churn discarded useful observations. | Best-effort enumeration reports skipped entries and continues. Directory identity and no-link protections remain enforced. |
| Read metadata | Missing easy-tag support lost WAVE/AIFF ID3 titles and artists. Unrecognized optional tags were reported as problems. | Read ID3 text frames; use ordinary filename/basic-fact fallback without a warning for absent metadata. Invalidate older scan metadata through cache v8. |
| Fingerprint | Missing fpcalc aborted scanning; silent/short Tracks could not pass execution despite explicit Add in Review. | Preserve media without acoustic evidence, honor explicit Add, and store committed path provenance in helper v2. |
| Publish scan progress | Results waited in submission order behind a slow file. | Publish completed inspections immediately and retain deterministic final catalog order. |
| Match media | Missing fingerprints were discarded before proven prior Host paths could match. | Match prior Sync paths first; unavailable analysis does not manufacture an identity conflict. |
| Check tools | Photo-only and Playlist-only Sync required all audio tools. | Check FFmpeg/FFprobe only for incoming Tracks; unavailable tools do not prevent independent changes. |
| Inspect data streams | Successful FFprobe runs were rejected for any stderr text, including stale QuickTime chapter references. | Accept valid successful output, log diagnostics, then enforce stream limits and decode verification. |
| Prepare media | Multiple audio-only editions failed; duration comparison used the first stream even when another default was selected. | Choose the default/first audio stream, remux compatible audio, and compare the selected stream's duration. |
| Capture artwork | The 64 MiB image limit applied to an entire audiobook loaded into memory. | Use a seekable Storage stream and bound the embedded image. |
| Validate sources | An unavailable In sync Host file blocked unrelated additions. | Keep its existing device Track and skip affected Playlist reconciliation. Incoming sources are still revalidated. |
| Reconcile Playlists | Failed/excluded Track updates must not erase existing memberships. | Existing conservative mapping and source checks retained; blocked prerequisites are reported. |
| Prepare the Library | Any pending positional sidecar blocked Track membership changes. | Preserve/remap Play Counts and On-The-Go data with the same verified transaction and recovery journal. |
| Stage and publish | Device writes already use sequential staging, verification, preconditions, retained originals, and safe cancellation boundaries. | Retained these protections; tested sidecar edits before publication and restoration with the Library. |
| Record provenance | Missing fingerprints prevented successful copies from having usable subsequent matching history. | Store committed Sync Details independently of optional acoustic evidence. |
| Report and clean up | Expected lossy-conversion warnings and unresolved unselected items flooded the result. | Informational, grouped notices; preparation reports ready/skipped counts and its active phase. Distinct recovery and cleanup outcomes remain. |

## Verification

Regression coverage includes stale chapter references, large sparse audiobook
artwork, missing tools, multiple audio streams, concurrent scan completion,
inaccessible subfolders, directory churn/replacement, explicit Add without an
acoustic fingerprint, repeat-Sync matching, mixed-media partial success, both
sidecar byte orders, opaque-byte preservation, and transaction restoration.

All five owner-provided Mitosis chapters completed actual Host preparation and
full decode verification. Embedded artwork decoded from all five Percy Jackson
audiobooks (202–312 MiB). A read-only check against the connected iPod's 704 Tracks
confirmed that appending a Track preserves its 19,808-byte Play Counts file exactly.
User media remains outside the repository and is not a test fixture.
Physical-device mutation or playback validation is not implied.

Final targeted regression run: **246 passed, 3 platform-specific skips**. UV lock
validation, Ruff formatting/lint, Rumdl, Mypy, and whitespace checks pass. The full
repository run passed 2,828 tests and skipped nine. One new public-interface import
failure was fixed and included in the passing regression run. Seven other failures
were reproduced against the initial workspace snapshot, including its preexisting
edits: four GUI assertions, a Windows-only binding import on macOS, a macOS firmlink
assertion, and the packaging icon-license path test. These remain separate from
this Sync change.

## Follow-up: publication appeared stuck at 485 of 485 files

The application log showed publication completed at 03:19:10 local time, followed
by an unreported readback pass. A precondition then failed for
`iPod_Control/Artwork/._F1055_1.ithmb`, a macOS AppleDouble companion mistakenly
captured as artwork. Automatic recovery inspection and restoration also lacked GUI
progress. Storage reached RESTORED at 03:32:13, but cleanup failed because macOS had
already removed a companion named `._retired-477.bin`.

Artwork inventory now excludes those companions. Terminal cleanup accepts entries
that are already absent while retaining path, journal, connection, and link checks.
The application distinguishes restored-but-not-cleaned-up from failed restoration,
and retries a verified RESTORED marker without another full media readback or
rollback. Verification, retained-file checks, flushing, recovery inspection, and
automatic restoration now have visible progress. Cancellation no longer freezes
those updates, and elapsed/last-update times remain visible.

The reported 174,765,580-byte GIF also reproduced the Photo source-size limit.
Oversized containers now produce a bounded PNG still via a seekable stream. The
actual file decoded to a 686,096-byte, 640 by 1138 PNG without modifying the Host
original. Helper v3 preserves separate source/result digests for repeat-Sync matching.
See ADR-0086. Physical-device observations for this follow-up remained read-only;
the existing recovery journal was confirmed to contain the RESTORED state.

Follow-up validation: **198 targeted tests pass**; the full suite reports
**2,838 passed, 9 skipped, and the same 7 baseline failures** listed above. The
reported GIF also completed the full Photo Sync workflow on a virtual Storage
volume. Later focused recovery/UI checks passed all 14 selected cases. Formatting,
lint, Markdown checks, and Mypy pass.

## Remaining limits

- An OS file read waiting on cloud hydration can still take time before reaching
  a cancellation checkpoint. There is no provider-specific hydration control.
- Current progress reports stages and completed files. It has no byte-rate report
  during a single large USB copy or continuous encoder percentage within a Track.
- Containers unsupported by the lightweight Host metadata reader may show basic
  scan facts until FFprobe runs during preparation.
- Missing or ambiguous matching evidence does not justify automatic removal or
  replacement. Explicit uncorrelated Adds can duplicate preexisting media.
- Photo preparation still retains a bounded 512 MiB batch, and optional Rockbox
  tagging still has a per-file memory bound. Larger batches need a streamed design.
- Malformed sidecars, unsupported positional changes, changed device dependencies,
  disconnects, bad decoded media, and inadequate staging space cannot safely be
  ignored. Errors should identify the affected file or phase.
- Playback history remains preserved in sidecars; applying it to the common Library
  Snapshot and Back Sync are separate work.
- Exact acoustic fingerprint equality remains the current content matcher; fuzzy
  correlation and representative firmware validation remain outside this fix.
