"""Threaded access to one instrument connection."""

from collections.abc import Callable

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, Signal, Slot

from .instrument import Instrument
from .transport import Transport


class _DeviceWorker(QObject):
    connected = Signal(str, object, object)
    status_changed = Signal(object)
    scope_status_changed = Signal(object)
    capture_ready = Signal(object)
    logic_status_changed = Signal(object)
    logic_capture_ready = Signal(object)
    device_status_changed = Signal(object)
    mixed_status_changed = Signal(object)
    mixed_capture_ready = Signal(object)
    disconnected = Signal()
    error = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, transport_factory: Callable[..., Transport]):
        super().__init__()
        self._transport_factory = transport_factory
        self._transport = None
        self._instrument = None
        self._capabilities = {}
        self._mixed_active = False

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
            self._capabilities = capabilities
            statuses = self._read_statuses()
            self.connected.emit(name, capabilities, statuses)
            self.scope_status_changed.emit(self._instrument.scope_status())
            self.logic_status_changed.emit(self._instrument.logic_status())
            self.device_status_changed.emit(self._instrument.device_status())
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
        """Poll the unified snapshot; three separate status reads would cost three
        round trips per tick and make the UI sluggish under load.

        The snapshot carries no mixed fields, and mixed state is otherwise only reported
        as a side effect of running a command, which stops happening the moment a capture
        is armed. So a mixed capture would complete with nobody listening. Pay the second
        round trip only while mixed is in play, including the one poll after it releases
        the hardware so that a stop or a fault is still delivered.
        """
        if self._instrument is None:
            self.error.emit("Device is not connected")
            return
        try:
            status = self._instrument.device_status()
            self.device_status_changed.emit(status)
            owns = status.owner_name == "mixed"
            if owns or self._mixed_active:
                self._mixed_active = owns
                self.mixed_status_changed.emit(self._instrument.mixed_status())
        except (OSError, RuntimeError, ValueError) as exc:
            self.error.emit(str(exc))
            if isinstance(exc, OSError):
                self._close(True)

    @Slot(int, str, float, float, float, float, object)
    def configure(
        self,
        channel: int,
        waveform: str,
        frequency_hz: float,
        amplitude_percent: float,
        offset_percent: float,
        phase_degrees: float,
        samples,
    ) -> None:
        self._run(
            lambda device: self._configure(
                device,
                channel,
                waveform,
                frequency_hz,
                amplitude_percent,
                offset_percent,
                phase_degrees,
                samples,
            )
        )

    def _configure(self, device, channel, waveform, frequency, amplitude, offset, phase, samples):
        if self._capabilities.get("channels", 1) < 2:
            device.configure(waveform, round(frequency))
            return
        if samples is not None:
            device.upload_arbitrary(channel, samples)
        device.configure_channel(channel, waveform, frequency, amplitude, offset, phase)

    @Slot(object)
    def start(self, configurations) -> None:
        def apply(device):
            for configuration in configurations or ():
                self._configure(device, *configuration)
            device.start()

        self._run(apply)

    @Slot()
    def stop(self) -> None:
        self._run(lambda device: device.stop())

    @Slot(object)
    def arm_scope(self, config) -> None:
        def arm(device):
            device.configure_scope(config)
            device.arm_scope()

        self._run(arm)

    @Slot()
    def stop_scope(self) -> None:
        self._run(lambda device: device.stop_scope())

    @Slot(object, object)
    def read_capture(self, status, rearm_config) -> None:
        if self._instrument is None:
            self.error.emit("Device is not connected")
            return
        try:
            capture = self._instrument.read_capture(status)
            if rearm_config is not None:
                self._instrument.configure_scope(rearm_config)
                self._instrument.arm_scope()
            else:
                self._instrument.stop_scope()
            self.capture_ready.emit(capture)
            self.scope_status_changed.emit(self._instrument.scope_status())
        except (OSError, RuntimeError, ValueError) as exc:
            self.error.emit(str(exc))
            if isinstance(exc, OSError):
                self._close(True)

    @Slot(str)
    def arm_mixed(self, triggered_by) -> None:
        def arm(device):
            device.arm_mixed(triggered_by)

        self._run(arm)

    @Slot()
    def stop_mixed(self) -> None:
        self._run(lambda device: device.stop_mixed())

    @Slot()
    def read_mixed_capture(self) -> None:
        """Read both captures and the statuses that place them on the timeline.

        The statuses are read first and passed on with the samples: they carry the
        window origins, and re-reading them later could catch a different capture.
        """
        if self._instrument is None:
            self.error.emit("Device is not connected")
            return
        try:
            scope_status = self._instrument.scope_status()
            logic_status = self._instrument.logic_status()
            analog = self._instrument.read_capture(scope_status)
            digital = self._instrument.read_logic_capture(logic_status)
            self._instrument.stop_mixed()
            self.mixed_capture_ready.emit((analog, digital, scope_status, logic_status))
            self.mixed_status_changed.emit(self._instrument.mixed_status())
        except (OSError, RuntimeError, ValueError) as exc:
            self.error.emit(str(exc))
            if isinstance(exc, OSError):
                self._close(True)

    @Slot(object)
    def arm_logic(self, config) -> None:
        def arm(device):
            device.configure_logic(config)
            device.arm_logic()

        self._run(arm)

    @Slot()
    def stop_logic(self) -> None:
        self._run(lambda device: device.stop_logic())

    @Slot(object, object)
    def read_logic_capture(self, status, rearm_config) -> None:
        if self._instrument is None:
            self.error.emit("Device is not connected")
            return
        try:
            capture = self._instrument.read_logic_capture(status)
            if rearm_config is not None:
                self._instrument.configure_logic(rearm_config)
                self._instrument.arm_logic()
            else:
                self._instrument.stop_logic()
            self.logic_capture_ready.emit(capture)
            self.logic_status_changed.emit(self._instrument.logic_status())
        except (OSError, RuntimeError, ValueError) as exc:
            self.error.emit(str(exc))
            if isinstance(exc, OSError):
                self._close(True)

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
            self.status_changed.emit(self._read_statuses())
            self.scope_status_changed.emit(self._instrument.scope_status())
            self.logic_status_changed.emit(self._instrument.logic_status())
            self.device_status_changed.emit(self._instrument.device_status())
            self.mixed_status_changed.emit(self._instrument.mixed_status())
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
        self._capabilities = {}
        self._mixed_active = False
        if notify:
            self.disconnected.emit()

    def _read_statuses(self):
        if self._capabilities.get("channels", 1) >= 2:
            return [
                self._instrument.channel_status(channel)
                for channel in range(self._capabilities["channels"])
            ]
        return [self._instrument.status()]


