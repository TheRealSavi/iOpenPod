# ADR-0089: Make interrupted Sync recovery a device-scoped choice

- Status: Accepted
- Date: 2026-09-26
- Supersedes: ADR-0076's Host recovery hints and mandatory-restoration policy
- Extends: ADR-0029

An interrupted Storage Transaction retains original files and an Operation Journal
under `.iopenpod-recovery` so restoration can reverse partially published changes.
This protection is useful, but persisting the journal path as a global setting
made a stale hint sufficient to lock an unrelated Library. Discovery also stopped
at the first pending journal, and there was no way to decline restoration when
later file changes or a corrupt journal made recovery impossible.

The device journal is the durable recovery record. Sync no longer persists recovery
or cleanup hints on the Host. Existing hint keys are removed from the settings
store and omitted on its next save; other preferences remain unchanged. No new
Host persistence is needed. Selection rediscovers terminal cleanup reminders from
the device itself.

Discovery lists an iPod with unfinished recovery as a selectable Device Candidate
without reading its interrupted Library. Selecting it presents **Restore Previous
Library** and **Keep Current Contents** before metadata repair or Library loading.
An unrelated iPod remains discoverable and usable. Restoration retains the existing
identity, precondition, verification, and cleanup requirements.

After an explicit warning and confirmation, Keep Current Contents renames the
selected `transaction.json` to `declined-transaction.json` beside its retained
payloads through Storage's fingerprint-checked move. It changes no media or Library
database files and deletes no recovery copies. The normal scan recognizes only
active journals in Storage's transaction namespaces, so this decision survives
restart and travel to another Host. Reloading after this decision skips metadata
repair as well. This is neither a verified commit nor a successful rollback.

A corrupt journal can be declined only using the Physical Device, Volume, and
journal fingerprint captured when it was discovered. A result not yet discovered
must first pass Storage's journal identity validation. Missing journals on an
observed device can be dismissed; changed journals, ambiguous matches, replacement
devices, and unavailable write access cannot authorize the move. Another pending
journal remains a separate choice.

If the retained Library cannot be parsed, the app reports that failure without
reinstating the declined recovery lock. The user may need to repair the Library
externally. Retained copies still occupy space and are available for manual
recovery; automatic restoration of a declined transaction is no longer offered.
Terminal cleanup can likewise be declined without restoring files. This preserves
the user's escape path without silently deleting the only copies of earlier data.
