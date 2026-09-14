"""Desktop controls for the instrument."""

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDial,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from .instrument import (
    LOGIC_CHANNELS,
    LOGIC_RATES,
    MAX_ARBITRARY_SAMPLES,
    MINIMUM_FIRMWARE,
    WAVEFORMS,
    Capture,
    DeviceStatus,
    LogicCapture,
    LogicConfig,
    LogicStatus,
    MixedStatus,
    ScopeConfig,
    ScopeStatus,
    Status,
)
from .logic import channel_bits, decode_i2c, decode_spi, decode_uart
from .logic import measure as logic_measure
from .mixed import Stream, align
from .protocol import VERSION
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


def format_per_division(value: float, unit: str) -> str:
    """Name a division at a readable magnitude. ``unit`` is "ms" for the time axis,
    whose data is already in milliseconds, or "V" for the vertical axis."""
    if unit == "ms":
        if abs(value) < 0.001:
            return f"{value * 1e6:.3g} ns/div"
        if abs(value) < 1.0:
            return f"{value * 1000:.3g} us/div"
        if abs(value) < 1000.0:
            return f"{value:.3g} ms/div"
        return f"{value / 1000:.3g} s/div"
    if abs(value) < 1.0:
        return f"{value * 1000:.3g} mV/div"
    return f"{value:.3g} V/div"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 1e-6:
        return f"{seconds * 1e9:.0f} ns"
    if seconds < 1e-3:
        return f"{seconds * 1e6:.3f} us"
    return f"{seconds * 1e3:.3f} ms"


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

        # Two by two rather than a row of four: the panel now lives in a tall, narrow
        # column beside the display, and a single row forced that column wide enough to
        # crowd out the thing it is meant to sit next to.
        knobs = QGridLayout()
        for index, (title, dial) in enumerate(
            (
                ("Frequency", self.frequency_dial),
                ("Amplitude", self.amplitude_dial),
                ("Offset", self.offset_dial),
                ("Phase", self.phase_dial),
            )
        ):
            column = QVBoxLayout()
            column.setSpacing(2)
            column.addWidget(dial, 0, Qt.AlignmentFlag.AlignHCenter)
            label = QLabel(title)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(label)
            knobs.addLayout(column, index // 2, index % 2)
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

        # Spare height on a tall window belongs at the bottom. Without this the rows
        # above share it out and the panel reads as scattered rather than spaced.
        layout.addStretch(1)

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
        dial.setFixedSize(58, 58)
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
        self._last_capture = None
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
        self.show_channel = []
        for index, name in enumerate(("CH1", "CH2")):
            box = QCheckBox(name)
            box.setChecked(True)
            box.setToolTip(f"Hide {name} and drop it from measurements and autoscale")
            self.show_channel.append(box)
        channel_column = QVBoxLayout()
        channel_column.addWidget(QLabel("Channels"))
        channel_row = QHBoxLayout()
        for box in self.show_channel:
            channel_row.addWidget(box)
        channel_column.addLayout(channel_row)
        display_row.addLayout(channel_column)

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
        # The unit is already in the label text, so pyqtgraph's own prefixing has
        # nothing to rename and shows a bare multiplier such as (x0.001) instead.
        for edge in ("bottom", "left"):
            self.plot.getAxis(edge).enableAutoSIPrefix(False)
        self.plot.setLabel("bottom", "Time (ms)")
        self.plot.setLabel("left", "Input (V)")
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
        for box in self.show_channel:
            box.toggled.connect(self._channels_changed)
        self.plot.getViewBox().sigRangeChangedManually.connect(self._view_changed_manually)
        self.set_enabled(False, False)

    def _channels_changed(self, *_args) -> None:
        for curve, box in zip(
            (self.channel_1_curve, self.channel_2_curve), self.show_channel, strict=True
        ):
            curve.setVisible(box.isChecked())
        for labels, box in zip(self.measurements, self.show_channel, strict=True):
            for label in labels:
                label.setEnabled(box.isChecked())
        if self._last_capture is not None:
            self.apply_capture(self._last_capture)

    def _arm(self) -> None:
        self._live_display = False
        self.plot.setLabel("bottom", "Time (ms)")
        self.trigger_line.setVisible(True)
        self.arm_requested.emit(self.config())

    def _run(self) -> None:
        self._live_display = True
        self._live_time = np.empty(0)
        self._live_first = np.empty(0)
        self._live_second = np.empty(0)
        self._live_next_ms = 0.0
        self._live_block_ms = 0.0
        self.plot.setLabel("bottom", "Captured time (ms)")
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
        self._last_capture = capture
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
        for labels, values, box in zip(
            self.measurements, (first, second), self.show_channel, strict=True
        ):
            if not box.isChecked():
                for label in labels:
                    label.setText("—")
                continue
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
        if scale != "custom":
            self.time_scale.setItemText(self.time_scale.count() - 1, "Custom")
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
        if scale != "custom":
            self.voltage_scale.setItemText(self.voltage_scale.count() - 1, "Custom")
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
        x_range, y_range = self.plot.viewRange()
        if axes[0]:
            self._mark_custom_scale(self.time_scale, (x_range[1] - x_range[0]) / 10, "ms")
            if self._live_display:
                self.follow.setChecked(False)
        if axes[1]:
            self._mark_custom_scale(self.voltage_scale, (y_range[1] - y_range[0]) / 8, "V")

    def _mark_custom_scale(self, combo: QComboBox, per_division: float, unit: str) -> None:
        """Name the division the view is actually at. "Custom" tells the reader
        nothing, and after a pan or zoom that is exactly when they need the number."""
        combo.blockSignals(True)
        combo.setItemText(combo.count() - 1, format_per_division(per_division, unit))
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
        blocked: bool = False,
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
        self.arm.setEnabled(editable and not blocked)
        self.run.setEnabled(editable and not blocked)
        self.stop.setEnabled(connected and not stopping and (live or state in (1, 2, 3)))


class LogicPanel(QWidget):
    arm_requested = Signal(object)
    run_requested = Signal(object)
    stop_requested = Signal()

    PINS = tuple(f"PE{7 + channel}" for channel in range(LOGIC_CHANNELS))
    DECODERS = {
        "Off": (),
        "UART": ("Data",),
        "SPI": ("Clock", "Data", "Select"),
        "I2C": ("SCL", "SDA"),
    }

    def __init__(self):
        super().__init__()
        self._capture = None
        self._build_ui()

    def _build_ui(self) -> None:
        page = QVBoxLayout(self)
        controls = QGroupBox("Acquisition")
        row = QHBoxLayout(controls)

        self.sample_rate = QComboBox()
        for value in LOGIC_RATES:
            self.sample_rate.addItem(f"{value // 1_000_000} MS/s", value)
        self.sample_count = QComboBox()
        for value in (256, 512, 1024, 2048, 4096):
            self.sample_count.addItem(str(value), value)
        self.sample_count.setCurrentIndex(self.sample_count.findData(1024))
        self.trigger_mode = QComboBox()
        for label, value in (("Free run", 0), ("Rising", 1), ("Falling", 2), ("Pattern", 3)):
            self.trigger_mode.addItem(label, value)
        self.trigger_channel = QComboBox()
        for channel, pin in enumerate(self.PINS):
            self.trigger_channel.addItem(f"D{channel} ({pin})", channel)
        self.pretrigger = QDoubleSpinBox()
        self.pretrigger.setRange(0, 90)
        self.pretrigger.setValue(50)
        self.pretrigger.setSuffix(" %")

        for label, widget in (
            ("Rate", self.sample_rate),
            ("Samples", self.sample_count),
            ("Trigger", self.trigger_mode),
            ("Channel", self.trigger_channel),
            ("Pretrigger", self.pretrigger),
        ):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            column.addWidget(widget)
            row.addLayout(column)

        # Built but not placed here: the advanced panel adopts these, because a masked
        # pattern is a rare choice and eight combo boxes crowd out the common ones.
        self.pattern = []
        for channel in range(LOGIC_CHANNELS):
            combo = QComboBox()
            combo.addItem("X", None)
            combo.addItem("0", 0)
            combo.addItem("1", 1)
            combo.setFixedWidth(52)
            combo.setToolTip(f"D{channel} ({self.PINS[channel]})")
            self.pattern.append(combo)

        self.arm = QPushButton("Single")
        self.run = QPushButton("Run")
        self.run.setToolTip("Continuously refresh using repeated finite captures")
        self.stop = QPushButton("Stop")
        row.addWidget(self.arm)
        row.addWidget(self.run)
        row.addWidget(self.stop)
        page.addWidget(controls)

        self.plot = pg.PlotWidget()
        self.plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.plot.setLabel("bottom", "Time (µs)")
        self.plot.setYRange(-0.4, LOGIC_CHANNELS)
        self.plot.showGrid(x=True, y=False, alpha=0.25)
        self.plot.setMouseEnabled(x=True, y=False)
        self.plot.setToolTip("Drag to pan. Use the mouse wheel to zoom the time axis.")
        self.plot.getAxis("left").setTicks(
            [[(channel + 0.35, f"D{channel}") for channel in range(LOGIC_CHANNELS)]]
        )
        self.traces = [
            self.plot.plot(pen=pg.mkPen(pg.intColor(channel, LOGIC_CHANNELS), width=2))
            for channel in range(LOGIC_CHANNELS)
        ]
        self.trigger_line = pg.InfiniteLine(
            0, angle=90, pen=pg.mkPen("#e06666", style=Qt.PenStyle.DashLine)
        )
        self.plot.addItem(self.trigger_line)
        self.plot.setMinimumHeight(220)

        decode = QGroupBox("Decoder")
        decode_layout = QVBoxLayout(decode)
        decode_row = QHBoxLayout()
        self.decoder = QComboBox()
        for name in self.DECODERS:
            self.decoder.addItem(name, name)
        column = QVBoxLayout()
        column.addWidget(QLabel("Protocol"))
        column.addWidget(self.decoder)
        decode_row.addLayout(column)

        self.decode_labels = []
        self.decode_channels = []
        for slot in range(3):
            label = QLabel("")
            combo = QComboBox()
            for channel, pin in enumerate(self.PINS):
                combo.addItem(f"D{channel} ({pin})", channel)
            combo.setCurrentIndex(slot)
            column = QVBoxLayout()
            column.addWidget(label)
            column.addWidget(combo)
            decode_row.addLayout(column)
            self.decode_labels.append(label)
            self.decode_channels.append(combo)

        self.baud = QDoubleSpinBox()
        self.baud.setRange(300, 5_000_000)
        self.baud.setDecimals(0)
        self.baud.setValue(115200)
        self.baud.setSuffix(" Bd")
        self.baud_label = QLabel("Baud")
        column = QVBoxLayout()
        column.addWidget(self.baud_label)
        column.addWidget(self.baud)
        decode_row.addLayout(column)
        decode_row.addStretch(1)
        decode_layout.addLayout(decode_row)
        self.decode_output = QPlainTextEdit()
        self.decode_output.setReadOnly(True)
        self.decode_output.setMaximumHeight(90)
        self.decode_output.setPlaceholderText("Select a protocol to decode the capture")
        decode_layout.addWidget(self.decode_output)

        summary = QGroupBox("Capture")
        grid = QGridLayout(summary)
        headings = ("", "Transitions", "Duty", "Min high", "Min low", "Frequency", "Jitter")
        for column_index, text in enumerate(headings):
            grid.addWidget(QLabel(text), 0, column_index)
        self.measurements = []
        for channel in range(LOGIC_CHANNELS):
            grid.addWidget(QLabel(f"D{channel} ({self.PINS[channel]})"), channel + 1, 0)
            labels = [QLabel("—") for _ in headings[1:]]
            for column_index, label in enumerate(labels, 1):
                grid.addWidget(label, channel + 1, column_index)
            self.measurements.append(labels)
        self.logic_state = QLabel("Idle")
        self.logic_counts = QLabel("Trigger misses 0  |  Overruns 0  |  DMA errors 0")
        grid.addWidget(self.logic_state, LOGIC_CHANNELS + 1, 0)

        # Eight channels of readout are taller than the traces they describe. Scrolling
        # the readout lets the plot keep its height on a short window, and the splitter
        # lets the reader trade one against the other.
        readout = QWidget()
        readout_layout = QVBoxLayout(readout)
        readout_layout.setContentsMargins(0, 0, 0, 0)
        readout_layout.addWidget(decode)
        readout_layout.addWidget(summary)
        readout_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(readout)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMinimumHeight(120)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.plot)
        splitter.addWidget(scroll)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        page.addWidget(splitter, 1)

        self.arm.clicked.connect(self._arm)
        self.run.clicked.connect(self._run)
        self.stop.clicked.connect(self.stop_requested)
        self.trigger_mode.currentIndexChanged.connect(self._trigger_mode_changed)
        self.decoder.currentIndexChanged.connect(self._decoder_changed)
        for combo in self.decode_channels:
            combo.currentIndexChanged.connect(self._decode)
        self.baud.valueChanged.connect(self._decode)
        self._trigger_mode_changed()
        self._decoder_changed()
        self.set_enabled(False, False)

    def _arm(self) -> None:
        self.arm_requested.emit(self.config())

    def _run(self) -> None:
        self.run_requested.emit(self.config())

    def _trigger_mode_changed(self) -> None:
        mode = self.trigger_mode.currentData()
        self.trigger_channel.setEnabled(mode in (1, 2))
        for combo in self.pattern:
            combo.setEnabled(mode == 3)

    def _decoder_changed(self) -> None:
        names = self.DECODERS[self.decoder.currentData()]
        for slot, label in enumerate(self.decode_labels):
            used = slot < len(names)
            label.setText(names[slot] if used else "")
            label.setVisible(used)
            self.decode_channels[slot].setVisible(used)
        uart = self.decoder.currentData() == "UART"
        self.baud.setVisible(uart)
        self.baud_label.setVisible(uart)
        self._decode()

    def config(self) -> LogicConfig:
        mask = value = 0
        for channel, combo in enumerate(self.pattern):
            level = combo.currentData()
            if level is not None:
                mask |= 1 << channel
                value |= level << channel
        return LogicConfig(
            self.sample_rate.currentData(),
            self.sample_count.currentData(),
            self.trigger_mode.currentData(),
            self.trigger_channel.currentData(),
            mask,
            value,
            round(self.pretrigger.value() * 10),
        )

    def apply_status(self, status: LogicStatus, live: bool = False) -> None:
        states = ("Idle", "Armed", "Complete", "Fault")
        if live and status.state != 3:
            state = "Live"
        else:
            state = states[status.state] if status.state < len(states) else "Unknown"
        rate = status.actual_rate or status.sample_rate
        self.logic_state.setText(f"{state} at {rate / 1e6:.3f} MS/s")
        self.logic_counts.setText(
            f"Trigger misses {status.trigger_misses}  |  Overruns {status.overruns}  |  "
            f"DMA errors {status.dma_errors}"
        )

    def apply_capture(self, capture: LogicCapture) -> None:
        self._capture = capture
        rate = capture.status.actual_rate or capture.status.sample_rate
        at = (np.arange(len(capture.samples)) - capture.status.trigger_index) * 1e6 / rate
        steps = np.repeat(at, 2)[1:]
        for channel, curve in enumerate(self.traces):
            bits = channel_bits(capture.samples, channel)
            curve.setData(steps, np.repeat(bits * 0.7 + channel, 2)[:-1])
        self.plot.setXRange(float(at[0]), float(at[-1]))
        for channel, labels in enumerate(self.measurements):
            result = logic_measure(capture.samples, channel, rate)
            labels[0].setText(str(result.transitions))
            labels[1].setText(f"{result.duty * 100:.1f} %")
            labels[2].setText(format_duration(result.shortest_high))
            labels[3].setText(format_duration(result.shortest_low))
            labels[4].setText(f"{result.frequency / 1000:.3f} kHz" if result.frequency else "—")
            labels[5].setText(format_duration(result.jitter))
        self._decode()

    def _decode(self) -> None:
        name = self.decoder.currentData()
        if self._capture is None or name == "Off":
            self.decode_output.setPlainText("")
            return
        capture = self._capture
        rate = capture.status.actual_rate or capture.status.sample_rate
        channels = [combo.currentData() for combo in self.decode_channels]
        try:
            if name == "UART":
                symbols = decode_uart(capture.samples, channels[0], rate, self.baud.value())
            elif name == "SPI":
                symbols = decode_spi(capture.samples, channels[0], channels[1], channels[2])
            else:
                symbols = decode_i2c(capture.samples, channels[0], channels[1])
        except ValueError as exc:
            self.decode_output.setPlainText(str(exc))
            return
        if not symbols:
            self.decode_output.setPlainText("No symbols decoded")
            return
        origin = capture.status.trigger_index
        self.decode_output.setPlainText(
            "\n".join(
                f"{(symbol.start - origin) * 1e6 / rate:10.3f} us  {symbol.text}"
                for symbol in symbols
            )
        )

    def set_enabled(
        self,
        connected: bool,
        busy: bool,
        state: int = 0,
        live: bool = False,
        transferring: bool = False,
        stopping: bool = False,
        blocked: bool = False,
    ) -> None:
        editable = connected and not busy and not transferring and state != 1 and not live
        for widget in (self.sample_rate, self.sample_count, self.trigger_mode, self.pretrigger):
            widget.setEnabled(editable)
        mode = self.trigger_mode.currentData()
        self.trigger_channel.setEnabled(editable and mode in (1, 2))
        for combo in self.pattern:
            combo.setEnabled(editable and mode == 3)
        self.arm.setEnabled(editable and not blocked)
        self.run.setEnabled(editable and not blocked)
        self.stop.setEnabled(connected and not stopping and (live or state in (1, 2, 3)))


