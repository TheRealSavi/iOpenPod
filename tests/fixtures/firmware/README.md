# Firmware fixtures

`classic-boot-report.xml` is the output of the compiled 0.6.0-dev ARM report hook
and Apple's native XML writers under emulation. It uses synthetic serial
TEST12345678, model MB565, hardware revision 0x130100 and the public identity/hash
of the shared 2.1.0 bootloader. It contains no device keys or personal capture.
The host tests consume it independently of the firmware encoder.

See [native probe evidence](../../../docs/research/classic-bootloader-report-2026-11-18.md)
for its origin and limits. The native result is not a physical USB observation.
