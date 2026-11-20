# ADR-0288: Resolve Classic Genius from qualified running firmware

- Status: Accepted
- Date: 2026-11-18
- Amends: ADR-0175's exclusion of cross-flashed Classic Genius support
- Extends: ADR-0201 and ADR-0284
- Amended by: [ADR-0289](0289-author-classic-genius-mixes-in-binary-playlist-datasets.md), which adds Classic Mix authoring

The shared updater-family-38 / RetailOS-2.0.5 image runs on earlier Classic
hardware, including the user's 120 GB Classic. Its Genius Mix support must not
inherit that model's stock 2.0.1 restriction. Refine exact Device Profiles using
the existing qualified Firmware Target resolver. A matching shared OS enables
native Genius Playlists and Mixes while retaining physical model, generation,
capacity limits and database capabilities. Catalog baselines remain immutable.

Use the highest authority across release and OS Updater Family observations for
this exception. Both fields must be present and agree at that authority. A
current incomplete or conflicting response must not complete itself from stale
metadata. A complete cached pair remains last-known evidence; ADR-0284 requires
fresh probing and contract reload when current OS identity changes. Preserve the
existing Classic 7G numeric 2.0.3 threshold for its stock release policy. Arbitrary
new version strings, updater families, bootloader markers and Mod Platform
Versions do not enable new Genius contracts.

Native capability does not imply that iOpenPod can author every database format.
The current Mix writer supports SQLite Library targets; Classic retains its
binary iTunesDB target and separate Genius relationship companion. Show the Mix
section on qualified Classic firmware, but explain that iOpenPod cannot yet
create Mixes for it when disabling Add and Settings. Do not change the writer
guard or substitute a Nano database layout. Classic native Mix authoring and
physical Mix playback qualification remain separate work.

Regression tests cover older Classics with the shared OS, unchanged physical
profiles/catalog objects, stale and incomplete firmware evidence, device refresh,
and the actual Genius page. No firmware upload or device-library mutation is
required for this change.