class MixedPanel(QWidget):
    """Analog and digital captures drawn against one time axis.

    The two plots are separate because the vertical scales have nothing in common, but
    their x axes are linked, so panning or zooming either moves both. Zero is the
    trigger instant of whichever stream carried the trigger.
    """

    arm_requested = Signal(str)
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self._alignment = None
        self._build_ui()

    def _build_ui(self) -> None:
        page = QVBoxLayout(self)
        controls = QGroupBox("Mixed capture")
        row = QHBoxLayout(controls)

        self.triggered_by = QComboBox()
        self.triggered_by.addItem("Logic analyzer", "logic")
        self.triggered_by.addItem("Oscilloscope", "scope")
        self.triggered_by.setToolTip(
            "Only one stream may search for an edge. The other free-runs and is placed "
            "against the shared start, so the device refuses a follower that triggers."
        )
        column = QVBoxLayout()
        column.addWidget(QLabel("Triggered by"))
        column.addWidget(self.triggered_by)
        row.addLayout(column)

        self.arm = QPushButton("Single")
        self.stop = QPushButton("Stop")
        row.addWidget(self.arm)
        row.addWidget(self.stop)
        row.addStretch(1)
        self.state_label = QLabel("Idle")
        row.addWidget(self.state_label)
        page.addWidget(controls)

        self.analog_plot = pg.PlotWidget()
        self.analog_plot.getAxis("left").enableAutoSIPrefix(False)
        self.analog_plot.setLabel("left", "Input (V)")
        self.analog_plot.showGrid(x=True, y=True, alpha=0.25)
        self.analog_plot.addLegend()
        self.channel_1_curve = self.analog_plot.plot(pen=pg.mkPen("#f5c542", width=2), name="CH1")
        self.channel_2_curve = self.analog_plot.plot(pen=pg.mkPen("#4aa8ff", width=2), name="CH2")

        self.digital_plot = pg.PlotWidget()
        self.digital_plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.analog_plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.digital_plot.setLabel("bottom", "Time from trigger (µs)")
        self.digital_plot.setYRange(-0.4, LOGIC_CHANNELS)
        self.digital_plot.showGrid(x=True, y=False, alpha=0.25)
        self.digital_plot.getAxis("left").setTicks(
            [[(channel + 0.35, f"D{channel}") for channel in range(LOGIC_CHANNELS)]]
        )
        self.traces = [
            self.digital_plot.plot(pen=pg.mkPen(pg.intColor(channel, LOGIC_CHANNELS), width=2))
            for channel in range(LOGIC_CHANNELS)
        ]
        # One timeline means one x axis: moving either plot moves the other.
        self.digital_plot.setXLink(self.analog_plot)

        for plot in (self.analog_plot, self.digital_plot):
            line = pg.InfiniteLine(0, angle=90, pen=pg.mkPen("#e06666", style=Qt.PenStyle.DashLine))
            plot.addItem(line)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.analog_plot)
        splitter.addWidget(self.digital_plot)
        splitter.setChildrenCollapsible(False)
        for index in (0, 1):
            splitter.setStretchFactor(index, 1)
        page.addWidget(splitter, 1)

        coverage = QGroupBox("Timeline")
        grid = QGridLayout(coverage)
        headings = ("Stream", "Rate", "Covers", "Samples")
        for column_index, text in enumerate(headings):
            grid.addWidget(QLabel(text), 0, column_index)
        self.coverage = []
        for row_index, name in enumerate(("Analog", "Digital"), 1):
            grid.addWidget(QLabel(name), row_index, 0)
            labels = [QLabel("—") for _ in headings[1:]]
            for column_index, label in enumerate(labels, 1):
                grid.addWidget(label, row_index, column_index)
            self.coverage.append(labels)
        self.overlap_label = QLabel("No capture yet")
        grid.addWidget(self.overlap_label, 3, 0, 1, len(headings))
        page.addWidget(coverage)

        self.arm.clicked.connect(lambda: self.arm_requested.emit(self.triggered_by.currentData()))
        self.stop.clicked.connect(self.stop_requested)
        self.set_enabled(False, False)

    def apply_status(self, status: MixedStatus) -> None:
        states = ("Idle", "Armed", "Complete", "Fault")
        label = states[status.state] if status.state < len(states) else "Unknown"
        self.state_label.setText(
            f"{label}, triggered by {status.trigger_name}  |  restarts {status.restarts}"
        )

    def apply_capture(self, analog, digital, alignment) -> None:
        """Draw both captures with zero at the trigger instant."""
        self._alignment = alignment
        scope, logic = alignment.streams
        reference = self._reference

        analog_us = alignment.relative(scope) * 1e6
        for curve, values in zip(
            (self.channel_1_curve, self.channel_2_curve),
            (analog.channel_1, analog.channel_2),
            strict=True,
        ):
            curve.setData(analog_us, adc_volts(values, reference))

        digital_us = alignment.relative(logic) * 1e6
        steps = np.repeat(digital_us, 2)[1:]
        for channel, curve in enumerate(self.traces):
            bits = channel_bits(digital.samples, channel)
            curve.setData(steps, np.repeat(bits * 0.7 + channel, 2)[:-1])

        for labels, stream in zip(self.coverage, (scope, logic), strict=True):
            labels[0].setText(f"{stream.rate / 1e6:.3f} MS/s")
            labels[1].setText(
                f"{(stream.start - alignment.origin) * 1e6:+.2f} to "
                f"{(stream.end - alignment.origin) * 1e6:+.2f} µs"
            )
            labels[2].setText(str(stream.count))

        if alignment.complete:
            self.overlap_label.setText(
                f"Both streams cover {alignment.overlap * 1e6:.2f} µs; outside that "
                "only one stream has data."
            )
        else:
            self.overlap_label.setText(
                "The two windows do not overlap. Nothing here can be compared across "
                "streams; shorten the faster capture or slow the other one."
            )
        self.analog_plot.setXRange(
            float(min(analog_us[0], digital_us[0])), float(max(analog_us[-1], digital_us[-1]))
        )

    _reference = 3.0

    def set_reference(self, volts: float) -> None:
        self._reference = volts

    def set_enabled(
        self,
        connected: bool,
        busy: bool,
        state: int = 0,
        transferring: bool = False,
        blocked: bool = False,
    ) -> None:
        editable = connected and not busy and not transferring and state != 1
        self.triggered_by.setEnabled(editable)
        self.arm.setEnabled(editable and not blocked)
        self.stop.setEnabled(connected and state in (1, 2, 3))


