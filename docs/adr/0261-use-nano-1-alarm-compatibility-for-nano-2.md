# ADR-0261: Use Nano 1 alarm compatibility for Nano 2

- Status: Accepted
- Date: 2026-11-13
- Amends: ADR-0247, ADR-0259 and ADR-0260 for Nano 2

City creation/removal is subsequently included by explicit user request in
[ADR-0263](0263-author-clock-cities-and-native-alarm-playlist-selections.md).
The earlier scope below records the initial existing-record workflow.

The user explicitly directed Nano 2 alarm behavior to follow Nano 1 instead of
waiting for hardware decryption. iOpenPod therefore selects the existing per-city
Clock Alarm codec and Nano 1 Playlist projection for identified Nano 2 1.1.3
devices, with updater families 19/29 when supplied. This is a compatibility
assumption, not evidence that the encrypted Nano 2 firmware has been inspected.
Research reports retain that distinction.

The existing editor can change saved time, enabled state, Beep and source-bound
Playlist selection when the captured `iPod_Control/Device/clock` file passes the
same structural and field checks as Nano 1. Unknown fields and sibling cities
remain unchanged. Missing, malformed or ambiguous stores do not authorize
inventing a clock collection. City creation/removal and live accessory Radio
selection remain outside this existing workflow. Matching identity and source
preconditions are rechecked before Storage publishes any edit.

Library publication leaves Alarm selections unchanged, following the subsequent
user direction in [ADR-0262](0262-leave-alarm-selections-unchanged-during-library-writes.md).
The new firmware identity does not enable a Nano 2
Preferences codec or other unrelated write capabilities. Registry tests cover
both updater families, identity conflicts and the Preferences exclusion; virtual
Storage tests cover source-bound sound changes and preservation through the
existing per-city editor. Physical acceptance and decrypted firmware comparison
remain unverified.
