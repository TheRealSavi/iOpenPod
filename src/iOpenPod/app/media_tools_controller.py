"""Nonblocking tool checks and sequential native package installation."""

from __future__ import annotations

import codecs
import shlex
import sys
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
    Slot,
)

from iOpenPod.app.services.media_tools import MediaToolSetup, inspect_media_tools

if TYPE_CHECKING:
    from iOpenPod.app.services.media_tools import InstallCommand


class _CheckCancelledError(Exception):
    pass


class _CheckSignals(QObject):
    finished = Signal(object, str)


class _Check(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = _CheckSignals()
        self.cancelled = Event()

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancelled.is_set():
                raise _CheckCancelledError

        try:
            result = inspect_media_tools(checkpoint=checkpoint)
        except _CheckCancelledError:
            self.signals.finished.emit(None, "")
        except Exception as error:
            self.signals.finished.emit(None, str(error))
        else:
            self.signals.finished.emit(result, "")


class MediaToolsController(QObject):
    changed = Signal()
    checked = Signal(object)
    output = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setup: MediaToolSetup | None = None
        self.message = ""
        self.checking = False
        self.installing = False
        self.stopping = False
        self._closed = False
        self._verifying_install = False
        self._job: _Check | None = None
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._commands: tuple[InstallCommand, ...] = ()
        self._index = 0
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._read_output)
        self._process.finished.connect(self._process_finished)
        self._process.errorOccurred.connect(self._process_error)

    @property
    def busy(self) -> bool:
        return self.checking or self.installing

    @Slot()
    def check(self) -> None:
        if not self.busy and not self._closed:
            self.message = ""
            self._check()

    def _check(self) -> None:
        self.checking = True
        job = _Check()
        self._job = job
        job.signals.finished.connect(self._checked, Qt.ConnectionType.QueuedConnection)
        self.changed.emit()
        self._pool.start(job)

    @Slot(object, str)
    def _checked(self, value: object, error: str) -> None:
        self._job = None
        self.checking = False
        if self._closed:
            return
        if isinstance(value, MediaToolSetup):
            self.setup = value
            if value.ready:
                self.message = self.tr("FFmpeg, FFprobe, and fpcalc are ready to use.")
            elif not self.message:
                self.message = (
                    self.tr(
                        "Package operation finished. Some tools still need setup; review the results and use Setup Help if needed."
                    )
                    if self._verifying_install
                    else self.tr("Some media tools need setup.")
                )
        else:
            self.setup = None
            self.message = self.tr("Could not check media tools: %1").replace(
                "%1", error
            )
        self._verifying_install = False
        self.changed.emit()
        self.checked.emit(self.setup)

    @Slot()
    def install(self) -> None:
        if (
            self.busy
            or self._closed
            or self.setup is None
            or not self.setup.plan.commands
        ):
            return
        self._commands = self.setup.plan.commands
        self._index = 0
        self.installing = True
        self.stopping = False
        self._start_command()

    def _start_command(self) -> None:
        command = self._commands[self._index]
        self.message = (
            self.tr("Installing %1 (%2 of %3)…")
            .replace("%1", command.label)
            .replace("%2", str(self._index + 1))
            .replace("%3", str(len(self._commands)))
        )
        self.output.emit(
            "\n" + shlex.join((command.program, *command.arguments)) + "\n"
        )
        environment = QProcessEnvironment.systemEnvironment()
        # Frozen Linux apps may prepend their bundled libraries. The native
        # package manager must use the Host's libraries instead.
        if sys.platform.startswith("linux"):
            if environment.contains("LD_LIBRARY_PATH_ORIG"):
                environment.insert(
                    "LD_LIBRARY_PATH", environment.value("LD_LIBRARY_PATH_ORIG")
                )
            else:
                environment.remove("LD_LIBRARY_PATH")
        self._process.setProcessEnvironment(environment)
        self._decoder.reset()
        self.changed.emit()
        self._process.start(command.program, list(command.arguments))
        self._process.closeWriteChannel()

    @Slot()
    def stop_after_current(self) -> None:
        if self.installing:
            self.stopping = True
            self.message = self.tr(
                "Waiting for the current package operation to finish. No further packages will be started."
            )
            self.changed.emit()

    @Slot()
    def _read_output(self) -> None:
        # Bound each signal; the dialog also bounds its retained log.
        while self._process.bytesAvailable():
            data = self._process.read(8192).data()
            if not data:
                break
            self.output.emit(self._decoder.decode(data))

    @Slot(int, QProcess.ExitStatus)
    def _process_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        if not self.installing:
            return
        self._read_output()
        tail = self._decoder.decode(b"", final=True)
        if tail:
            self.output.emit(tail)
        if code != 0 or status != QProcess.ExitStatus.NormalExit:
            self._finish(
                self.tr(
                    "Installation did not complete (exit %1). Review the details below, then retry or use Setup Help."
                ).replace("%1", str(code))
            )
            return
        self._index += 1
        if self.stopping or self._index == len(self._commands):
            self._finish("")
        else:
            self._start_command()

    @Slot(QProcess.ProcessError)
    def _process_error(self, error: QProcess.ProcessError) -> None:
        if self.installing and error == QProcess.ProcessError.FailedToStart:
            self._finish(
                self.tr("Could not start the package manager: %1").replace(
                    "%1", self._process.errorString()
                )
            )

    def _finish(self, message: str) -> None:
        self.installing = False
        self.stopping = False
        self._commands = ()
        self.message = message
        self._verifying_install = True
        if message:
            self.output.emit("\n" + message + "\n")
        self._check()

    def shutdown(self) -> None:
        """Cancel checks only; the window refuses to quit during package mutations."""
        if self.installing:
            raise RuntimeError("Wait for the package manager before closing iOpenPod")
        self._closed = True
        if self._job is not None:
            self._job.cancelled.set()
        self._pool.waitForDone()
