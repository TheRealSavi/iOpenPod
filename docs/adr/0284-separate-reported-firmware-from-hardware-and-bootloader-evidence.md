# ADR-0284: Separate reported firmware from hardware and bootloader evidence

- Status: Accepted
- Amended by: ADR-0287 adds a native Bootloader Report and a current-USB update path;
  the historical limitations below describe the earlier release.
- Date: 2026-11-17
- Supersedes: ADR-0220's cross-connection probe suppression and ADR-0282's
  running-release-derived hardware selection

A Classic 6.5 running the common image reports OS updater family 38 and version
2.0.5 while its physical SysCfg still identifies hardware family 33. A stock
family-38 iPod can report the same OS fields. Neither those fields nor a saved
installation receipt proves which bootloader is installed now.

Read live device metadata on each new connection, app discovery and explicit
refresh. Unchanged automatic polling still reuses its connection's observation.
SysInfo Authority continues to record provenance and protect metadata
reconciliation, but no longer suppresses those probes. Discovery remains read-only.
Selection reconciles metadata through the existing Storage workflow.

Keep current-observation flags separately for reported firmware and OS updater
family. Label fallback values as cached and require both current values for an OS
installation. A live response supersedes the entire cached firmware identity,
including omitted fields; do not combine current and stale fields into a qualified
firmware contract. If explicit refresh changes the loaded OS identity, retire its
loaded contracts and let the remembered-device selection reload them. Transport
revisions remain separate from firmware releases. Reported 2.0.5 alone never means
that the custom OS or unlocked loader is installed.

Select bootloader setup by supported physical model and product serial, independently
of OS version and updater family. Model numbers shared by hardware revisions 35
and 38 leave the hardware family unresolved. DFU reads SysCfg to determine the
actual revision and checks the selected serial/model before selecting a migration.
Retain legacy operation fields only to resume existing installation journals.
Carry the observed OS version and updater family separately in new operations and
compare them with a fresh normal-USB read immediately before upload. Do not infer
the running version from a hardware-family release table.

Decode the Bootloader Identity Record from established slots in the decrypted
device-read loader. Reject damaged or duplicate markers. A recognized marker still
requires the complete qualified executable hash before treating the shared loader
as installed. A missing marker means unidentified, not proven stock. The existing
DFU setup checks before writing and leaves the qualified current loader unchanged.

Device Summary labels the saved bootloader version and SysCfg hardware family as
**last verified in DFU**. The same-device, qualified receipt remains the prerequisite
for routine normal-USB OS updates; it is not a live unlock measurement. Normal USB
in the currently shipped OS has no qualified NOR reader. A different Host or an
external bootloader replacement requires repeating DFU setup. In particular, a
stock restore reporting the same 38/2.0.5 cannot be detected from those fields.
Automatic current bootloader detection in normal USB requires a future native
firmware reporting interface; this change does not invent such an observation or
claim a new physical firmware test.
