"""Threaded access to one instrument connection."""

from collections.abc import Callable

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, Signal, Slot

from .instrument import Instrument
from .transport import Transport


class _DeviceWorker(QObject):
    connected = Signal(str, object, object)
    status_changed = Signal(object)
    disconnected = Signal()
    error = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, transport_factory: Callable[..., Transport]):
        super().__init__()
        self._transport_factory = transport_factory
        self._transport = None
        self._instrument = None

    @Slot(str)
    def open(self, port: str) -> None:
        self.busy_changed.emit(True)
        self._close(False)
        try:
            self._transport = self._transport_factory(port)
            self._instrument = Instrument(self._transport)
            name = self._instrument.hello()
            if name != "STM32-MSI":
                raise OSError(f"Unexpected device: {name}")
            capabilities = self._instrument.capabilities()
            status = self._instrument.status()
            self.connected.emit(name, capabilities, status)
        except (OSError, RuntimeError, ValueError) as exc:
            self.error.emit(str(exc))
            self._close(True)
        finally:
            self.busy_changed.emit(False)

    @Slot()
    def close(self) -> None:
        self.busy_changed.emit(True)
        self._close(True)
        self.busy_changed.emit(False)

    @Slot()
    def refresh(self) -> None:
        self._run(lambda device: None, report_busy=False)

    @Slot(str, int)
    def configure(self, waveform: str, frequency_hz: int) -> None:
        self._run(lambda device: device.configure(waveform, frequency_hz))

    @Slot()
    def start(self) -> None:
        self._run(lambda device: device.start())

    @Slot()
    def stop(self) -> None:
        self._run(lambda device: device.stop())

    def _run(self, command, report_busy: bool = True) -> None:
        if self._instrument is None:
            self.error.emit("Device is not connected")
            if report_busy:
                self.busy_changed.emit(False)
            return
        if report_busy:
            self.busy_changed.emit(True)
        try:
            command(self._instrument)
            self.status_changed.emit(self._instrument.status())
        except (OSError, RuntimeError, ValueError) as exc:
            self.error.emit(str(exc))
            if isinstance(exc, OSError):
                self._close(True)
        finally:
            if report_busy:
                self.busy_changed.emit(False)

    def _close(self, notify: bool) -> None:
        if self._transport is not None:
            self._transport.close()
        self._transport = None
        self._instrument = None
        if notify:
            self.disconnected.emit()


class DeviceSession(QObject):
    connected = Signal(str, object, object)
    status_changed = Signal(object)
    disconnected = Signal()
    error = Signal(str)
    busy_changed = Signal(bool)

    _open_requested = Signal(str)
    _close_requested = Signal()
    _refresh_requested = Signal()
    _configure_requested = Signal(str, int)
    _start_requested = Signal()
    _stop_requested = Signal()

    def __init__(self, transport_factory=Transport, parent=None):
        super().__init__(parent)
        self._thread = QThread(self)
        self._worker = _DeviceWorker(transport_factory)
        self._worker.moveToThread(self._thread)

        self._open_requested.connect(self._worker.open)
        self._close_requested.connect(self._worker.close)
        self._refresh_requested.connect(self._worker.refresh)
        self._configure_requested.connect(self._worker.configure)
        self._start_requested.connect(self._worker.start)
        self._stop_requested.connect(self._worker.stop)
        self._worker.connected.connect(self.connected)
        self._worker.status_changed.connect(self.status_changed)
        self._worker.disconnected.connect(self.disconnected)
        self._worker.error.connect(self.error)
        self._worker.busy_changed.connect(self.busy_changed)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    def connect_device(self, port: str) -> None:
        self._open_requested.emit(port)

    def disconnect_device(self) -> None:
        self._close_requested.emit()

    def refresh(self) -> None:
        self._refresh_requested.emit()

    def configure(self, waveform: str, frequency_hz: int) -> None:
        self._configure_requested.emit(waveform, frequency_hz)

    def start(self) -> None:
        self._start_requested.emit()

    def stop(self) -> None:
        self._stop_requested.emit()

    def shutdown(self) -> None:
        if not self._thread.isRunning():
            return
        QMetaObject.invokeMethod(self._worker, "close", Qt.ConnectionType.BlockingQueuedConnection)
        self._thread.quit()
        self._thread.wait(3000)
