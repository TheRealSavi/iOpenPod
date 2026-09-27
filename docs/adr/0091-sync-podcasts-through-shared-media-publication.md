# ADR-0091: Sync Podcasts through shared media publication

- Status: Accepted
- Date: 2026-09-27
- Extends: ADR-0037 and ADR-0076

Podcast Sync uses the existing Sync reservation, Library Draft preparation, and
verified Storage Transaction. Manual Episode additions and removals, Sync Podcast,
Sync Podcasts, and ordinary Host Sync all enter this workflow. The document writer
continues to write only subscription metadata and Listening History. This extends
ADR-0037's intentionally deferred media scope without creating another device-media
writer. Ordinary Sync Review discloses that subscriptions' saved settings can add
and remove Episodes, even when there are no selected Host media changes.

Original iOpenPod's `src/iopenpod/podcasts/models.py` and
`src/iopenpod/podcasts/podcast_sync.py` provide the behavioral baseline. Each Subscription
has 1–50 Episode slots (default 3), Newest or Next ordering (default Newest), a
clear-listened choice (default enabled), a time-on-iPod threshold (default Never),
and Remove or Replace clearing (default Remove). Slots are an automatic filling
target. Manual additions may exceed it, and neither exceeding nor lowering the
target alone authorizes removal. Four Episodes can remain against a target of three.

In both modes, an Episode is eligible for clearing when either the enabled listened
rule or the time-on-iPod rule applies. Age is measured from the Track's date added,
not publication. Explicit listened/unlistened overrides remain authoritative.
Newest fills vacancies with the newest eligible publications and replaces an
existing Episode only when it is clear-eligible and a newer publication is
available. Retained chronology for successful automatic clears prevents later
Syncs from filling with older publications. Next starts with the oldest available
Episode when no listened publication is known, otherwise after the furthest listened
publication. It skips Episodes already on the iPod and automatically cleared
identities. Skipped identities do not advance the chronological listening position.
An unlistened Episode cleared by age stays unlistened and is excluded from automatic
selection; explicit Add bypasses that exclusion. No starting-position control is
introduced.

Remove clears eligible Episodes independently of additions. Replace pairs each
conditional removal with an incoming Episode and retains the old Track until its
replacement succeeds. These one-for-one replacements remain available above the
slot target without reducing the count solely to meet it. A failed feed refresh
skips that show's managed changes. Independent successful shows and Host media can
still complete, with failures reported.

Sync reloads current Podcast documents under its device reservation, reconciles
Library membership, and saves refreshed history facts before media publication. A
history failure prevents those changes. New automatic-clear exclusions are derived
only from actual removals in the final Library Draft, then published in the same
verified Storage Transaction as media and Library changes. Failed replacements,
cancelled publication, and removals outside automatic Podcast clearing do not
create exclusions. Downloads stream into bounded private Host files owned by
Storage, validate HTTP(S) redirects and transfer length, and use the common media
transcoder and Device Profile. Publisher metadata supplies Episode identity, feed
URL, release date, Podcast classification, and playback flags. iPodDB maintains the
native Podcasts Playlist during the same verified Library preparation.

The Sync worker obtains publisher covers through the existing bounded Podcast
artwork loader and supplies owned pixels to shared ArtworkDB and thumbnail
preparation. Covers publish in the same Storage Transaction as the Library.
Automatic Podcast Sync also fills missing covers on retained Episodes from
successfully refreshed subscriptions without downloading their media again.
Existing covers are preserved. Cover failures are reported as warnings and do not
prevent an otherwise valid Episode from syncing.

Both documents now encode version 2 at the existing `subscriptions-v1.json` and
`listening-history-v1.json` paths. Subscriptions retain typed Sync settings; Listening
History retains publication dates, episode numbers, and automatic-clear exclusions
separately from listened state. Version 1 reads with compatible defaults and upgrades
on its next save. One authoritative path avoids diverging copies, and the version
bump makes older readers fail closed instead of dropping settings or history facts.
Podcast Episodes remain runtime projections. Invalid or unsupported documents are
preserved.

Dedicated Podcast Sync does not overwrite the Library Sync Helper with an empty
Host scan or retain temporary download paths as Host provenance. Device media and
database publication, cancellation, restoration, and cleanup retain the common
Sync guarantees. No new dependency or background schedule is introduced.
