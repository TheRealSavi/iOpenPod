# ADR-0248: Edit qualified firmware Preferences

- Status: Accepted
- Date: 2026-11-07
- Extends: ADR-0097, ADR-0240 and ADR-0247

Settings > iPod Preferences now offers explicit Apply/Revert editing for native
fields whose saved representation, value domain and coupled updates are verified
in the latest studied firmware. Device Registry qualifies Mini 1/2, Nano
1/3/4/5/6/7, Video 5/5.5 and the four latest Classic targets from ranked identity
evidence. See the [exact release matrix](../research/preferences-model-coverage-2026-11-07.md).
iPodDB separately checks the artifact's framing and version. An identified model,
a familiar file size or a generic inverse codec alone does not qualify a write.
The [implemented field matrix](../ipod-preferences.md#qualified-firmware-preference-editing)
records the currently offered controls; new research does not automatically add
write authority.

iPodDB keeps native field definitions and edit semantics together, including
compound settings and preserved bit masks. Its public field descriptors expose
only evidenced domains. The Application Layer supplies translated choices and
retains unknown values until explicitly changed. Date and clock observations are
not normalized by an unrelated preference edit. The existing iTunesPrefs and
Saved Firmware DST Rules views remain separate and read-only in this workflow.

Pure inspection is a broader contract than authoring. Exact binary profiles and
named-store profiles produce immutable observations containing a raw value,
interpretation, category and explicit limits. Unknown values, partly understood
fields and bounded summaries of unclassified bytes remain visible. A binary
reset request permits inspection with a discard caveat while withholding edits.
The Application Layer merges observations with independently qualified editors
by logical key; observation metadata cannot supply an edit capability. The GUI
groups and searches these rows without changing drafts or publication authority.
This refines the existing capture/edit boundary rather than adding a new writer.

The native UI of Nano 5/6/7 uses `iPod_Control/Device/iPodSettings.xml` for the
qualified named settings. It is modeled separately from binary Preferences;
similar saved binary offsets do not establish a UI field. Its immutable document
retains all XML bytes and replaces only explicitly edited, unambiguous scalar
text. Missing files/nodes are not created. Qualified writes cover Brightness,
Sound Check and numeric EQ; other registered settings are observations.
Publication and no-op validation use the XML fingerprint, without
depending on the optional legacy binary blob. This extends the same editing
boundary rather than introducing another device mutation path.

Nano 4's extensionless `iPod_Control/Device/iPodSettings` is a separate read-only
store alongside its qualified binary editor. Nano 6's
`iPod_Control/Device/iPodTimerSettings.xml` is also read-only and independently
captured. Its deadline is a civil calendar value without a timezone: Whenever
validates and formats its components without resolving a Host offset or DST.
Malformed datetime state remains raw and nonblocking. The optional legacy Nano
5/6/7 binary blob has only its own qualified observations; similar framing never
imports Classic clock semantics or makes it a prerequisite for XML edits.

The Application Layer captures one source revision, reserves the Active iPod and
publishes through a source-fingerprinted Storage Transaction. It rechecks the
device identity, firmware metadata and source bytes before writing; an issued
catalog cannot be substituted, reused after a save or transferred to another
connection. Missing files are not manufactured. No-op edits still check source
freshness. Device changes cancel work and discard stale completion. Ordinary
preference errors stay within Settings; only an actual transaction recovery
condition gates further device writes. This does not make Preferences a Library
publication dependency.

Successful publication means verified saved bytes. It does not assert that the
running firmware has adopted them: native Preferences owners keep a RAM copy and
can later serialize it. Firmware reload/adoption evidence and physical acceptance
must be documented separately from the byte contract. See the
[Classic investigation](../research/preferences-classic-writes-2026-11-07.md) and
[Mini/Video investigation](../research/preferences-mini-video-writes-2026-11-07.md).
