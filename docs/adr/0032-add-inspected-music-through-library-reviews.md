# ADR-0032: Add inspected music through Library reviews

- Status: Accepted
- Date: 2026-09-12
- Extends: ADR-0030 and ADR-0031

Backend music import uses the existing Library Workspace, review, and Storage transaction.
FFprobe observations and Mutagen tags/artwork come from the same temporary captured
Host bytes. The application chooses a bounded music compatibility policy and
semantic fields; iPodDB owns native codec constants, identities, database links,
and thumbnail encoding. This implements compatible song import in the Application
Layer without a transcoder or Sync engine. GUI integration is outside this scope:
there is no Add Music button, file picker, startup import, or import progress dialog.

The draft retains each original Host source path with its observed size/hash,
rather than keeping temporary inspection copies alive until the user saves.
This limits temporary storage lifetime but means a moved, deleted, or changed
source must be selected again. The exact issued review binds its create-only
device destination and required content. Storage stages and verifies every source
before publication, then publishes songs, thumbnails, ArtworkDB, and iTunesDB in
that order. A source change cannot publish databases referring to unverified bytes.
Per-file replacement and retained recovery remain the transaction contract;
cross-file power-loss atomicity is not claimed.

Inspection produces one batch. The controller applies it only while its Active
iPod, workspace revision, and editability remain current. Pending imports have
temporary identities, can participate in Playlist edits, and disappear with their
resources on removal or discard. Save adopts the reparsed committed snapshot.

The initial policy supports mono/stereo MP3, M4A AAC LC up to an observed 320 kb/s,
16-bit ALAC on supporting profiles, and 16-bit PCM WAV/AIFF, at at most 48 kHz.
Unknown required limits cannot establish support. Embedded covers become bounded
RGB888 assets; observed VBR/ABR MP3 metadata supplies the native VBR flag. Exact
gapless delay, padding, and payload analysis remain separate work. No codec claim
establishes universal firmware compatibility or full-file decode validation.

End-to-end evidence includes a real MB565 Classic with an existing ArtworkDB,
HASH58 database, and four cover formats. Its added song and thumbnails were read
back and decoded; native links and the signature verified. Other firmware layouts
and creation of a first ArtworkDB still require their own evidence.
