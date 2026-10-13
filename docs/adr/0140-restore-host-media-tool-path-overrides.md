# Restore Host media-tool path overrides

- Status: Accepted
- Date: 2026-10-13
- Amends: ADR-0103's executable discovery precedence

[Issue #241](https://github.com/TheRealSavi/iOpenPod/issues/241) requests the Original
iOpenPod's custom executable paths for installations
whose media tools are outside automatic search locations. Retain independent Host-only
FFmpeg, FFprobe, and fpcalc paths in the existing v2 settings file. Empty values use
Storage's PATH and package-location discovery. Do not migrate Original settings or
store computer-specific paths on an iPod.

An explicit override takes precedence even when it cannot run. Tool checks retain
the selected path and report the execution failure instead of silently choosing a
different build or offering installation to replace it. This makes encoder selection
predictable and leaves recovery to correcting or clearing the path. Normal bounded
version and encoder checks still apply. Paths are executable filenames, not shell
commands; sandbox access and library compatibility remain installation prerequisites.

The Original iOpenPod skipped missing overrides and inferred FFprobe from FFmpeg's
directory. The new independent FFprobe field makes that choice explicit, while
retaining failed overrides keeps setup diagnostics consistent with subsequent use.

Application composition injects a shared configured lookup into media consumers.
The settings owner publishes immutable path choices for workers; Storage keeps
filesystem discovery and process execution and never imports application settings.
Saved edits affect subsequent lookups. Already captured paths and running processes
remain with their operation, including fpcalc's existing per-scan cache. Retrying a
failed scan or Sync remains a user action.
