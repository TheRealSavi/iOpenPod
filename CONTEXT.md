# iOpenPod Context

iOpenPod manages media and metadata on an iPod from a desktop library, including planning changes, reviewing them, writing them, and preserving device state.

## Language

**Sync Session**:
A user-initiated attempt to plan and apply PC-to-iPod media changes for the connected iPod, from readiness checks through review, execution, cancellation, or completion.
_Avoid_: Sync job, sync workflow, sync task

**Sidebar Navigation**:
A source-list style set of rows that switches the visible page, media category, or collection. Selected rows share one visual state across the application: neutral selection background, primary text, and an accent-colored navigation glyph. Rich rows may preserve artwork and secondary text while consuming the same state policy.
_Avoid_: Treating command buttons, horizontal action tabs, or arbitrary supporting panes as Sidebar Navigation
