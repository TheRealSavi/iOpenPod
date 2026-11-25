# ADR-0300: Restore the remembered iPod only at launch

- Status: Accepted
- Date: 2026-11-25
- Amends the restoration triggers in ADR-0027, ADR-0069 and ADR-0071.

Opening the Device Picker gives the user a choice among connected iPods.
Previously, discovering the remembered Volume during a picker refresh could
load its Library before the user chose a device.

Only the single startup discovery pass may automatically restore the remembered
Volume Identity. It uses the ordinary selection workflow when it finds a unique
eligible match. A choice the user makes during that pass takes precedence.
Opening the Device Picker, polling it, and using Refresh update the list of
Device Candidates. A later connection or a failed startup load requires an
explicit selection. The saved Volume Identity remains available for the next launch.
