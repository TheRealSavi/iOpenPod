# ADR-0251: Reconcile ratings through opt-in Host Back Sync

- Status: Accepted
- Date: 2026-11-10
- Extends: ADR-0005, ADR-0065 and ADR-0076

Native rating reads were promised in #291 and PR #293, but that PR contained
only tests. The recovered #292 implementation also lacked an opt-in and the
requested conflict policies. This change recovers that work without restoring its
older Sync or cache architecture.

Settings > Sync offers **Sync star ratings to Host files**, off by default.
Review captures that opt-in in the Sync Plan. Separate Host and iPod rating
baselines distinguish which side changed. A Host-only change updates the iPod;
an iPod-only change updates the Host; equal concurrent changes establish a new
baseline. Differing concurrent changes use the selected Host wins, iPod wins or
Average policy. Average rounds to the nearest whole star, with halves upward.
A deliberately cleared rating is zero. Unknown baselines establish observations
without authorizing a Host write. Reassociation cannot inherit another file's
rating authority. Only selected, successfully completed Track actions can write
a Host rating.

The iPod rating is prepared and verified through the ordinary Library transaction.
After that commit, Storage stages a private copy beside the paired regular Host
file, applies the rating transform, verifies it, rechecks file and session facts,
and atomically replaces the source. A failed Host update reports a partial Sync
and retains rating baselines for retry; it cannot roll back the verified iPod
commit. Cancellation prevents subsequent Host replacements. Existing POPM counters,
other tags, and audio payloads are preserved. Host source replacement remains a
Storage responsibility.

MP3 writes POPM; MP4 writes `----:com.apple.iTunes:RATING`, independently of the
content-advisory `rtng` atom; FLAC, Ogg Vorbis and Opus write `RATING`. Legacy
ID3v2.2 conversion is rejected. Exported ID3/MP4 copies receive the current Library
rating, including clears. Ratings do not authorize listening-history tag writes.
Host Media Scan Cache v17 refreshes previously unsupported native rating formats.

Tests use authored media and virtual devices. Physical iPods, native Windows and
network filesystem replacement still require acceptance on those platforms.