class ReferenceOutput(QGroupBox):
    """The TIM3 square wave on PC6.

    It exists in the firmware and reaches far past the 20 kHz the DAC can manage, which
    makes it the only on-board source fast enough to exercise the logic inputs near their
    limit. It was previously reachable only from a script.
    """

    changed = Signal(float, float)

    def __init__(self):
        super().__init__("Reference output — PC6")
        layout = QFormLayout(self)
        self.frequency = QDoubleSpinBox()
        self.frequency.setRange(1, 42_000_000)
        self.frequency.setDecimals(0)
        self.frequency.setValue(100_000)
        self.frequency.setSuffix(" Hz")
        self.frequency.setToolTip("A square wave for probing the logic inputs, 1 Hz to 42 MHz")
        self.duty = QDoubleSpinBox()
        self.duty.setRange(1, 99)
        self.duty.setValue(50)
        self.duty.setSuffix(" %")
        self.enabled = QPushButton("Output off")
        self.enabled.setCheckable(True)
        self.actual = QLabel("—")
        layout.addRow("Frequency", self.frequency)
        layout.addRow("Duty", self.duty)
        layout.addRow("Actual", self.actual)
        layout.addRow(self.enabled)

        self.enabled.toggled.connect(self._toggled)
        self.frequency.valueChanged.connect(self._emit)
        self.duty.valueChanged.connect(self._emit)

    def _toggled(self, on: bool) -> None:
        self.enabled.setText("Output on" if on else "Output off")
        self._emit()

    def _emit(self) -> None:
        # Zero is how the device is told to stop, so the off state needs no second command.
        hz = self.frequency.value() if self.enabled.isChecked() else 0.0
        self.changed.emit(hz, self.duty.value())

    def apply_status(self, actual_hz) -> None:
        self.actual.setText(f"{actual_hz:,.0f} Hz" if actual_hz else "—")

    def set_editable(self, editable: bool) -> None:
        for widget in (self.frequency, self.duty, self.enabled):
            widget.setEnabled(editable)


