# ADR-0014: Persist global settings through Storage

- Status: Superseded by ADR-0015
- Date: 2026-08-30

## Context

Global settings were persisted through Qt's native `QSettings` backend in the GUI,
while early startup used an unrelated in-memory store. This did not provide one
predictable settings file on every Host: Windows commonly used the Registry, and
the logging bootstrap could not read persisted settings at all.

ADR-0011 kept ordinary application files entirely outside Storage so the device
portal would not become a generic wrapper around every file used by iOpenPod. That
separation was too broad for settings persistence. It left platform path selection
and direct file I/O outside the boundary that owns safe Host filesystem access.

iOpenPod 2.0 has no existing user settings to migrate. A direct replacement is
therefore clearer than compatibility readers, deprecations, or schema migrators.

## Decision

Storage owns a narrow, generic Host configuration-file capability:

- `Storage.host_config_file()` resolves the conventional configuration location for
  the current Host without exposing platform branches to iOpenPod.
- `AtomicHostFile` reads bytes and publishes replacements through a flushed sibling
  temporary file and atomic replacement. On POSIX Hosts, new files are private to
  the user and the containing directory is flushed after replacement.
- The global settings file is named `settings.json` and lives at:
  - Windows: `%APPDATA%\iOpenPod\settings.json`, falling back to
    `~/AppData/Roaming/iOpenPod/settings.json`.
  - macOS: `~/Library/Application Support/iOpenPod/settings.json`.
  - Linux: `${XDG_CONFIG_HOME}/iopenpod/settings.json` when
    `XDG_CONFIG_HOME` is absolute, otherwise `~/.config/iopenpod/settings.json`.

iOpenPod continues to own all settings meaning. `JsonSettingsStore` owns setting
keys, validation-compatible values, UTF-8 JSON encoding, and the tagged Base64
representation of Qt byte arrays. Storage sees only an application name, filename,
and bytes; it imports no Qt, GUI, or iOpenPod knowledge.

Global changes are synchronized immediately. Early startup and the GUI use the same
store composition. The former `QSettings` backend and its platform-specific Registry
behavior are removed without migration or fallback.

ADR-0011 remains authoritative for device-facing Storage. This decision supersedes
only its statement that Storage may not participate in ordinary settings
persistence; settings semantics remain an iOpenPod responsibility.

## Consequences

Every supported Host now has one inspectable settings file at a conventional
location, and all reads and writes cross the same typed Storage boundary. Atomic
replacement prevents an interrupted write from exposing a partial JSON document.
Tests can verify each platform location and persistence without touching a user's
real configuration directory.

Storage gains one explicit Host-file capability but does not become a general
application-filesystem facade. Logs, caches, temporary files, and Backup Snapshot
policy remain separate decisions. Device-specific settings that travel with an
iPod still require a Filesystem Session and Device Path.
