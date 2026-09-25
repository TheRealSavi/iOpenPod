"""Qt bootstrap for iOpenPod."""

import logging
import signal
import socket
import sys
from collections.abc import Callable
from types import FrameType

from PySide6.QtCore import QCoreApplication, QSocketNotifier
from PySide6.QtWidgets import QApplication

from iOpenPod.app.context import AppContext
from iOpenPod.app.playback.system_media import (
    SystemMediaBridge,
    create_system_media_session,
)
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.presentation.application_icon import application_icon
from iOpenPod.GUI.presentation.display import configure_display
from iOpenPod.GUI.presentation.middle_mouse_scrolling import (
    install_middle_mouse_scrolling,
)

logger = logging.getLogger(__name__)

_WINDOWS_APP_USER_MODEL_ID = "iOpenPod.iOpenPod"


def start_ui() -> int:
    """Start iOpenPod and discover connected Device Candidates."""

    _set_windows_app_user_model_id()
    configure_display()
    application = QApplication(sys.argv)
    install_middle_mouse_scrolling(application)
    QCoreApplication.setApplicationName("iOpenPod")
    QCoreApplication.setOrganizationName("iOpenPod")
    from iOpenPod.app.core.version import get_version

    QCoreApplication.setApplicationVersion(get_version())
    application.setDesktopFileName("io.github.therealsavi.iOpenPod")
    application.setWindowIcon(application_icon())
    context = AppContext.create(application)

    window = MainWindow(context)
    window.show()
    system_media_bridge = SystemMediaBridge(
        context.playback_controller,
        create_system_media_session(window_id=int(window.winId())),
        application,
        artwork_controller=context.artwork_controller,
    )
    restore_interrupt_handler = _install_interrupt_handler(application)
    shutdown_complete = False

    def shutdown() -> None:
        nonlocal shutdown_complete
        if shutdown_complete:
            return
        shutdown_complete = True
        system_media_bridge.close()
        context.shutdown()

    application.aboutToQuit.connect(shutdown)
    try:
        return application.exec()
    finally:
        try:
            shutdown()
        finally:
            restore_interrupt_handler()


def _install_interrupt_handler(application: QApplication) -> Callable[[], None]:
    """Request Qt shutdown when the Host sends an interrupt to the process."""

    previous_handler = signal.getsignal(signal.SIGINT)
    interrupt_read, interrupt_write = socket.socketpair()
    previous_wakeup_fd = -1
    wakeup_fd_configured = False
    handler_installed = False

    def handle_signal(_signum: int, _frame: FrameType | None) -> None:
        """Keep SIGINT registered so Python writes it to the wakeup socket."""

    try:
        interrupt_read.setblocking(False)
        interrupt_write.setblocking(False)
        previous_wakeup_fd = signal.set_wakeup_fd(
            interrupt_write.fileno(),
            warn_on_full_buffer=False,
        )
        wakeup_fd_configured = True
        signal.signal(signal.SIGINT, handle_signal)
        handler_installed = True
    except Exception:
        if wakeup_fd_configured:
            signal.set_wakeup_fd(previous_wakeup_fd)
        interrupt_read.close()
        interrupt_write.close()
        raise

    shutdown_requested = False

    def handle_interrupt(_socket: object, _event: object) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            return
        try:
            while interrupt_read.recv(4096):
                pass
        except BlockingIOError:
            pass
        logger.info("Interrupt received")
        shutdown_requested = True
        application.quit()

    try:
        interrupt_notifier = QSocketNotifier(
            interrupt_read.fileno(),
            QSocketNotifier.Type.Read,
            application,
        )
        interrupt_notifier.activated.connect(handle_interrupt)
    except Exception:
        if handler_installed:
            signal.signal(signal.SIGINT, previous_handler)
        if wakeup_fd_configured:
            signal.set_wakeup_fd(previous_wakeup_fd)
        interrupt_read.close()
        interrupt_write.close()
        raise

    def restore() -> None:
        interrupt_notifier.setEnabled(False)
        if signal.getsignal(signal.SIGINT) is handle_signal:
            signal.signal(signal.SIGINT, previous_handler)
        if wakeup_fd_configured:
            signal.set_wakeup_fd(previous_wakeup_fd)
        interrupt_read.close()
        interrupt_write.close()

    return restore


def _set_windows_app_user_model_id() -> None:
    """Give unpackaged Windows launches a stable shell identity when possible."""

    if sys.platform != "win32":
        return
    try:
        import ctypes

        name_length = ctypes.c_uint32(0)
        package_status = ctypes.windll.kernel32.GetCurrentPackageFullName(
            ctypes.byref(name_length), None
        )
        if package_status != 15700:  # APPMODEL_ERROR_NO_PACKAGE
            # MSIX provides its own shell identity. Preserve it (also on an
            # unexpected identity-query error) instead of replacing it with
            # the unpackaged development identity.
            return
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            _WINDOWS_APP_USER_MODEL_ID
        )
    except Exception:
        logger.debug("Could not set the Windows AppUserModelID", exc_info=True)
        return
    if result:
        logger.debug(
            "Windows rejected AppUserModelID %s (HRESULT %s)",
            _WINDOWS_APP_USER_MODEL_ID,
            result,
        )
