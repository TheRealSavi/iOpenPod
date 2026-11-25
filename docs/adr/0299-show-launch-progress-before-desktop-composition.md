# ADR-0299: Show launch progress before desktop composition

- Status: Accepted
- Date: 2026-11-24

## Context

Window creation waited for application imports, Host staging cleanup and every
Settings tab. The Windows standalone and MSIX builds also extract their embedded
runtime before Python starts (ADR-0108).

## Decision

Keep the single Windows executable. Use PyInstaller's bootloader splash to
display the application icon during extraction. It adds the small Tcl/Tk runtime
subset needed to draw before Qt is available. Dismiss it when the Qt loading
window paints. Center both on the display under the pointer at launch where
the window system permits it. Wayland compositors control final placement.
The Qt window keeps its initial Host colors, font and dimensions as the desktop
theme loads. Three dots show the completed stages. Unattended callers can set
`PYINSTALLER_SUPPRESS_SPLASH_SCREEN=1` to suppress the early artwork.

On every desktop, the first paint precedes application composition. Build the
context, window and native media session on the GUI thread, yielding to Qt
between stages. Run Storage's lease-protected staging cleanup in the background.
Construct Settings on first navigation and initialize it from current controller
state.

## Consequences

Closing the loading window ends startup. An update helper receives its health
handshake only after the main window opens. Onboarding and device discovery
continue to follow the launch health decision. The packaged smoke test imports
the deferred GUI composition without starting device workflows.