class SourceColumn(QWidget):
    """Everything the board can drive, in one place that stays visible.

    Sources sit beside the display rather than behind a tab because a bench session is
    almost always "change the source, look at the result". Switching views to do that
    hides the very thing being changed.
    """

    def __init__(self, outputs, reference):
        super().__init__()
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        for panel in outputs:
            page.addWidget(panel)
        page.addWidget(reference)
        page.addStretch(1)


class DisplayColumn(QWidget):
    """One display, with a selector for what is on it.

    Analog, digital and both are three ways of looking at the same instant, not three
    instruments, so they share a pane instead of each owning a tab.
    """

    mode_changed = Signal(str)

    MODES = (
        ("Analog", "scope", "Two analog inputs on PC4 and PC5"),
        ("Digital", "logic", "Eight logic inputs on PE7 to PE14"),
        ("Both", "mixed", "Analog and digital on one timeline"),
    )

    def __init__(self, scope, logic, mixed):
        super().__init__()
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)

        chooser = QHBoxLayout()
        chooser.setSpacing(0)
        self.buttons = QButtonGroup(self)
        self.buttons.setExclusive(True)
        for index, (label, mode, tip) in enumerate(self.MODES):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setObjectName("mode")
            button.setChecked(index == 0)
            self.buttons.addButton(button, index)
            chooser.addWidget(button)
        chooser.addStretch(1)
        page.addLayout(chooser)

        self.stack = QStackedWidget()
        for widget in (scope, logic, mixed):
            self.stack.addWidget(widget)
        page.addWidget(self.stack, 1)

        self.buttons.idClicked.connect(self._choose)

    def _choose(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.mode_changed.emit(self.MODES[index][1])

    def mode(self) -> str:
        return self.MODES[self.stack.currentIndex()][1]

    def set_mode(self, mode: str) -> None:
        for index, (_, name, _tip) in enumerate(self.MODES):
            if name == mode:
                self.buttons.button(index).setChecked(True)
                self.stack.setCurrentIndex(index)
                return


class AdvancedDialog(QDialog):
    """Settings that are chosen once, and counters read only when something looks wrong.

    Keeping these out of the main view is the point: a supply reference is set when the
    board is first measured, a masked pattern is a rare trigger, and an error counter is
    worth reading when a capture looks wrong rather than continuously.
    """

    def __init__(self, scope, logic, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Advanced")
        page = QVBoxLayout(self)

        supply = QGroupBox("Supply reference")
        supply_form = QFormLayout(supply)
        supply_form.addRow("VDDA", scope.reference)
        note = QLabel("Every voltage is relative to this. Measure it once and enter it.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        supply_form.addRow(note)
        page.addWidget(supply)

        pattern = QGroupBox("Logic pattern trigger")
        pattern_layout = QVBoxLayout(pattern)
        row = QHBoxLayout()
        row.setSpacing(2)
        row.addWidget(QLabel("D7"))
        for combo in reversed(logic.pattern):
            row.addWidget(combo)
        row.addWidget(QLabel("D0"))
        row.addStretch(1)
        pattern_layout.addLayout(row)
        pattern_note = QLabel(
            'Used when the digital trigger is set to "Pattern". X ignores a channel.'
        )
        pattern_note.setObjectName("hint")
        pattern_note.setWordWrap(True)
        pattern_layout.addWidget(pattern_note)
        page.addWidget(pattern)

        counters = QGroupBox("Error counters")
        counter_form = QFormLayout(counters)
        self.underrun_label = QLabel("—")
        self.dma_error_label = QLabel("—")
        self.refill_miss_label = QLabel("—")
        counter_form.addRow("AWG underruns", self.underrun_label)
        counter_form.addRow("AWG DMA errors", self.dma_error_label)
        counter_form.addRow("Refill misses", self.refill_miss_label)
        counter_form.addRow("Analog", scope.scope_counts)
        counter_form.addRow("Digital", logic.logic_counts)
        page.addWidget(counters)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        page.addLayout(buttons)


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
        self._logic_status = None
        self._logic_read_id = None
        self._logic_live = False
        self._logic_config = None
        self._logic_transfer = False
        self._logic_stopping = False
        self._device_status = None
        self._mixed_status = None
        self._mixed_read_id = None
        self._mixed_transfer = False
        self._firmware = None

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
        page.setContentsMargins(16, 12, 16, 12)
        page.setSpacing(10)
        page.addLayout(self._build_connection_bar())
        page.addWidget(self.firmware_warning)

        self.outputs = [OutputPanel(0, "PA4"), OutputPanel(1, "PA5")]
        self.reference_output = ReferenceOutput()
        self.source = SourceColumn(self.outputs, self.reference_output)
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")

        self.scope = ScopePanel()
        self.logic = LogicPanel()
        self.mixed = MixedPanel()
        self.display = DisplayColumn(self.scope, self.logic, self.mixed)
        self.advanced = AdvancedDialog(self.scope, self.logic, self)
        # The counters moved into the advanced panel; the handlers still address them here.
        self.underrun_label = self.advanced.underrun_label
        self.dma_error_label = self.advanced.dma_error_label
        self.refill_miss_label = self.advanced.refill_miss_label

        # Two output panels with their dials are taller than a short laptop screen, so the
        # source column scrolls rather than squeezing the display beside it.
        source_area = QScrollArea()
        source_area.setWidget(self.source)
        source_area.setWidgetResizable(True)
        source_area.setFrameShape(QScrollArea.Shape.NoFrame)
        source_area.setMinimumWidth(400)
        source_area.setMaximumWidth(560)

        # Start and Stop sit outside the scroll area. Two output panels with their dials
        # are taller than the window, and the one control you always need should not be
        # the one you have to scroll to find.
        source_side = QWidget()
        source_layout = QVBoxLayout(source_side)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.addWidget(source_area, 1)
        actions = QHBoxLayout()
        actions.addWidget(self.start_button, 1)
        actions.addWidget(self.stop_button, 1)
        source_layout.addLayout(actions)
        hint = QLabel("Shift while dragging a knob for fine control")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        source_layout.addWidget(hint)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(source_side)
        split.addWidget(self.display)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(False)
        # Give the sources enough room that nothing is cut off before the user has
        # touched the handle; the display takes whatever is left.
        split.setSizes([440, 880])
        page.addWidget(split, 1)

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        for caption, label in (
            ("Device", self.device_label),
            ("Output", self.state_label),
            ("Capture", self.acquisition_label),
            ("Firmware", self.firmware_label),
        ):
            self.statusBar().addPermanentWidget(QLabel(f"{caption}:"))
            self.statusBar().addPermanentWidget(label)
        self.statusBar().showMessage("Disconnected")
        self.setStyleSheet(
            "QLabel#hint { color: #888; }"
            "QLabel#warning { color: #e6a23c; padding: 6px 10px;"
            " border: 1px solid #e6a23c; border-radius: 4px; }"
            "QGroupBox { font-weight: 600; margin-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
            "QPushButton { min-height: 28px; padding: 0 12px; }"
            "QPushButton#mode { min-width: 96px; padding: 0 18px; }"
            "QPushButton#mode:checked { font-weight: 600; }"
            "QComboBox, QDoubleSpinBox { min-height: 28px; }"
        )

    def _build_connection_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(260)
        self.refresh_button = QPushButton("Refresh")
        self.connect_button = QPushButton("Connect")
        self.advanced_button = QPushButton("Advanced")
        self.advanced_button.setToolTip("Supply reference, pattern trigger and error counters")
        bar.addWidget(self.port_combo, 1)
        bar.addWidget(self.refresh_button)
        bar.addWidget(self.connect_button)
        bar.addSpacing(12)
        bar.addWidget(self.advanced_button)

        # A mismatch is worth saying once and leaving on screen; the status bar's message
        # is overwritten by the next capture, so this sits in the bar instead.
        self.firmware_warning = QLabel()
        self.firmware_warning.setObjectName("warning")
        self.firmware_warning.setWordWrap(True)
        self.firmware_warning.hide()

        # Read at a glance, so they sit in the status bar rather than taking a row.
        self.device_label = QLabel("—")
        self.connection_label = QLabel("Disconnected")
        self.state_label = QLabel("—")
        self.acquisition_label = QLabel("—")
        self.firmware_label = QLabel("—")
        return bar

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self._toggle_connection)
        self.advanced_button.clicked.connect(self.advanced.show)
        self.reference_output.changed.connect(self._session.configure_probe)
        self.display.mode_changed.connect(self._on_mode_changed)
        for panel in self.outputs:
            panel.load_requested.connect(self._load_table)
            panel.waveform.currentIndexChanged.connect(self._update_controls)
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self._stop)
        self.scope.arm_requested.connect(self._arm_scope)
        self.scope.run_requested.connect(self._run_scope)
        self.scope.stop_requested.connect(self._stop_scope)
        self.logic.arm_requested.connect(self._arm_logic)
        self.logic.run_requested.connect(self._run_logic)
        self.logic.stop_requested.connect(self._stop_logic)
        self.mixed.arm_requested.connect(self._arm_mixed)
        self.mixed.stop_requested.connect(self._stop_mixed)
        self._session.connected.connect(self._on_connected)
        self._session.status_changed.connect(self._on_statuses)
        self._session.scope_status_changed.connect(self._on_scope_status)
        self._session.capture_ready.connect(self._on_capture)
        self._session.logic_status_changed.connect(self._on_logic_status)
        self._session.logic_capture_ready.connect(self._on_logic_capture)
        self._session.device_status_changed.connect(self._on_device_status)
        self._session.mixed_status_changed.connect(self._on_mixed_status)
        self._session.mixed_capture_ready.connect(self._on_mixed_capture)
        self._session.firmware_reported.connect(self._on_firmware)
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

    def _arm_logic(self, config: LogicConfig) -> None:
        self._set_logic_live(False)
        self._logic_config = config
        self._logic_read_id = None
        self._set_busy(True)
        self._session.arm_logic(config)

    def _run_logic(self, config: LogicConfig) -> None:
        self._set_logic_live(True)
        self._logic_config = config
        self._logic_read_id = None
        self._set_busy(True)
        self._session.arm_logic(config)

    def _stop_logic(self) -> None:
        if self._logic_stopping:
            return
        self._logic_stopping = True
        self._set_logic_live(False)
        self._set_busy(True)
        self._session.stop_logic()

    def _arm_mixed(self, triggered_by: str) -> None:
        """Send the acquisition settings along with the arm.

        The combined view has no controls of its own; it borrows the analog and digital
        ones. Sending them here is what lets it stand alone, instead of depending on
        those views having been run first, which nothing on screen ever said.
        """
        scope_config = self.scope.config()
        logic_config = self.logic.config()
        # Only the nominated stream may search for an edge. Forcing the follower to
        # free-run beats letting the device refuse an arm the user cannot diagnose.
        if triggered_by == "logic":
            scope_config = replace(scope_config, trigger_edge=0)
        else:
            logic_config = replace(logic_config, trigger_mode=0)
        self._mixed_read_id = None
        self._scope_config = scope_config
        self._logic_config = logic_config
        self._set_busy(True)
        self._session.arm_mixed(triggered_by, scope_config, logic_config)

    def _on_mode_changed(self, mode: str) -> None:
        """Leave a capture running in a view the user just left, but stop following it."""
        if mode != "scope" and self._scope_live:
            self._stop_scope()
        if mode != "logic" and self._logic_live:
            self._stop_logic()
        self._update_controls()

    def _stop_mixed(self) -> None:
        self._set_busy(True)
        self._session.stop_mixed()

    def _on_mixed_status(self, status: MixedStatus) -> None:
        self._mixed_status = status
        self.mixed.apply_status(status)
        if (
            status.state == 2
            and status.capture_id != self._mixed_read_id
            and not self._busy
            and not self._mixed_transfer
        ):
            self._mixed_read_id = status.capture_id
            self._mixed_transfer = True
            self._session.read_mixed_capture()
        self._update_controls()

    def _on_mixed_capture(self, payload) -> None:
        """Both captures plus the statuses that place them on the timeline."""
        self._mixed_transfer = False
        analog, digital, scope_status, logic_status = payload
        streams = [
            Stream(
                "scope",
                scope_status.sample_rate,
                scope_status.window_origin,
                scope_status.trigger_index,
                len(analog.channel_1),
            ),
            Stream(
                "logic",
                logic_status.actual_rate,
                logic_status.window_origin,
                logic_status.trigger_index,
                len(digital.samples),
            ),
        ]
        triggered = self._mixed_status.trigger_name if self._mixed_status else "logic"
        self.mixed.set_reference(self.scope.reference.value())
        self.mixed.apply_capture(analog, digital, align(streams, triggered=triggered))
        self.statusBar().showMessage(
            f"Mixed capture {self._mixed_status.capture_id if self._mixed_status else 0} received"
        )

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
            and not self._owned_by("mixed")
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

    def _on_logic_status(self, status: LogicStatus) -> None:
        self._logic_status = status
        if status.state == 0:
            self._logic_stopping = False
        if status.state == 3:
            self._set_logic_live(False)
        self.logic.apply_status(status, self._logic_live)
        if (
            status.state == 2
            and status.capture_id != self._logic_read_id
            and not self._busy
            and not self._logic_transfer
            and not self._owned_by("mixed")
        ):
            self._logic_read_id = status.capture_id
            self._logic_transfer = True
            rearm = self._logic_config if self._logic_live else None
            self._session.read_logic_capture(status, rearm)
        self._update_controls()

    def _on_logic_capture(self, capture: LogicCapture) -> None:
        self._logic_transfer = False
        self.logic.apply_capture(capture)
        prefix = "Live logic" if self._logic_live else "Logic capture"
        self.statusBar().showMessage(f"{prefix} {capture.status.capture_id} received")

    def _on_device_status(self, status: DeviceStatus) -> None:
        """One snapshot drives every panel, so they can never disagree about the device."""
        self._polling = False
        self._device_status = status
        states = ("Unconfigured", "Ready", "Running", "Fault")
        self.state_label.setText(
            states[status.awg_state] if status.awg_state < len(states) else "Unknown"
        )
        self.underrun_label.setText(str(status.underruns))
        self.dma_error_label.setText(str(status.awg_dma_errors))
        self.refill_miss_label.setText(str(status.refill_misses))
        owner = "Free" if status.owner_name == "none" else status.owner_name.title()
        if status.conflicts:
            owner += f" ({status.conflicts} refused)"
        self.acquisition_label.setText(owner)
        # Both panels see the stream state so they can display it, but neither may act on
        # it while mixed capture owns the hardware: their own read finishes by stopping the
        # stream, the device answers an idle stream by restarting the pair, and the mixed
        # capture is torn down before it can be read.
        self._on_scope_status(status.scope_status(self._scope_config or self.scope.config()))
        self._on_logic_status(status.logic_status(self._logic_config or self.logic.config()))

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

    def _on_firmware(self, version) -> None:
        """Say when the board and this application disagree, but let the session continue.

        Blocking would strand a student mid-measurement over a difference that may not
        matter to what they are doing; saying nothing would leave them guessing at a
        missing control. So it connects, and the reason stays on screen.
        """
        self._firmware = version
        wanted = ".".join(str(part) for part in MINIMUM_FIRMWARE)
        if version is None:
            self.firmware_label.setText("unknown")
            self.firmware_warning.setText(
                f"This firmware is too old to report its version. Reflash the board with "
                f"the matching build ({wanted} or newer) if something looks missing."
            )
            self.firmware_warning.show()
            return
        self.firmware_label.setText(str(version))
        if version.supported:
            self.firmware_warning.hide()
            return
        self.firmware_warning.setText(
            f"Firmware {version} does not match this application, which expects {wanted} "
            f"and protocol {VERSION}. It is still connected, but some controls may not work."
        )
        self.firmware_warning.show()

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
        self._logic_status = None
        self._logic_read_id = None
        self._set_logic_live(False)
        self._logic_config = None
        self._logic_transfer = False
        self._logic_stopping = False
        self._device_status = None
        self._mixed_status = None
        self._mixed_read_id = None
        self._mixed_transfer = False
        self._firmware = None
        self.firmware_warning.hide()
        self.firmware_label.setText("—")
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
        self._set_logic_live(False)
        self._logic_transfer = False
        self._logic_stopping = False
        self._mixed_transfer = False
        self.statusBar().showMessage(f"Error: {message}")

    def _owned_by(self, other: str) -> bool:
        """The device grants acquisition to one subsystem at a time; say so up front
        rather than letting the user press Arm and collect a Busy reply."""
        return self._device_status is not None and self._device_status.owner_name == other

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_controls()

    def _set_scope_live(self, live: bool) -> None:
        self._scope_live = live
        self._apply_poll_interval()

    def _set_logic_live(self, live: bool) -> None:
        self._logic_live = live
        self._apply_poll_interval()

    def _apply_poll_interval(self) -> None:
        self._poll_timer.setInterval(100 if self._scope_live or self._logic_live else 500)

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
        self.reference_output.set_editable(self._connected and not self._busy)
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
            self._owned_by("logic"),
        )
        mixed_state = self._mixed_status.state if self._mixed_status else 0
        self.mixed.set_enabled(
            self._connected,
            self._busy,
            mixed_state,
            self._mixed_transfer,
            self._owned_by("scope") or self._owned_by("logic"),
        )
        logic_state = self._logic_status.state if self._logic_status else 0
        self.logic.set_enabled(
            self._connected,
            self._busy,
            logic_state,
            self._logic_live,
            self._logic_transfer,
            self._logic_stopping,
            self._owned_by("scope"),
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
