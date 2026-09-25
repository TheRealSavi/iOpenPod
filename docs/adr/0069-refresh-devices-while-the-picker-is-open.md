# ADR-0069: Refresh devices while the Device Picker is open

- Status: Accepted
- Date: 2026-09-24
- Extends: ADR-0011 and ADR-0027
- Startup trigger amended by ADR-0071

The Device Picker should show newly connected iPods without a manual Refresh on
Windows, macOS, and Linux. The Original iOpenPod's scanner establishes the mounted-
volume discovery baseline; the existing Storage adapters retain that responsibility.
Use the shared background discovery path with an immediate pass when the picker
opens and another pass two seconds after each completion. Only the open picker
schedules discovery; closing it stops the loop, and reopening starts a fresh pass.
An in-flight read may finish after closing, but it cannot schedule another pass or
start automatic selection while the picker remains closed. Startup no longer scans
with the picker closed; remembered selection is restored when discovery runs.

Passes never overlap and defer during exclusive device operations or read
reservations. Automatic discovery reuses ready candidates only when their complete
Storage observations, including Connection Generation, are unchanged. New, changed,
and unready candidates are inspected again. Manual Refresh reinspects all candidates.
Unchanged results preserve picker selection, the Active iPod, and Library Drafts.
Automatic passes do not replace the Active iPod object merely to update discovery
metadata, which would invalidate unrelated application workflows.

The picker shows small, secondary-colored search text after a short delay so quick
checks do not flash. No sidebar search indicator is added. Automatic discovery
failures appear inline and retry; a failed remembered selection is attempted only
once per connected candidate until explicit Refresh or reconnection permits a retry.

This changes ADR-0011's explicit-refresh limitation and ADR-0027's startup trigger.
It does not implement native device-event subscriptions or replace Storage's
connection validation. Polling can miss a disconnect/reconnect between snapshots;
native connection monitoring remains required for broader destructive workflows.
