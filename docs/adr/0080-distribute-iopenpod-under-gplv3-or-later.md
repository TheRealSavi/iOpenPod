# Distribute iOpenPod under GPLv3 or later

Status: Accepted

The owner wants free distribution with optional donations and accepts a license
change. iOpenPod directly uses GPL-2.0-or-later Mutagen, and the initial Qt preview
bundle included a GPLv3/commercial component. Adopt **GPL-3.0-or-later** for iOpenPod
instead of replacing those dependencies to preserve an MIT-only application.

Retain all third-party licenses. Include the GPL grant and license texts in Python and native
distributions, and provide corresponding source and required build materials for
each release. Optional donations do not change these obligations. Store-term
compatibility and the exact binary license inventory remain release gates; this
decision alone does not establish eligibility for every target store. See the
[licensing guide](../licensing.md).

The Windows release audit subsequently removed unused Qt PDF and Virtual Keyboard
plugins, supplied upstream native-library notices and source archives, and replaced
vendor-extracted device thumbnails with original illustrations. The source-built
PCM-only libsndfile avoids the SoundFile wheel's unpinned static codec provenance;
application media decoding continues to use user-installed FFmpeg. These packaging
changes do not change the application's GPL grant.