class DeviceSession(QObject):
    connected = Signal(str, object, object)
    status_changed = Signal(object)
    scope_status_changed = Signal(object)
    capture_ready = Signal(object)
    logic_status_changed = Signal(object)
    logic_capture_ready = Signal(object)
    device_status_changed = Signal(object)
    mixed_status_changed = Signal(object)
    mixed_capture_ready = Signal(object)
    disconnected = Signal()
    error = Signal(str)
    busy_changed = Signal(bool)

    _open_requested = Signal(str)
    _close_requested = Signal()
    _refresh_requested = Signal()
    _configure_requested = Signal(int, str, float, float, float, float, object)
    _start_requested = Signal(object)
    _stop_requested = Signal()
    _arm_scope_requested = Signal(object)
    _stop_scope_requested = Signal()
    _read_capture_requested = Signal(object, object)
    _arm_logic_requested = Signal(object)
    _stop_logic_requested = Signal()
    _read_logic_capture_requested = Signal(object, object)
    _arm_mixed_requested = Signal(str)
    _stop_mixed_requested = Signal()
    _read_mixed_requested = Signal()

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
        self._arm_scope_requested.connect(self._worker.arm_scope)
        self._stop_scope_requested.connect(self._worker.stop_scope)
        self._read_capture_requested.connect(self._worker.read_capture)
        self._arm_logic_requested.connect(self._worker.arm_logic)
        self._stop_logic_requested.connect(self._worker.stop_logic)
        self._read_logic_capture_requested.connect(self._worker.read_logic_capture)
        self._arm_mixed_requested.connect(self._worker.arm_mixed)
        self._stop_mixed_requested.connect(self._worker.stop_mixed)
        self._read_mixed_requested.connect(self._worker.read_mixed_capture)
        self._worker.connected.connect(self.connected)
        self._worker.status_changed.connect(self.status_changed)
        self._worker.scope_status_changed.connect(self.scope_status_changed)
        self._worker.capture_ready.connect(self.capture_ready)
        self._worker.logic_status_changed.connect(self.logic_status_changed)
        self._worker.logic_capture_ready.connect(self.logic_capture_ready)
        self._worker.device_status_changed.connect(self.device_status_changed)
        self._worker.mixed_status_changed.connect(self.mixed_status_changed)
        self._worker.mixed_capture_ready.connect(self.mixed_capture_ready)
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

    def configure(
        self,
        channel: int,
        waveform: str,
        frequency_hz: float,
        amplitude_percent: float,
        offset_percent: float,
        phase_degrees: float,
        samples=None,
    ) -> None:
        self._configure_requested.emit(
            channel,
            waveform,
            frequency_hz,
            amplitude_percent,
            offset_percent,
            phase_degrees,
            samples,
        )

    def start(self, configurations=None) -> None:
        self._start_requested.emit(configurations)

    def stop(self) -> None:
        self._stop_requested.emit()

    def arm_scope(self, config) -> None:
        self._arm_scope_requested.emit(config)

    def stop_scope(self) -> None:
        self._stop_scope_requested.emit()

    def read_capture(self, status, rearm_config=None) -> None:
        self._read_capture_requested.emit(status, rearm_config)

    def arm_logic(self, config) -> None:
        self._arm_logic_requested.emit(config)

    def stop_logic(self) -> None:
        self._stop_logic_requested.emit()

    def read_logic_capture(self, status, rearm_config=None) -> None:
        self._read_logic_capture_requested.emit(status, rearm_config)

    def arm_mixed(self, triggered_by: str) -> None:
        self._arm_mixed_requested.emit(triggered_by)

    def stop_mixed(self) -> None:
        self._stop_mixed_requested.emit()

    def read_mixed_capture(self) -> None:
        self._read_mixed_requested.emit()

    def shutdown(self) -> None:
        if not self._thread.isRunning():
            return
        QMetaObject.invokeMethod(self._worker, "close", Qt.ConnectionType.BlockingQueuedConnection)
        self._thread.quit()
        self._thread.wait(3000)
