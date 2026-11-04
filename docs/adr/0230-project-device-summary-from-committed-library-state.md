# ADR-0230: Project Device Summary from committed Library state

- Status: Accepted
- Date: 2026-11-03
- Extends: ADR-0019

## Context

Device Summary needs an Apple-inspired device portrait, identity details, and
color-coded capacity without adding device access or implying that unsaved Library
edits have already changed the Volume. The Original iOpenPod's
`src/iopenpod/gui/widgets/sidebar.py` at `origin/1.x` (`a2024242`) presents observed
total/free capacity and a separate database-size meter. This preserves its total/free
capacity behavior; media category estimates and the summary page are new.

## Decision

Device Summary presents the Active iPod's Device Profile,
committed Library Snapshot, captured content-folder sizes, and Device Candidate
capacity observation. Non-button
areas of the sidebar device information open the page; existing device controls
keep their actions. The page uses the shared theme, typography, and bundled device
artwork. Its Restore iPod button is always disabled beside “Coming soon” and has no
device operation attached.

The name field also offers a pencil button for inline renaming through the
existing Library Workspace workflow. Enter, focus loss, or Apply validates the
captured edit revision; Escape or Cancel discards the entry. Device changes,
Library replacement, and unavailable editing cancel pending input. Saving follows
the existing automatic or manual Library save setting; capacity remains based on
committed state.

Firmware version and product serial come from already captured Device Evidence,
with current hardware preferred over metadata and equally authoritative conflicts
left unavailable. Original observations survive selection-time metadata
normalization for this display decision. Derived values, transport revisions, and
USB or FireWire serials do not substitute for these fields. Missing evidence is
shown as unavailable; opening the page does not trigger a probe.

The Application Layer computes immutable byte segments for Music, Videos,
Podcasts, Audiobooks, Photos, Games, Album artwork, Other, and Free. Media estimates use indexed
file metadata, not a filesystem allocation scan. Repeated Track locations count once;
conflicting classifications remain Other. Photos count the union of stored
representation ranges per file, excluding source-image sizes whose originals may
never have been copied. Invalid sizes and missing locations cannot establish
categorized bytes.

Games counts all regular files beneath `iPod_Control/Games_RO`,
`iPod_Control/GameData_RW`, and `iPod_Control/GameStats_WO`, including shared files,
unrecognized installations, saved data, and statistics. Selection captures their
logical file sizes through the identity-bound Storage session with cancellation
and bounded enumeration; it never reads file contents or follows links. The
immutable Active iPod retains the total until the next load. Missing folders count
as zero; a failed measurement is logged and leaves those bytes in Other without
blocking Library loading. Disconnection and cancellation still stop selection.
Library locations inside these folders cannot contribute a second category.

Album artwork counts all regular files beneath `iPod_Control/Artwork`, including
ArtworkDB, thumbnail shards, unused shard bytes, and unrecognized files. It uses
the same bounded selection-time capture and failure policy as Games, independently
of whether ArtworkDB can identify the contents. Library locations in that folder
cannot contribute another category. Games uses pink and Album artwork uses cyan
through shared theme tokens for the capacity bar and legend.

Other retains remaining used capacity, including unindexed files outside measured
folders, remaining databases, filesystem overhead, and unused Photo shard space.
Free uses the captured
Volume observation. If categorized sizes exceed observed used capacity, category
estimates are withdrawn and the page shows used/free capacity with an explanation.
Unknown capacity stays unavailable. Values are bounded; categories are never
proportionally rescaled to manufacture a plausible breakdown.

## Consequences

Opening the page performs no device reads or writes and grants no filesystem
authority. Unsaved rename presentation may follow the Library workspace, while
capacity remains tied to committed Active iPod state. Device
changes replace that projection and disconnection clears it. Physical allocation
measurement, further device identity evidence, and firmware restore would need
their own Application Layer workflows and Storage access policies.
