"""Desktop controls for the instrument."""

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDial,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from .instrument import MAX_ARBITRARY_SAMPLES, WAVEFORMS, Capture, ScopeConfig, ScopeStatus, Status
from .scope import adc_volts, measure
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


def parse_sample_table(text: str) -> list[int]:
    tokens = [token for token in re.split(r"[\s,;]+", text.strip()) if token]
    try:
        samples = [
            int(token, 16) if token.lower().startswith("0x") else int(token) for token in tokens
        ]
    except ValueError as exc:
        raise ValueError("Table entries must be integer DAC codes") from exc
    if not 2 <= len(samples) <= MAX_ARBITRARY_SAMPLES:
        raise ValueError("Arbitrary tables require 2..256 samples")
    if any(not 0 <= sample <= 4095 for sample in samples):
        raise ValueError("DAC codes must be between 0 and 4095")
    return samples


class FineDial(QDial):
    def __init__(self, fine_step: int, fine_drag_step: int | None = None):
        super().__init__()
        self._fine_step = fine_step
        self._fine_drag_step = fine_drag_step or fine_step
        self._fine_anchor = None

    def _adjust(self, amount: int) -> None:
        value = self.value() + amount
        if self.wrapping():
            width = self.maximum() - self.minimum() + 1
            value = (value - self.minimum()) % width + self.minimum()
        self.setValue(value)

    def mousePressEvent(self, event) -> None:
        self._fine_anchor = None
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._fine_anchor = (event.position(), self.value())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self._fine_anchor is None:
                self._fine_anchor = (event.position(), self.value())
            position, value = self._fine_anchor
            steps = round((position.y() - event.position().y()) / 2)
            self.setValue(value + steps * self._fine_drag_step)
            event.accept()
            return
        self._fine_anchor = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._fine_anchor is not None:
            self._fine_anchor = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            steps = round(event.angleDelta().y() / 120)
            if steps:
                self._adjust(steps * self._fine_step)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Up):
                self._adjust(self._fine_step)
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Down):
                self._adjust(-self._fine_step)
                event.accept()
                return
        super().keyPressEvent(event)


