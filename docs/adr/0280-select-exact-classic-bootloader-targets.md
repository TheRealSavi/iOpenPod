# ADR-0280: Select exact Classic bootloader targets

- Status: Superseded in part by ADR-0281 (shared outputs); exact source qualification retained
- Date: 2026-11-17
- Extends: ADR-0278, ADR-0279

The user requested ports for the remaining Classic updater families. Original
ROM, Bds and IpodFirmwareFS executable sections match across families 24, 33, 35
and 38, so the implementation shares native hooks while retaining separately
pinned inputs, deltas, identity records, OSOS bounds and writer packing layouts.
Family 24's SecCore starts earlier and must retain its own tail. See the
[independent comparison and audit](../research/classic-bootloader-family-comparison-2026-11-17.md).

Device Summary selects the bundle from the observed updater family, exact Apple
release and retail model. The DFU phase independently checks the selected serial,
model, conservative SysCfg hardware profile, complete BootROM hash and
authenticated stock-loader hash; the writer still refuses any flash chip other
than the qualified SST25VF080B. Retail capacity and a shared model number never
substitute for updater-family evidence. Cross-version or cross-flashed hardware
combinations outside the profiles remain unsupported; this is an eligibility
policy, not an asserted Apple restriction.

Installation records retain the updater family so result-only recovery selects
the original bundle. Records from the prior family-33-only installer remain
readable. A mismatch cannot initiate another installation or reopen USB for a
pending result. The existing physically tested family-33 loader is recognized
without replacement, and its executable bytes remain unchanged.

Families 24/1.1.2, 35/2.0.4 and 38/2.0.5 are available as experimental ports in
the same wizard, with their lack of physical testing stated before starting.
Independent extraction, native emulation and simulated installation establish
offline behavior; they do not establish a physical boot, USB return or power-loss
recovery. Restore and Update retain their download-only behavior. Porting the
bootloader does not qualify the separate normal-mode OS upload on another family.
