# ADR-0294: Use upstream USB backends for Classic DFU setup

- Status: Accepted
- Date: 2026-11-22
- Extends: ADR-0277 and ADR-0279
- DFU backend and permission policy superseded by: [ADR-0296](0296-use-bundled-libusb-with-platform-access-setup.md)

## Decision

Expose the existing Classic bootloader workflow on macOS and Linux. Storage
adapts Rockbox's IOKit device-open/control-request path on macOS and its libusb
configuration/interface/control-transfer path on Linux. Preserve the DFU request
fields, bounded lengths, timeouts and terminal failures consumed by the existing
wInd3x-derived probes. The bundled writer, input qualification, authentication,
journal handoff and result verification serve every Host.

Pin Linux's libusb through the libusb-package binary wheel and collect its shared
library into frozen distributions. Its build disables the libudev dependency.
Load the package's library by its complete path. A missing library fails the
runtime smoke check. This adds a small native dependency to the Linux distribution
and makes the selected backend reproducible across PyPI and frozen installs.

When Linux denies USB access, use the desktop's existing pkexec/polkit agent.
An isolated bundled helper validates the current sysfs connection and held USB
descriptor, then passes that descriptor to the original user over a private,
credential-checked Unix socket. libusb wraps the descriptor in the app process.
Both sides verify their peer's user identity. The helper exits after the handoff.
The application process owns every USB request. Administrator approval is scoped
to opening one device, whose permissions remain controlled by the operating system.
Authorization denial ends the attempt immediately, including result verification.
A further OS prompt requires the user to reopen setup or check the saved result.

macOS opens the retained IOKit Registry entry through IOUSBDeviceInterface197.
DeviceRequestTO gives synchronous requests explicit timeouts. Recheck Registry
identity and vendor/product on the held interface before using it. A busy device
fails the open. Connection generations and Storage leases retain their existing
roles across native handle ownership.

## Qualification

The 2026-11-24 distribution decision excludes Classic bootloader setup and
normal-USB firmware installation from the Windows MSIX. Package identity is
checked before creating either controller or reading pending installation
journals. Locally signed MSIX candidates exercise the same restriction.
The standalone Windows executable uses its ordinary device eligibility checks.

Automated checks cover native ABI framing, complete request forwarding, stale
connections, authorization failures, claim failures, descriptor ownership and
simulated installation/result verification on all three Host platform names.
Linux's native runtime check loads the packaged libusb and calls its version
function. macOS's check loads and binds its system frameworks. Physical bootloader
installation and result verification on Linux and current Intel/Apple Silicon
Macs remain required acceptance evidence.

Normal-USB firmware publication requires a Storage adapter that implements
exclusive SCSI Sessions. Windows, macOS and Linux supply these adapters (ADR-0276). See the pinned
[Rockbox backend](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/utils/mks5lboot/ipoddfu.c),
[Apple USB interfaces](https://github.com/apple-oss-distributions/IOUSBFamily/blob/main/IOUSBFamily/Headers/IOUSBLib.h),
[libusb device access](https://libusb.sourceforge.io/api-1.0/group__libusb__dev.html)
and [polkit authorization](https://polkit.pages.freedesktop.org/polkit/pkexec.1.html).