class OutputPanel(QGroupBox):
    load_requested = Signal(int)

    def __init__(self, channel: int, pin: str):
        super().__init__(f"Output {channel + 1} — {pin}")
        self.channel = channel
        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.waveform = QComboBox()
        for name in WAVEFORMS:
            self.waveform.addItem(name.title(), name)

        self.frequency = QDoubleSpinBox()
        self.frequency.setRange(1, 20_000)
        self.frequency.setDecimals(3)
        self.frequency.setValue(1000)
        self.frequency.setSuffix(" Hz")
        self.frequency.setAccelerated(True)

        self.amplitude = QDoubleSpinBox()
        self.amplitude.setRange(0, 100)
        self.amplitude.setDecimals(1)
        self.amplitude.setValue(75)
        self.amplitude.setSuffix(" % FS")

        self.offset = QDoubleSpinBox()
        self.offset.setRange(0, 100)
        self.offset.setDecimals(1)
        self.offset.setValue(50)
        self.offset.setSuffix(" % FS")

        self.phase = QDoubleSpinBox()
        self.phase.setRange(0, 359.9)
        self.phase.setDecimals(1)
        self.phase.setSuffix("°")

        form.addRow("Waveform", self.waveform)
        form.addRow("Frequency", self.frequency)
        form.addRow("Amplitude", self.amplitude)
        form.addRow("Offset", self.offset)
        form.addRow("Phase", self.phase)
        layout.addLayout(form)

        self.frequency_dial = self._dial(1000, 20_000_000, 1_000_000, 1000, 1, 100)
        self.amplitude_dial = self._dial(0, 1000, 750, 10, 1)
        self.offset_dial = self._dial(0, 1000, 500, 10, 1)
        self.phase_dial = self._dial(0, 3599, 0, 10, 1, wrapping=True)

        knobs = QHBoxLayout()
        for title, dial in (
            ("Frequency", self.frequency_dial),
            ("Amplitude", self.amplitude_dial),
            ("Offset", self.offset_dial),
            ("Phase", self.phase_dial),
        ):
            column = QVBoxLayout()
            column.setSpacing(2)
            column.addWidget(dial, 0, Qt.AlignmentFlag.AlignHCenter)
            label = QLabel(title)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(label)
            knobs.addLayout(column)
        layout.addLayout(knobs)

        table_row = QHBoxLayout()
        self.load_table = QPushButton("Load table…")
        self.table = QLabel("No table loaded")
        table_row.addWidget(self.load_table)
        table_row.addWidget(self.table, 1)
        layout.addLayout(table_row)

        status = QGridLayout()
        status.addWidget(QLabel("State"), 0, 0)
        status.addWidget(QLabel("Actual"), 0, 1)
        status.addWidget(QLabel("Error"), 0, 2)
        self.state = QLabel("—")
        self.actual = QLabel("—")
        self.error = QLabel("—")
        self.actual.setToolTip("Calculated from the DDS phase increment")
        status.addWidget(self.state, 1, 0)
        status.addWidget(self.actual, 1, 1)
        status.addWidget(self.error, 1, 2)
        layout.addLayout(status)

    @staticmethod
    def _dial(
        minimum: int,
        maximum: int,
        value: int,
        step: int,
        fine_step: int,
        fine_drag_step: int | None = None,
        wrapping: bool = False,
    ) -> FineDial:
        dial = FineDial(fine_step, fine_drag_step)
        dial.setRange(minimum, maximum)
        dial.setValue(value)
        dial.setSingleStep(step)
        dial.setNotchesVisible(True)
        dial.setNotchTarget(7)
        dial.setWrapping(wrapping)
        dial.setFixedSize(76, 76)
        dial.setToolTip("Hold Shift for fine control")
        return dial

    def _connect_signals(self) -> None:
        self.waveform.currentIndexChanged.connect(self._waveform_changed)
        self._link(self.frequency_dial, self.frequency, 1000)
        self._link(self.amplitude_dial, self.amplitude, 10)
        self._link(self.offset_dial, self.offset, 10)
        self._link(self.phase_dial, self.phase, 10)
        self.load_table.clicked.connect(lambda: self.load_requested.emit(self.channel))
        self._waveform_changed()

    @staticmethod
    def _link(dial: QDial, spin: QDoubleSpinBox, scale: int) -> None:
        dial.valueChanged.connect(lambda value: spin.setValue(value / scale))

        def update_dial(value: float) -> None:
            dial.blockSignals(True)
            dial.setValue(round(value * scale))
            dial.blockSignals(False)

        spin.valueChanged.connect(update_dial)

    def _waveform_changed(self) -> None:
        visible = self.waveform.currentData() == "arbitrary"
        self.load_table.setVisible(visible)
        self.table.setVisible(visible)

    def set_frequency_range(self, minimum: float, maximum: float) -> None:
        self.frequency.setRange(minimum, maximum)
        self.frequency_dial.setRange(round(minimum * 1000), round(maximum * 1000))

    def set_waveforms(self, mask: int) -> None:
        current = self.waveform.currentData()
        self.waveform.blockSignals(True)
        self.waveform.clear()
        for name, value in WAVEFORMS.items():
            if mask & (1 << value):
                self.waveform.addItem(name.title(), name)
        index = self.waveform.findData(current)
        self.waveform.setCurrentIndex(index if index >= 0 else 0)
        self.waveform.blockSignals(False)
        self._waveform_changed()

    def load_controls(self, status: Status) -> None:
        name = next((name for name, value in WAVEFORMS.items() if value == status.waveform), None)
        index = self.waveform.findData(name)
        if index >= 0:
            self.waveform.setCurrentIndex(index)
        self.frequency.setValue(status.requested_hz)
        self.amplitude.setValue(status.amplitude_permille / 10)
        self.offset.setValue(status.offset_permille / 10)
        self.phase.setValue(status.phase_decidegrees / 10)

    def apply_status(self, status: Status) -> None:
        states = ("Unconfigured", "Ready", "Running", "Fault")
        self.state.setText(states[status.state] if status.state < len(states) else "Unknown")
        actual_hz = status.actual_millihz / 1000
        self.actual.setText(f"{actual_hz:.3f} Hz")
        if status.frequency_millihz:
            error = actual_hz - status.requested_hz
            self.error.setText(f"{error:+.3f} Hz")
        else:
            self.error.setText("—")

    def set_table_count(self, count: int) -> None:
        self.table.setText(f"{count} samples" if count else "No table loaded")

    def set_editable(self, editable: bool, extended: bool) -> None:
        for widget in (
            self.waveform,
            self.frequency,
            self.frequency_dial,
            self.amplitude,
            self.amplitude_dial,
            self.offset,
            self.offset_dial,
            self.phase,
            self.phase_dial,
        ):
            widget.setEnabled(editable)
        for widget in (self.amplitude, self.amplitude_dial, self.offset, self.offset_dial):
            widget.setEnabled(editable and extended)
        self.phase.setEnabled(editable and extended)
        self.phase_dial.setEnabled(editable and extended)
        self.load_table.setEnabled(
            editable and extended and self.waveform.currentData() == "arbitrary"
        )


