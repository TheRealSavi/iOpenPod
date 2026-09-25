# ADR-0023: Capture write requests and inspect them without replay

- Status: Accepted
- Date: 2026-09-05
- Extends: ADR-0021 and ADR-0022
- DEBUG logging policy extended by [ADR-0028](0028-record-library-write-debug-diagnostics.md).

## Context

Developers need to understand which draft was submitted, why preparation blocked,
what binary output was produced, and why a completed result became stale. The
application previously passed desired state and source separately, retained the
workspace revision elsewhere, and presented preparation as one broad step.

An editable JSON dump or replayable operation history would introduce another
representation to reconcile. Neither can reproduce private source bindings,
occurrence metadata, or device-session authority from common Library values alone.

## Decision

Capture one immutable `LibraryPreparationRequest` containing the complete desired
snapshot, the loaded Active iPod, workspace generation and edit revision, and the
explicit omission-deletion policy. These application messages live separately from
the Qt controller. The coordinator checks the captured source, then binds an iPodDB
Library Draft to its retained documents. The common Library contract remains free
of application and Storage dependencies.

The desired snapshot remains the editing contract. Changes are derived analysis,
not a second writable command list. iPodDB retains its existing begin/analyze/prepare
interface. Pure preparation optionally reports entered stages; a caller can raise
at a checkpoint to cancel. Stage entry never claims verification or completion.

The controller retains a bounded trace for its latest preparation/save attempt.
Its inspection report shows source and workspace bindings, before/desired/prepared
values, requirements, supplied resource evidence, output sizes and hashes, identity
mappings, and structured issues. The last completed review remains inspectable
after invalidation, separately from the current saveable review. Stale reports do
not re-enable saving. A new preparation replaces the prior inspection context.

Inspection is read-only and on demand. It neither reruns analysis nor reads device
files. JSON is a versioned diagnostic representation, with explicit truncation,
not an import format, persisted draft, save capability, or replay log. Binary data
is represented by size and hash. Signing GUIDs are not dumped. Library metadata
can appear, so copying a report is an explicit UI action. Ordinary stage logging
contains phase codes rather than Library metadata.

## Consequences

The same request and report can be used by a debugger, application tests, or the
Review Changes dialog. Preparation and commit remain distinct, and Storage keeps
ownership of device mutation and recovery. Developer visibility does not require
exposing Chunk references or changing the binary writer.

Reports are bounded and may omit values; original immutable Python records remain
available for deeper inspection. Trace elapsed times are observed by the controller
and include queued signal delivery, so they are not a precision profiler. Internal
relationship repair is still verified inside iPodDB rather than exposed as an
editable sequence of low-level write operations. Persisted drafts and replay across
source reloads would require a separate rebinding design.
