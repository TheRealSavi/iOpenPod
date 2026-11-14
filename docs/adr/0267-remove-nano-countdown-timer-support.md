# ADR-0267: Remove Nano Countdown Timer support

- Status: Accepted
- Date: 2026-11-13
- Partly supersedes: ADR-0248, ADR-0259 and ADR-0260 for Nano timer support

By explicit user direction, Nano 6/7 Countdown Timer functionality is outside
iOpenPod's scope. Remove its page content, editor, application intents, firmware
qualification, file capture and publication paths, codecs, sound catalog and
dedicated Preferences observations. Alarms navigation depends on native Clock
Alarm support; native Sleep Timer availability alone does not expose it.

The shared named Preferences parser and unrelated Nano settings remain supported.
Nano 6's separate timer file is not read or written. Timer values in the ordinary
named store remain generic Unknown Data and survive unrelated edits unchanged.
Native capability metadata and historical firmware research remain evidence of
device behavior, not authorization to reintroduce the removed workflow.

Regression coverage verifies absent Nano 6/7 navigation and Alarm qualification,
no timer-file reads in Extras, and byte preservation during ordinary Preferences
edits. Existing Clock Alarm, Calendar and Tones behavior remains in scope.