class ScopePanel(QWidget):
    arm_requested = Signal(object)
    run_requested = Signal(object)
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self._live_display = False
        self._live_time = np.empty(0)
        self._live_first = np.empty(0)
        self._live_second = np.empty(0)
        self._live_next_ms = 0.0
        self._live_block_ms = 0.0
        self._last_reference = 3.0
        self._build_ui()

    def _build_ui(self) -> None:
        page = QVBoxLayout(self)
        controls = QGroupBox("Acquisition")
        row = QHBoxLayout(controls)

        self.sample_rate = QComboBox()
        for label, value in (("100 kS/s", 100_000), ("500 kS/s", 500_000), ("1 MS/s", 1_000_000)):
            self.sample_rate.addItem(label, value)
        self.sample_count = QComboBox()
        for value in (64, 128, 256, 512, 1024, 2048):
            self.sample_count.addItem(str(value), value)
        self.sample_count.setCurrentIndex(self.sample_count.findData(512))
        self.trigger_channel = QComboBox()
        self.trigger_channel.addItem("CH1 (PC4)", 0)
        self.trigger_channel.addItem("CH2 (PC5)", 1)
        self.trigger_edge = QComboBox()
        self.trigger_edge.addItem("Free run", 0)
        self.trigger_edge.addItem("Rising", 1)
        self.trigger_edge.addItem("Falling", 2)
        self.trigger_level = QDoubleSpinBox()
        self.trigger_level.setRange(0, 3.0)
        self.trigger_level.setValue(1.5)
        self.trigger_level.setDecimals(3)
        self.trigger_level.setSuffix(" V")
        self.pretrigger = QDoubleSpinBox()
        self.pretrigger.setRange(0, 90)
        self.pretrigger.setValue(50)
        self.pretrigger.setSuffix(" %")
        self.reference = QDoubleSpinBox()
        self.reference.setRange(1.8, 3.6)
        self.reference.setValue(3.0)
        self.reference.setDecimals(3)
        self.reference.setSuffix(" V")

        for label, widget in (
            ("Rate", self.sample_rate),
            ("Samples", self.sample_count),
            ("Trigger", self.trigger_channel),
            ("Edge", self.trigger_edge),
            ("Level", self.trigger_level),
            ("Pretrigger", self.pretrigger),
            ("VDDA", self.reference),
        ):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            column.addWidget(widget)
            row.addLayout(column)
        self.arm = QPushButton("Single")
        self.run = QPushButton("Run")
        self.run.setToolTip("Continuously refresh using repeated finite captures")
        self.stop = QPushButton("Stop")
        row.addWidget(self.arm)
        row.addWidget(self.run)
        row.addWidget(self.stop)
        page.addWidget(controls)

        display = QGroupBox("Display")
        display_row = QHBoxLayout(display)
        self.time_scale = QComboBox()
        self.time_scale.addItem("Auto", None)
        for label, value in (
            ("10 us/div", 0.01),
            ("20 us/div", 0.02),
            ("50 us/div", 0.05),
            ("100 us/div", 0.1),
            ("200 us/div", 0.2),
            ("500 us/div", 0.5),
            ("1 ms/div", 1.0),
            ("2 ms/div", 2.0),
            ("5 ms/div", 5.0),
            ("10 ms/div", 10.0),
            ("20 ms/div", 20.0),
            ("50 ms/div", 50.0),
            ("100 ms/div", 100.0),
            ("200 ms/div", 200.0),
            ("500 ms/div", 500.0),
            ("1 s/div", 1000.0),
        ):
            self.time_scale.addItem(label, value)
        self.time_scale.addItem("Custom", "custom")
        self.voltage_scale = QComboBox()
        self.voltage_scale.addItem("Auto", None)
        for value in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0):
            label = f"{value * 1000:g} mV/div" if value < 1 else f"{value:g} V/div"
            self.voltage_scale.addItem(label, value)
        self.voltage_scale.addItem("Custom", "custom")
        self.vertical_center = QDoubleSpinBox()
        self.vertical_center.setRange(-10.0, 10.0)
        self.vertical_center.setValue(1.5)
        self.vertical_center.setDecimals(3)
        self.vertical_center.setSingleStep(0.1)
        self.vertical_center.setSuffix(" V")
        for label, widget in (
            ("Time", self.time_scale),
            ("Voltage", self.voltage_scale),
            ("Vertical center", self.vertical_center),
        ):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            column.addWidget(widget)
            display_row.addLayout(column)
        self.follow = QPushButton("Follow latest")
        self.follow.setCheckable(True)
        self.follow.setChecked(True)
        self.follow.setToolTip("Keep the newest live samples at the right edge")
        self.autoscale = QPushButton("Autoscale")
        display_row.addWidget(self.follow)
        display_row.addWidget(self.autoscale)
        display_row.addStretch(1)
        page.addWidget(display)

        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "Time", "ms")
        self.plot.setLabel("left", "Input", "V")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setYRange(0, 3.0)
        self.plot.setMouseEnabled(x=True, y=True)
        self.plot.setToolTip("Drag to pan. Use the mouse wheel to zoom.")
        self.plot.addLegend()
        self.channel_1_curve = self.plot.plot(pen=pg.mkPen("#f5c542", width=2), name="CH1")
        self.channel_2_curve = self.plot.plot(pen=pg.mkPen("#4aa8ff", width=2), name="CH2")
        self.trigger_line = pg.InfiniteLine(
            0, angle=90, pen=pg.mkPen("#e06666", style=Qt.PenStyle.DashLine)
        )
        self.plot.addItem(self.trigger_line)
        page.addWidget(self.plot, 1)

        summary = QGroupBox("Capture")
        grid = QGridLayout(summary)
        headings = ("", "Min", "Max", "Mean", "RMS", "Vpp", "Frequency", "Period")
        for column, text in enumerate(headings):
            grid.addWidget(QLabel(text), 0, column)
        self.measurements = []
        for row_index, channel in enumerate(("CH1", "CH2"), 1):
            grid.addWidget(QLabel(channel), row_index, 0)
            labels = [QLabel("—") for _ in headings[1:]]
            for column, label in enumerate(labels, 1):
                grid.addWidget(label, row_index, column)
            self.measurements.append(labels)
        self.scope_state = QLabel("Idle")
        self.scope_counts = QLabel("Trigger misses 0  |  Overruns 0  |  DMA errors 0")
        grid.addWidget(self.scope_state, 3, 0, 1, 2)
        grid.addWidget(self.scope_counts, 3, 2, 1, 6)
        page.addWidget(summary)

        self.arm.clicked.connect(self._arm)
        self.run.clicked.connect(self._run)
        self.stop.clicked.connect(self.stop_requested)
        self.reference.valueChanged.connect(lambda value: self.trigger_level.setMaximum(value))
        self.time_scale.currentIndexChanged.connect(self._apply_horizontal_scale)
        self.voltage_scale.currentIndexChanged.connect(self._apply_vertical_scale)
        self.vertical_center.valueChanged.connect(self._apply_vertical_scale)
        self.follow.toggled.connect(self._follow_changed)
        self.autoscale.clicked.connect(self._autoscale)
        self.plot.getViewBox().sigRangeChangedManually.connect(self._view_changed_manually)
        self.set_enabled(False, False)

    def _arm(self) -> None:
        self._live_display = False
        self.plot.setLabel("bottom", "Time", "ms")
        self.trigger_line.setVisible(True)
        self.arm_requested.emit(self.config())

    def _run(self) -> None:
        self._live_display = True
        self._live_time = np.empty(0)
        self._live_first = np.empty(0)
        self._live_second = np.empty(0)
        self._live_next_ms = 0.0
        self._live_block_ms = 0.0
        self.plot.setLabel("bottom", "Captured time", "ms")
        self.trigger_line.setVisible(False)
        self.run_requested.emit(self.config())

    def config(self) -> ScopeConfig:
        reference = self.reference.value()
        level = round(self.trigger_level.value() * 4095 / reference)
        return ScopeConfig(
            self.sample_rate.currentData(),
            self.sample_count.currentData(),
            self.trigger_channel.currentData(),
            self.trigger_edge.currentData(),
            level,
            round(self.pretrigger.value() * 10),
        )

    def apply_status(self, status: ScopeStatus, live: bool = False) -> None:
        states = ("Idle", "Armed", "Complete", "Fault")
        if live and status.state != 3:
            state = "Live"
        else:
            state = states[status.state] if status.state < len(states) else "Unknown"
        self.scope_state.setText(state)
        self.scope_counts.setText(
            f"Trigger misses {status.trigger_misses}  |  Overruns {status.overruns}  |  "
            f"DMA errors {status.dma_errors}"
        )

    def apply_capture(self, capture: Capture) -> None:
        reference = self.reference.value()
        self._last_reference = reference
        first = adc_volts(capture.channel_1, reference)
        second = adc_volts(capture.channel_2, reference)
        if self._live_display:
            self._append_live(capture, first, second)
        else:
            at = np.arange(capture.status.sample_count) - capture.status.trigger_index
            time_ms = at * 1000 / capture.status.sample_rate
            self.channel_1_curve.setData(time_ms, first)
            self.channel_2_curve.setData(time_ms, second)
            self._apply_horizontal_scale()
        self._apply_vertical_scale()
        for labels, values in zip(self.measurements, (first, second), strict=True):
            result = measure(values, capture.status.sample_rate)
            frequency = f"{result.frequency:.3f} Hz" if result.frequency else "—"
            period = f"{result.period * 1000:.3f} ms" if result.period else "—"
            text = (
                f"{result.minimum:.3f} V",
                f"{result.maximum:.3f} V",
                f"{result.mean:.3f} V",
                f"{result.rms:.3f} V",
                f"{result.peak_to_peak:.3f} V",
                frequency,
                period,
            )
            for label, value in zip(labels, text, strict=True):
                label.setText(value)

    def _append_live(self, capture: Capture, first: np.ndarray, second: np.ndarray) -> None:
        step_ms = 1000 / capture.status.sample_rate
        time_ms = self._live_next_ms + np.arange(first.size) * step_ms
        self._live_block_ms = first.size * step_ms
        self._live_next_ms += self._live_block_ms
        self._live_time = np.concatenate((self._live_time, time_ms))[-100_000:]
        self._live_first = np.concatenate((self._live_first, first))[-100_000:]
        self._live_second = np.concatenate((self._live_second, second))[-100_000:]
        self.channel_1_curve.setData(self._live_time, self._live_first)
        self.channel_2_curve.setData(self._live_time, self._live_second)
        if self.follow.isChecked():
            self._follow_live()

    def _follow_live(self) -> None:
        if not self._live_time.size:
            return
        scale = self.time_scale.currentData()
        if isinstance(scale, float):
            window_ms = 10 * scale
        elif scale == "custom":
            current = self.plot.viewRange()[0]
            window_ms = current[1] - current[0]
        else:
            window_ms = max(10 * self._live_block_ms, 10.0)
        left = self._live_next_ms - window_ms
        self.plot.setXRange(left, self._live_next_ms, padding=0)

    def _apply_horizontal_scale(self, *_args) -> None:
        scale = self.time_scale.currentData()
        if scale == "custom" or not self.channel_1_curve.xData.size:
            return
        if self._live_display and self.follow.isChecked():
            self._follow_live()
            return
        data = self.channel_1_curve.xData
        if scale is None:
            self.plot.setXRange(float(data[0]), float(data[-1]), padding=0.02)
            return
        current = self.plot.viewRange()[0]
        center = sum(current) / 2 if current[1] > current[0] else 0.0
        span = 10 * scale
        self.plot.setXRange(center - span / 2, center + span / 2, padding=0)

    def _apply_vertical_scale(self, *_args) -> None:
        scale = self.voltage_scale.currentData()
        if scale == "custom":
            return
        if scale is None:
            self.plot.setYRange(0, self._last_reference, padding=0)
            return
        center = self.vertical_center.value()
        span = 8 * scale
        self.plot.setYRange(center - span / 2, center + span / 2, padding=0)

    def _follow_changed(self, enabled: bool) -> None:
        if enabled and self._live_display:
            self._follow_live()

    def _autoscale(self) -> None:
        self.time_scale.setCurrentIndex(0)
        self.voltage_scale.setCurrentIndex(0)
        self.vertical_center.setValue(self._last_reference / 2)
        self.follow.setChecked(True)
        self._apply_horizontal_scale()
        self._apply_vertical_scale()

    def _view_changed_manually(self, axes) -> None:
        if axes[0]:
            self._mark_custom_scale(self.time_scale)
            if self._live_display:
                self.follow.setChecked(False)
        if axes[1]:
            self._mark_custom_scale(self.voltage_scale)

    @staticmethod
    def _mark_custom_scale(combo: QComboBox) -> None:
        combo.blockSignals(True)
        combo.setCurrentIndex(combo.count() - 1)
        combo.blockSignals(False)

    def set_enabled(
        self,
        connected: bool,
        busy: bool,
        state: int = 0,
        live: bool = False,
        transferring: bool = False,
        stopping: bool = False,
    ) -> None:
        editable = connected and not busy and not transferring and state != 1 and not live
        for widget in (
            self.sample_rate,
            self.sample_count,
            self.trigger_channel,
            self.trigger_edge,
            self.trigger_level,
            self.pretrigger,
            self.reference,
        ):
            widget.setEnabled(editable)
        self.arm.setEnabled(editable)
        self.run.setEnabled(editable)
        self.stop.setEnabled(connected and not stopping and (live or state in (1, 2, 3)))


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
        self._statuses: dict[int, Status] = {}
        self._capabilities = {}
        self._tables: dict[int, list[int]] = {}
        self._scope_status = None
        self._capture_read_id = None
        self._scope_live = False
        self._scope_config = None
        self._scope_transfer = False
        self._scope_stopping = False

        self.setWindowTitle("STM32 Mixed-Signal Instrument")
        self.setMinimumSize(1050, 700)
        self._build_ui()
        self._connect_signals()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll)
        self.refresh_ports()
        self._update_controls()

    def _build_ui(self) -> None:
        root = QWidget()
        page = QVBoxLayout(root)
        page.setContentsMargins(20, 16, 20, 16)
        page.setSpacing(12)

        title = QLabel("STM32 Mixed-Signal Instrument")
        title.setObjectName("title")
        page.addWidget(title)

        connection = QGroupBox("Connection")
        connection_layout = QHBoxLayout(connection)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(320)
        self.refresh_button = QPushButton("Refresh")
        self.connect_button = QPushButton("Connect")
        connection_layout.addWidget(self.port_combo, 1)
        connection_layout.addWidget(self.refresh_button)
        connection_layout.addWidget(self.connect_button)
        page.addWidget(connection)

        tabs = QTabWidget()
        awg_page = QWidget()
        awg_layout = QVBoxLayout(awg_page)
        self.outputs = [OutputPanel(0, "PA4"), OutputPanel(1, "PA5")]
        output_row = QHBoxLayout()
        output_row.setSpacing(12)
        for panel in self.outputs:
            output_row.addWidget(panel, 1)
        awg_layout.addLayout(output_row, 1)

        hint = QLabel("Hold Shift while dragging a knob for fine control")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        awg_layout.addWidget(hint)

        actions = QHBoxLayout()
        actions.addStretch()
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        actions.addStretch()
        awg_layout.addLayout(actions)
        awg_layout.addWidget(self._build_status_panel())
        tabs.addTab(awg_page, "Waveform Generator")
        self.scope = ScopePanel()
        tabs.addTab(self.scope, "Oscilloscope")
        page.addWidget(tabs, 1)

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Disconnected")
        self.setStyleSheet(
            "QLabel#title { font-size: 22px; font-weight: 600; }"
            "QLabel#hint { color: #888; }"
            "QGroupBox { font-weight: 600; margin-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
            "QPushButton { min-height: 28px; padding: 0 12px; }"
            "QComboBox, QDoubleSpinBox { min-height: 28px; }"
        )

    def _build_status_panel(self) -> QGroupBox:
        panel = QGroupBox("Device Status")
        layout = QGridLayout(panel)
        headings = ("Device", "Connection", "AWG state", "Underruns", "DMA errors", "Refill misses")
        labels = []
        for column, heading in enumerate(headings):
            title = QLabel(heading)
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title, 0, column)
            value = QLabel("—")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(value, 1, column)
            labels.append(value)
        (
            self.device_label,
            self.connection_label,
            self.state_label,
            self.underrun_label,
            self.dma_error_label,
            self.refill_miss_label,
        ) = labels
        self.connection_label.setText("Disconnected")
        return panel

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self._toggle_connection)
        for panel in self.outputs:
            panel.load_requested.connect(self._load_table)
            panel.waveform.currentIndexChanged.connect(self._update_controls)
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self._stop)
        self.scope.arm_requested.connect(self._arm_scope)
        self.scope.run_requested.connect(self._run_scope)
        self.scope.stop_requested.connect(self._stop_scope)
        self._session.connected.connect(self._on_connected)
        self._session.status_changed.connect(self._on_statuses)
        self._session.scope_status_changed.connect(self._on_scope_status)
        self._session.capture_ready.connect(self._on_capture)
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

    def _load_table(self, channel: int) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load arbitrary waveform", "", "Sample tables (*.csv *.txt);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as file:
                self._tables[channel] = parse_sample_table(file.read())
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"Error: {exc}")
            return
        self.outputs[channel].set_table_count(len(self._tables[channel]))

    def _channel_configuration(self, channel: int):
        panel = self.outputs[channel]
        waveform = panel.waveform.currentData()
        samples = self._tables.get(channel) if waveform == "arbitrary" else None
        status = self._statuses.get(channel)
        if (
            waveform == "arbitrary"
            and samples is None
            and (status is None or status.arbitrary_length == 0)
        ):
            self.statusBar().showMessage("Error: load an arbitrary table first")
            return None
        return (
            channel,
            waveform,
            panel.frequency.value(),
            panel.amplitude.value(),
            panel.offset.value(),
            panel.phase.value(),
            samples,
        )

    def _start(self) -> None:
        count = 2 if self._capabilities.get("channels", 1) >= 2 else 1
        configurations = [self._channel_configuration(channel) for channel in range(count)]
        if any(configuration is None for configuration in configurations):
            return
        self._set_busy(True)
        self._session.start(configurations)

    def _stop(self) -> None:
        self._set_busy(True)
        self._session.stop()

    def _arm_scope(self, config: ScopeConfig) -> None:
        self._set_scope_live(False)
        self._scope_config = config
        self._capture_read_id = None
        self._set_busy(True)
        self._session.arm_scope(config)

    def _run_scope(self, config: ScopeConfig) -> None:
        self._set_scope_live(True)
        self._scope_config = config
        self._capture_read_id = None
        self._set_busy(True)
        self._session.arm_scope(config)

    def _stop_scope(self) -> None:
        if self._scope_stopping:
            return
        self._scope_stopping = True
        self._set_scope_live(False)
        self._set_busy(True)
        self._session.stop_scope()

    def _poll(self) -> None:
        if self._connected and not self._busy and not self._polling:
            self._polling = True
            self._session.refresh()

    @staticmethod
    def _status_list(statuses) -> list[Status]:
        return statuses if isinstance(statuses, list) else [statuses]

    def _on_connected(self, name: str, capabilities: dict, statuses) -> None:
        self._connected = True
        self._capabilities = capabilities
        self.device_label.setText(name)
        self.connection_label.setText("Connected")
        self.connect_button.setText("Disconnect")
        extended = capabilities.get("channels", 1) >= 2
        for panel in self.outputs:
            panel.set_frequency_range(capabilities["min_hz"], capabilities["max_hz"])
            panel.set_waveforms(capabilities.get("waveforms", 7))
        self.outputs[1].setVisible(extended)
        initial = self._status_list(statuses)
        for status in initial:
            self.outputs[status.channel].load_controls(status)
        self._apply_statuses(initial)
        self.statusBar().showMessage("Connected")
        self._poll_timer.start()

    def _on_statuses(self, statuses) -> None:
        self._polling = False
        self._apply_statuses(self._status_list(statuses))

    def _on_scope_status(self, status: ScopeStatus) -> None:
        self._scope_status = status
        if status.state == 0:
            self._scope_stopping = False
        if status.state == 3:
            self._set_scope_live(False)
        self.scope.apply_status(status, self._scope_live)
        if (
            status.state == 2
            and status.capture_id != self._capture_read_id
            and not self._busy
            and not self._scope_transfer
        ):
            self._capture_read_id = status.capture_id
            self._scope_transfer = True
            rearm = self._scope_config if self._scope_live else None
            self._session.read_capture(status, rearm)
        self._update_controls()

    def _on_capture(self, capture: Capture) -> None:
        self._scope_transfer = False
        self.scope.apply_capture(capture)
        prefix = "Live" if self._scope_live else "Capture"
        self.statusBar().showMessage(f"{prefix} {capture.status.capture_id} received")

    def _apply_statuses(self, statuses: list[Status]) -> None:
        for status in statuses:
            self._statuses[status.channel] = status
            self.outputs[status.channel].apply_status(status)
        if self._statuses:
            status = self._statuses[min(self._statuses)]
            states = ("Unconfigured", "Ready", "Running", "Fault")
            self.state_label.setText(
                states[status.state] if status.state < len(states) else "Unknown"
            )
            self.underrun_label.setText(str(status.underruns))
            self.dma_error_label.setText(str(status.dma_errors))
            self.refill_miss_label.setText(str(status.refill_misses))
        self._update_controls()

    def _on_disconnected(self) -> None:
        self._connected = False
        self._polling = False
        self._statuses.clear()
        self._capabilities = {}
        self._scope_status = None
        self._capture_read_id = None
        self._set_scope_live(False)
        self._scope_config = None
        self._scope_transfer = False
        self._scope_stopping = False
        self._poll_timer.stop()
        self.connection_label.setText("Disconnected")
        self.connect_button.setText("Connect")
        if not self.statusBar().currentMessage().startswith("Error:"):
            self.statusBar().showMessage("Disconnected")
        self._update_controls()

    def _on_error(self, message: str) -> None:
        self._polling = False
        self._set_scope_live(False)
        self._scope_transfer = False
        self._scope_stopping = False
        self.statusBar().showMessage(f"Error: {message}")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_controls()

    def _set_scope_live(self, live: bool) -> None:
        self._scope_live = live
        self._poll_timer.setInterval(100 if live else 500)

    def _update_controls(self) -> None:
        if not hasattr(self, "port_combo"):
            return
        status = self._statuses.get(0)
        state = status.state if status else None
        available = self.port_combo.currentData() is not None
        editable = self._connected and not self._busy and state != 2
        extended = self._capabilities.get("channels", 1) >= 2
        self.port_combo.setEnabled(not self._connected and not self._busy)
        self.refresh_button.setEnabled(not self._connected and not self._busy)
        self.connect_button.setEnabled(not self._busy and (self._connected or available))
        self.outputs[0].set_editable(editable, extended)
        self.outputs[1].set_editable(editable and extended, extended)
        self.start_button.setEnabled(self._connected and not self._busy and state == 1)
        self.stop_button.setEnabled(self._connected and not self._busy and state in (2, 3))
        scope_state = self._scope_status.state if self._scope_status else 0
        self.scope.set_enabled(
            self._connected,
            self._busy,
            scope_state,
            self._scope_live,
            self._scope_transfer,
            self._scope_stopping,
        )

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
