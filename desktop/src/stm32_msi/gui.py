"""Desktop controls for the instrument."""

import sys
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDial,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from .instrument import WAVEFORMS, Status
from .session import DeviceSession


@dataclass(frozen=True)
class Port:
    device: str
    description: str
    instrument: bool = False


def available_ports() -> list[Port]:
    ports = [
        Port(
            item.device,
            item.description or "Serial device",
            item.vid == 0x0483 and item.pid == 0x5740,
        )
        for item in list_ports.comports()
    ]
    return sorted(ports, key=lambda item: (not item.instrument, item.device))


class MainWindow(QMainWindow):
    def __init__(
        self,
        session=None,
        port_provider: Callable[[], list[Port]] = available_ports,
    ):
        super().__init__()
        self._session = session or DeviceSession(parent=self)
        self._port_provider = port_provider
        self._connected = False
        self._busy = False
        self._polling = False
        self._status = None

        self.setWindowTitle("STM32 Mixed-Signal Instrument")
        self.setMinimumSize(720, 430)
        self._build_ui()
        self._connect_signals()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll)
        self.refresh_ports()
        self._update_controls()

    def _build_ui(self) -> None:
        root = QWidget()
        page = QVBoxLayout(root)
        page.setContentsMargins(24, 20, 24, 20)
        page.setSpacing(16)

        title = QLabel("STM32 Mixed-Signal Instrument")
        title.setObjectName("title")
        page.addWidget(title)

        connection = QGroupBox("Connection")
        connection_layout = QHBoxLayout(connection)
        self.port_combo = QComboBox()
        self.port_combo.setObjectName("portCombo")
        self.port_combo.setMinimumWidth(320)
        self.refresh_button = QPushButton("Refresh")
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("connectButton")
        connection_layout.addWidget(self.port_combo, 1)
        connection_layout.addWidget(self.refresh_button)
        connection_layout.addWidget(self.connect_button)
        page.addWidget(connection)

        content = QHBoxLayout()
        content.setSpacing(16)
        content.addWidget(self._build_awg_panel(), 1)
        content.addWidget(self._build_status_panel(), 1)
        page.addLayout(content, 1)

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Disconnected")
        self.setStyleSheet(
            "QLabel#title { font-size: 22px; font-weight: 600; }"
            "QGroupBox { font-weight: 600; margin-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
            "QPushButton { min-height: 28px; padding: 0 12px; }"
            "QComboBox, QSpinBox { min-height: 28px; }"
        )

    def _build_awg_panel(self) -> QGroupBox:
        panel = QGroupBox("Waveform Generator")
        layout = QVBoxLayout(panel)
        form = QFormLayout()
        self.waveform_combo = QComboBox()
        self.waveform_combo.setObjectName("waveformCombo")
        for waveform in WAVEFORMS:
            self.waveform_combo.addItem(waveform.title(), waveform)
        self.frequency_spin = QSpinBox()
        self.frequency_spin.setObjectName("frequencySpin")
        self.frequency_spin.setRange(1, 1000)
        self.frequency_spin.setValue(1000)
        self.frequency_spin.setSuffix(" Hz")
        self.frequency_dial = QDial()
        self.frequency_dial.setObjectName("frequencyDial")
        self.frequency_dial.setRange(1, 1000)
        self.frequency_dial.setValue(1000)
        self.frequency_dial.setNotchesVisible(True)
        self.frequency_dial.setNotchTarget(8)
        self.frequency_dial.setFixedSize(150, 150)
        self.frequency_dial.valueChanged.connect(self.frequency_spin.setValue)
        self.frequency_spin.valueChanged.connect(self.frequency_dial.setValue)
        form.addRow("Waveform", self.waveform_combo)
        form.addRow("Frequency", self.frequency_spin)
        layout.addLayout(form)
        layout.addWidget(self.frequency_dial, 0, Qt.AlignmentFlag.AlignHCenter)

        buttons = QHBoxLayout()
        self.configure_button = QPushButton("Apply")
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        buttons.addWidget(self.configure_button)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)
        layout.addStretch()
        return panel

    def _build_status_panel(self) -> QGroupBox:
        panel = QGroupBox("Device Status")
        form = QFormLayout(panel)
        self.device_label = QLabel("—")
        self.connection_label = QLabel("Disconnected")
        self.state_label = QLabel("—")
        self.waveform_label = QLabel("—")
        self.requested_label = QLabel("—")
        self.actual_label = QLabel("—")
        self.frequency_error_label = QLabel("—")
        self.actual_label.setToolTip("Calculated from the integer TIM6 divider values.")
        self.frequency_error_label.setToolTip(
            "Difference between the requested frequency and the calculated timer output."
        )
        self.underrun_label = QLabel("—")
        self.dma_error_label = QLabel("—")
        form.addRow("Device", self.device_label)
        form.addRow("Connection", self.connection_label)
        form.addRow("AWG state", self.state_label)
        form.addRow("Waveform", self.waveform_label)
        form.addRow("Requested", self.requested_label)
        form.addRow("Actual", self.actual_label)
        form.addRow("Frequency error", self.frequency_error_label)
        form.addRow("Underruns", self.underrun_label)
        form.addRow("DMA errors", self.dma_error_label)
        return panel

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self._toggle_connection)
        self.configure_button.clicked.connect(self._configure)
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self._stop)
        self._session.connected.connect(self._on_connected)
        self._session.status_changed.connect(self._on_status)
        self._session.disconnected.connect(self._on_disconnected)
        self._session.error.connect(self._on_error)
        self._session.busy_changed.connect(self._set_busy)

    def refresh_ports(self) -> None:
        selected = self.port_combo.currentData()
        self.port_combo.clear()
        ports = sorted(self._port_provider(), key=lambda item: (not item.instrument, item.device))
        for port in ports:
            suffix = " — instrument" if port.instrument else f" — {port.description}"
            self.port_combo.addItem(port.device + suffix, port.device)
        if self.port_combo.count() == 0:
            self.port_combo.addItem("No serial ports found", None)
        elif selected is not None:
            index = self.port_combo.findData(selected)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        self._update_controls()

    def _toggle_connection(self) -> None:
        self._set_busy(True)
        if self._connected:
            self._session.disconnect_device()
        else:
            self._session.connect_device(self.port_combo.currentData())

    def _configure(self) -> None:
        self._set_busy(True)
        self._session.configure(self.waveform_combo.currentData(), self.frequency_spin.value())

    def _start(self) -> None:
        self._set_busy(True)
        self._session.start()

    def _stop(self) -> None:
        self._set_busy(True)
        self._session.stop()

    def _poll(self) -> None:
        if self._connected and not self._busy and not self._polling:
            self._polling = True
            self._session.refresh()

    def _on_connected(self, name: str, capabilities: dict, status: Status) -> None:
        self._connected = True
        self.device_label.setText(name)
        self.connection_label.setText("Connected")
        self.connect_button.setText("Disconnect")
        self.frequency_spin.setRange(capabilities["min_hz"], capabilities["max_hz"])
        self.frequency_dial.setRange(capabilities["min_hz"], capabilities["max_hz"])
        self.frequency_spin.setValue(status.requested_hz)
        if status.waveform < self.waveform_combo.count():
            self.waveform_combo.setCurrentIndex(status.waveform)
        self.statusBar().showMessage("Connected")
        self._apply_status(status)
        self._poll_timer.start()

    def _on_status(self, status: Status) -> None:
        self._polling = False
        self.statusBar().showMessage("Connected")
        self._apply_status(status)

    def _apply_status(self, status: Status) -> None:
        states = ("Unconfigured", "Ready", "Running", "Fault")
        waveforms = ("Sine", "Triangle", "Square")
        self._status = status
        self.state_label.setText(states[status.state] if status.state < len(states) else "Unknown")
        self.waveform_label.setText(
            waveforms[status.waveform] if status.waveform < len(waveforms) else "Unknown"
        )
        self.requested_label.setText(f"{status.requested_hz} Hz")
        actual_hz = status.actual_millihz / 1000
        self.actual_label.setText(f"{actual_hz:.3f} Hz")
        if status.requested_hz:
            error_hz = actual_hz - status.requested_hz
            error_percent = error_hz * 100 / status.requested_hz
            self.frequency_error_label.setText(f"{error_hz:+.3f} Hz ({error_percent:+.3f}%)")
        else:
            self.frequency_error_label.setText("—")
        self.underrun_label.setText(str(status.underruns))
        self.dma_error_label.setText(str(status.dma_errors))
        self._update_controls()

    def _on_disconnected(self) -> None:
        self._connected = False
        self._polling = False
        self._status = None
        self._poll_timer.stop()
        self.connection_label.setText("Disconnected")
        self.connect_button.setText("Connect")
        if not self.statusBar().currentMessage().startswith("Error:"):
            self.statusBar().showMessage("Disconnected")
        self._update_controls()

    def _on_error(self, message: str) -> None:
        self._polling = False
        self.statusBar().showMessage(f"Error: {message}")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_controls()

    def _update_controls(self) -> None:
        state = self._status.state if self._status else None
        available = self.port_combo.currentData() is not None
        self.port_combo.setEnabled(not self._connected and not self._busy)
        self.refresh_button.setEnabled(not self._connected and not self._busy)
        self.connect_button.setEnabled(not self._busy and (self._connected or available))
        self.waveform_combo.setEnabled(self._connected and not self._busy and state != 2)
        self.frequency_spin.setEnabled(self._connected and not self._busy and state != 2)
        self.frequency_dial.setEnabled(self._connected and not self._busy and state != 2)
        self.configure_button.setEnabled(self._connected and not self._busy and state != 2)
        self.start_button.setEnabled(self._connected and not self._busy and state == 1)
        self.stop_button.setEnabled(self._connected and not self._busy and state in (2, 3))

    def closeEvent(self, event) -> None:
        self._poll_timer.stop()
        self._session.shutdown()
        super().closeEvent(event)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("STM32 Mixed-Signal Instrument")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
