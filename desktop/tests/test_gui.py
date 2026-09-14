import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from stm32_msi.gui import (
    MainWindow,
    Port,
    format_duration,
    format_per_division,
    parse_sample_table,
)
from stm32_msi.instrument import (
    Capture,
    DeviceStatus,
    FirmwareVersion,
    LogicCapture,
    LogicStatus,
    MixedStatus,
    ScopeStatus,
    Status,
)


class FakeSession(QObject):
    connected = Signal(str, object, object)
    firmware_reported = Signal(object)
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

    def __init__(self):
        super().__init__()
        self.calls = []

    def connect_device(self, port):
        self.calls.append(("connect", port))

    def disconnect_device(self):
        self.calls.append(("disconnect",))

    def refresh(self):
        self.calls.append(("refresh",))

    def configure(self, *settings):
        self.calls.append(("configure", *settings))

    def start(self, configurations=None):
        self.calls.append(("start", configurations))

    def stop(self):
        self.calls.append(("stop",))

    def arm_scope(self, config):
        self.calls.append(("arm_scope", config))

    def stop_scope(self):
        self.calls.append(("stop_scope",))

    def read_capture(self, status, rearm_config=None):
        self.calls.append(("read_capture", status, rearm_config))

    def arm_logic(self, config):
        self.calls.append(("arm_logic", config))

    def stop_logic(self):
        self.calls.append(("stop_logic",))

    def read_logic_capture(self, status, rearm_config=None):
        self.calls.append(("read_logic_capture", status, rearm_config))

    def arm_mixed(self, triggered_by, scope_config=None, logic_config=None):
        self.calls.append(("arm_mixed", triggered_by, scope_config, logic_config))

    def configure_probe(self, frequency_hz, duty_percent=50.0):
        self.calls.append(("configure_probe", frequency_hz, duty_percent))

    def stop_mixed(self):
        self.calls.append(("stop_mixed",))

    def read_mixed_capture(self):
        self.calls.append(("read_mixed_capture",))

    def shutdown(self):
        self.calls.append(("shutdown",))


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    session = FakeSession()
    ports = [Port("COM3", "ST-LINK"), Port("COM4", "USB Serial Device", True)]
    view = MainWindow(session, lambda: ports)
    yield view, session
    view.close()


def status(channel=0, state=1, waveform=0, frequency=1_000_000):
    return Status(state, channel, waveform, frequency, frequency)


def connect(view, session, app):
    statuses = [status(0), status(1)]
    session.connected.emit(
        "STM32-MSI",
        {"channels": 2, "waveforms": 63, "min_hz": 1, "max_hz": 20_000},
        statuses,
    )
    session.busy_changed.emit(False)
    app.processEvents()


def test_instrument_port_is_selected_first(window):
    view, _ = window
    assert view.port_combo.currentData() == "COM4"
    assert view.connect_button.isEnabled()
    assert not view.start_button.isEnabled()


def test_start_applies_both_outputs(window, app):
    view, session = window
    view.connect_button.click()
    assert session.calls[-1] == ("connect", "COM4")
    connect(view, session, app)

    first, second = view.outputs
    assert first.isVisibleTo(view)
    assert second.isVisibleTo(view)
    assert view.start_button.isEnabled()

    first.waveform.setCurrentIndex(3)
    first.frequency.setValue(501.125)
    first.amplitude.setValue(65)
    first.offset.setValue(50)
    first.phase.setValue(90)
    second.waveform.setCurrentIndex(2)
    second.frequency.setValue(2500)
    view.start_button.click()
    command, configurations = session.calls[-1]
    assert command == "start"
    assert configurations[0] == (0, "sawtooth", 501.125, 65.0, 50.0, 90.0, None)
    assert configurations[1][0:4] == (1, "square", 2500.0, 75.0)


def test_frequency_knob_is_linear_and_shift_is_fine(window, app):
    view, session = window
    connect(view, session, app)
    dial = view.outputs[0].frequency_dial
    spin = view.outputs[0].frequency

    dial.setValue((dial.minimum() + dial.maximum()) // 2)
    assert spin.value() == pytest.approx(10_000.5)

    spin.setValue(501.125)
    assert dial.value() == 501_125
    QTest.keyClick(dial, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert spin.value() == pytest.approx(501.126)

    QTest.keyClick(dial, Qt.Key.Key_Right)
    assert spin.value() == pytest.approx(502.126)


def test_both_statuses_update_together(window, app):
    view, session = window
    connect(view, session, app)
    statuses = [
        Status(1, 0, 0, 250_500, 250_499),
        Status(1, 1, 2, 2_500_000, 2_500_001, 400, 500, 1800),
    ]
    session.status_changed.emit(statuses)
    app.processEvents()

    assert view.outputs[0].actual.text() == "250.499 Hz"
    assert view.outputs[0].error.text() == "-0.001 Hz"
    assert view.outputs[1].actual.text() == "2500.001 Hz"
    assert view.outputs[1].error.text() == "+0.001 Hz"


def test_arbitrary_table_parsing_and_configuration(window, app):
    assert parse_sample_table("0, 0x800; 4095\n1024") == [0, 2048, 4095, 1024]
    for text in ("1", "0, 4096", "0, nope"):
        with pytest.raises(ValueError):
            parse_sample_table(text)

    view, session = window
    connect(view, session, app)
    panel = view.outputs[1]
    panel.waveform.setCurrentIndex(5)
    view.start_button.click()
    assert "load an arbitrary table" in view.statusBar().currentMessage()
    view._tables[1] = [0, 4095]
    panel.set_table_count(2)
    view.start_button.click()
    assert session.calls[-1][1][1][-1] == [0, 4095]


def test_running_status_enables_stop(window, app):
    view, session = window
    connect(view, session, app)
    statuses = [
        Status(2, 0, 0, 1_000_000, 1_000_000, refill_misses=2),
        Status(2, 1, 2, 250_000, 249_999, refill_misses=2),
    ]
    session.status_changed.emit(statuses)
    app.processEvents()

    assert view.state_label.text() == "Running"
    assert view.refill_miss_label.text() == "2"
    assert not view.outputs[1].frequency_dial.isEnabled()
    assert view.stop_button.isEnabled()
    view.stop_button.click()
    assert session.calls[-1] == ("stop",)


def test_background_poll_does_not_overlap(window, app):
    view, session = window
    connect(view, session, app)
    view._poll()
    assert session.calls[-1] == ("refresh",)
    refreshes = session.calls.count(("refresh",))
    view._poll()
    assert session.calls.count(("refresh",)) == refreshes
    session.status_changed.emit([status(0), status(1)])
    app.processEvents()
    view._poll()
    assert session.calls.count(("refresh",)) == refreshes + 1


def test_scope_controls_and_capture_plot(window, app):
    view, session = window
    connect(view, session, app)
    session.scope_status_changed.emit(ScopeStatus(0, 100_000, 512, 256, 0, 0, 0, 0))
    app.processEvents()
    view.scope.trigger_edge.setCurrentIndex(1)
    view.scope.arm.click()
    assert session.calls[-1][0] == "arm_scope"
    assert session.calls[-1][1].trigger_edge == 1

    session.busy_changed.emit(False)
    complete = ScopeStatus(2, 100_000, 4, 2, 7, 0, 0, 0)
    session.scope_status_changed.emit(complete)
    app.processEvents()
    assert session.calls[-1] == ("read_capture", complete, None)
    capture = Capture(complete, (0, 1024, 2048, 4095), (4095, 2048, 1024, 0))
    session.capture_ready.emit(capture)
    app.processEvents()
    assert view.scope.channel_1_curve.xData.size == 4
    assert view.scope.measurements[0][4].text().endswith(" V")


def test_scope_scaling_and_manual_traversal(window, app):
    view, session = window
    connect(view, session, app)
    panel = view.scope
    complete = ScopeStatus(2, 100_000, 4, 2, 7, 0, 0, 0)
    capture = Capture(complete, (0, 1024, 2048, 4095), (4095, 2048, 1024, 0))

    panel.time_scale.setCurrentIndex(panel.time_scale.findData(0.5))
    panel.voltage_scale.setCurrentIndex(panel.voltage_scale.findData(0.2))
    panel.vertical_center.setValue(1.2)
    panel.apply_capture(capture)
    x_range, y_range = panel.plot.viewRange()
    assert x_range[1] - x_range[0] == pytest.approx(5.0)
    assert y_range == pytest.approx([0.4, 2.0])

    panel._run()
    panel.apply_capture(capture)
    x_range = panel.plot.viewRange()[0]
    assert x_range[1] - x_range[0] == pytest.approx(5.0)
    assert x_range[1] == pytest.approx(0.04)

    panel._view_changed_manually((True, False))
    assert not panel.follow.isChecked()
    assert panel.time_scale.currentData() == "custom"
    held_range = panel.plot.viewRange()[0]
    panel.apply_capture(capture)
    assert panel.plot.viewRange()[0] == pytest.approx(held_range)

    panel.follow.setChecked(True)
    followed_range = panel.plot.viewRange()[0]
    assert followed_range[1] - followed_range[0] == pytest.approx(held_range[1] - held_range[0])
    assert followed_range[1] == pytest.approx(panel._live_next_ms)

    panel.autoscale.click()
    assert panel.follow.isChecked()
    assert panel.time_scale.currentData() is None
    assert panel.voltage_scale.currentData() is None


def test_scope_run_rearms_after_each_capture(window, app):
    view, session = window
    connect(view, session, app)
    idle = ScopeStatus(0, 100_000, 512, 256, 0, 0, 0, 0)
    session.scope_status_changed.emit(idle)
    app.processEvents()

    view.scope.run.click()
    assert session.calls[-1][0] == "arm_scope"
    assert view._poll_timer.interval() == 100
    live_config = session.calls[-1][1]
    session.busy_changed.emit(False)

    complete = ScopeStatus(2, 100_000, 512, 256, 8, 0, 0, 0)
    session.scope_status_changed.emit(complete)
    app.processEvents()
    assert session.calls[-1] == ("read_capture", complete, live_config)
    assert view.scope.stop.isEnabled()

    session.busy_changed.emit(True)
    app.processEvents()
    assert view.scope.stop.isEnabled()
    session.busy_changed.emit(False)

    first = Capture(complete, (0, 1024, 2048, 4095), (4095, 2048, 1024, 0))
    session.capture_ready.emit(first)
    app.processEvents()
    first_end = view.scope.channel_1_curve.xData[-1]
    assert view.scope.channel_1_curve.xData.size == 4
    message = view.statusBar().currentMessage()

    session.status_changed.emit([status(0), status(1)])
    app.processEvents()
    assert view.statusBar().currentMessage() == message

    second = Capture(complete, (4095, 2048, 1024, 0), (0, 1024, 2048, 4095))
    session.capture_ready.emit(second)
    app.processEvents()
    assert view.scope.channel_1_curve.xData.size == 8
    assert view.scope.channel_1_curve.xData[-1] > first_end
    view.scope.stop.click()
    assert session.calls[-1] == ("stop_scope",)
    assert not view.scope.stop.isEnabled()


def test_empty_port_list_disables_connect(app):
    view = MainWindow(FakeSession(), list)
    assert view.port_combo.currentData() is None
    assert not view.connect_button.isEnabled()
    view.close()


def uart_capture(values, span=16):
    bits = [1] * (2 * span)
    for value in values:
        for bit in [0] + [(value >> index) & 1 for index in range(8)] + [1]:
            bits += [bit] * span
    bits += [1] * span
    status = LogicStatus(2, 1_000_000, 1_000_000, len(bits), 0, 1, 0, 0, 0)
    return LogicCapture(status, tuple(bits))


def test_logic_trigger_controls_follow_the_selected_mode(window, app):
    view, session = window
    connect(view, session, app)
    session.logic_status_changed.emit(LogicStatus(0, 1_000_000, 1_000_000, 1024, 512, 0, 0, 0, 0))
    app.processEvents()
    panel = view.logic

    panel.trigger_mode.setCurrentIndex(1)
    assert panel.trigger_channel.isEnabled()
    assert not panel.pattern[0].isEnabled()

    panel.trigger_mode.setCurrentIndex(3)
    assert not panel.trigger_channel.isEnabled()
    assert all(combo.isEnabled() for combo in panel.pattern)

    panel.pattern[0].setCurrentIndex(2)
    panel.pattern[3].setCurrentIndex(1)
    config = panel.config()
    assert config.trigger_mode == 3
    assert config.trigger_mask == 0b00001001
    assert config.trigger_value == 0b00000001


def test_logic_capture_draws_square_traces_and_measures(window, app):
    view, session = window
    connect(view, session, app)
    complete = LogicStatus(2, 1_000_000, 1_000_000, 8, 4, 3, 0, 0, 0)
    session.logic_status_changed.emit(complete)
    app.processEvents()
    assert session.calls[-1] == ("read_logic_capture", complete, None)

    session.logic_capture_ready.emit(LogicCapture(complete, (0, 0, 1, 1, 0, 0, 1, 1)))
    app.processEvents()
    panel = view.logic
    # Each sample becomes two points so the trace shows square edges.
    assert panel.traces[0].xData.size == 15
    assert panel.traces[0].yData.min() == pytest.approx(0.0)
    assert panel.traces[0].yData.max() == pytest.approx(0.7)
    assert panel.traces[1].yData.min() == pytest.approx(1.0)
    assert panel.measurements[0][0].text() == "3"
    assert panel.measurements[0][1].text() == "50.0 %"
    assert panel.measurements[1][0].text() == "0"
    assert "1.000 MS/s" in panel.logic_state.text()


def test_logic_decoder_output_follows_the_protocol_selection(window, app):
    view, session = window
    connect(view, session, app)
    panel = view.logic
    panel.apply_capture(uart_capture([0x41, 0x42]))
    assert panel.decode_output.toPlainText() == ""

    panel.decoder.setCurrentIndex(panel.decoder.findData("UART"))
    panel.baud.setValue(62_500)
    assert panel.baud.isVisibleTo(panel)
    lines = panel.decode_output.toPlainText().splitlines()
    assert [line.split()[-1] for line in lines] == ["0x41", "0x42"]

    panel.decoder.setCurrentIndex(panel.decoder.findData("I2C"))
    assert not panel.baud.isVisibleTo(panel)
    assert panel.decode_output.toPlainText() == "No symbols decoded"

    panel.decoder.setCurrentIndex(panel.decoder.findData("UART"))
    panel.baud.setValue(1_000_000)
    assert "too slow" in panel.decode_output.toPlainText()


def test_logic_run_rearms_and_stop_clears_it(window, app):
    view, session = window
    connect(view, session, app)
    session.logic_status_changed.emit(LogicStatus(0, 1_000_000, 1_000_000, 1024, 512, 0, 0, 0, 0))
    app.processEvents()

    view.logic.run.click()
    assert session.calls[-1][0] == "arm_logic"
    assert view._poll_timer.interval() == 100
    live_config = session.calls[-1][1]
    session.busy_changed.emit(False)

    complete = LogicStatus(2, 1_000_000, 1_000_000, 8, 4, 9, 0, 0, 0)
    session.logic_status_changed.emit(complete)
    app.processEvents()
    assert session.calls[-1] == ("read_logic_capture", complete, live_config)
    assert view.logic.stop.isEnabled()
    assert not view.logic.run.isEnabled()

    session.logic_capture_ready.emit(LogicCapture(complete, (0, 1, 0, 1, 0, 1, 0, 1)))
    app.processEvents()
    assert "Live logic 9" in view.statusBar().currentMessage()

    view.logic.stop.click()
    assert session.calls[-1] == ("stop_logic",)
    session.logic_status_changed.emit(LogicStatus(0, 1_000_000, 1_000_000, 8, 4, 9, 0, 0, 0))
    session.busy_changed.emit(False)
    app.processEvents()
    assert view._poll_timer.interval() == 500
    assert view.logic.run.isEnabled()


def test_logic_fault_stops_the_live_view(window, app):
    view, session = window
    connect(view, session, app)
    session.logic_status_changed.emit(LogicStatus(0, 2_000_000, 2_000_000, 1024, 512, 0, 0, 0, 0))
    app.processEvents()
    view.logic.run.click()
    session.busy_changed.emit(False)
    session.logic_status_changed.emit(LogicStatus(3, 2_000_000, 2_000_000, 1024, 512, 0, 1, 2, 3))
    app.processEvents()
    assert not view._logic_live
    assert view._poll_timer.interval() == 500
    assert "Fault" in view.logic.logic_state.text()
    assert "Overruns 2" in view.logic.logic_counts.text()


def test_durations_are_formatted_by_magnitude():
    assert format_duration(None) == "\u2014"
    assert format_duration(500e-9) == "500 ns"
    assert format_duration(12.5e-6) == "12.500 us"
    assert format_duration(4e-3) == "4.000 ms"


def device_status(owner=0, conflicts=0, awg_state=1, scope_state=0, logic_state=0, **counts):
    return DeviceStatus(
        owner,
        conflicts,
        awg_state,
        counts.get("underruns", 0),
        counts.get("awg_dma_errors", 0),
        counts.get("refill_misses", 0),
        scope_state,
        counts.get("scope_capture_id", 0),
        counts.get("scope_trigger_misses", 0),
        counts.get("scope_overruns", 0),
        counts.get("scope_dma_errors", 0),
        logic_state,
        counts.get("logic_capture_id", 0),
        counts.get("logic_trigger_misses", 0),
        counts.get("logic_overruns", 0),
        counts.get("logic_dma_errors", 0),
    )


def test_one_snapshot_drives_every_panel(window, app):
    view, session = window
    connect(view, session, app)
    session.device_status_changed.emit(
        device_status(awg_state=2, underruns=3, refill_misses=4, scope_state=1)
    )
    app.processEvents()
    assert view.state_label.text() == "Running"
    assert view.underrun_label.text() == "3"
    assert view.refill_miss_label.text() == "4"
    assert view.acquisition_label.text() == "Free"
    # The scope panel learns it is armed from the same snapshot.
    assert view.scope.scope_state.text() == "Armed"


def test_acquisition_owner_blocks_the_other_panel(window, app):
    view, session = window
    connect(view, session, app)

    session.device_status_changed.emit(device_status(owner=2, logic_state=1))
    app.processEvents()
    assert "Logic" in view.acquisition_label.text()
    # Logic holds the hardware, so Arm is refused up front rather than by the device.
    assert not view.scope.arm.isEnabled()
    assert not view.scope.run.isEnabled()

    session.device_status_changed.emit(device_status(owner=1, scope_state=1))
    app.processEvents()
    assert not view.logic.arm.isEnabled()

    session.device_status_changed.emit(device_status())
    app.processEvents()
    assert view.acquisition_label.text() == "Free"
    assert view.scope.arm.isEnabled()
    assert view.logic.arm.isEnabled()


def test_refused_claims_are_surfaced(window, app):
    view, session = window
    connect(view, session, app)
    session.device_status_changed.emit(device_status(owner=2, conflicts=5, logic_state=1))
    app.processEvents()
    assert "5 refused" in view.acquisition_label.text()


def test_polling_uses_the_unified_snapshot(window, app):
    view, session = window
    connect(view, session, app)
    session.calls.clear()
    view._poll()
    assert session.calls == [("refresh",)]
    # A snapshot clears the in-flight flag so the next tick can poll again.
    session.device_status_changed.emit(device_status())
    app.processEvents()
    view._poll()
    assert session.calls == [("refresh",), ("refresh",)]


def test_manual_zoom_names_the_division_instead_of_custom(window, app):
    view, session = window
    panel = view.scope
    complete = ScopeStatus(2, 1_000_000, 512, 256, 7, 0, 0, 0)
    panel.apply_capture(Capture(complete, tuple(range(512)), tuple(range(512))))

    panel.plot.setXRange(-0.25, 0.25, padding=0)
    panel.plot.setYRange(0.0, 1.6, padding=0)
    panel._view_changed_manually((True, True))
    # 0.5 ms across ten divisions, 1.6 V across eight.
    assert panel.time_scale.currentText() == "50 us/div"
    assert panel.voltage_scale.currentText() == "200 mV/div"
    assert panel.time_scale.currentData() == "custom"

    # Choosing a preset again must not leave the stale number in the list.
    panel.time_scale.setCurrentIndex(panel.time_scale.findData(1.0))
    panel.voltage_scale.setCurrentIndex(panel.voltage_scale.findData(0.5))
    assert panel.time_scale.itemText(panel.time_scale.count() - 1) == "Custom"
    assert panel.voltage_scale.itemText(panel.voltage_scale.count() - 1) == "Custom"


def test_division_labels_pick_a_readable_magnitude():
    assert format_per_division(0.0005, "ms") == "500 ns/div"
    assert format_per_division(0.05, "ms") == "50 us/div"
    assert format_per_division(2.5, "ms") == "2.5 ms/div"
    assert format_per_division(2000.0, "ms") == "2 s/div"
    assert format_per_division(0.2, "V") == "200 mV/div"
    assert format_per_division(1.5, "V") == "1.5 V/div"


def test_hiding_a_channel_drops_it_from_the_plot_and_measurements(window, app):
    view, session = window
    panel = view.scope
    complete = ScopeStatus(2, 1_000_000, 4, 2, 7, 0, 0, 0)
    panel.apply_capture(Capture(complete, (0, 1024, 2048, 4095), (4095, 2048, 1024, 0)))
    assert panel.measurements[0][0].text() != "\u2014"
    assert panel.measurements[1][0].text() != "\u2014"

    panel.show_channel[1].setChecked(False)
    app.processEvents()
    assert panel.channel_1_curve.isVisible()
    assert not panel.channel_2_curve.isVisible()
    # CH2 is not measured while hidden, and says so.
    assert panel.measurements[1][0].text() == "\u2014"
    assert panel.measurements[0][0].text() != "\u2014"

    panel.show_channel[1].setChecked(True)
    app.processEvents()
    assert panel.channel_2_curve.isVisible()
    assert panel.measurements[1][0].text() != "\u2014"


def test_hiding_a_channel_before_any_capture_is_safe(app):
    session = FakeSession()
    view = MainWindow(session, lambda: [Port("COM4", "instrument", True)])
    try:
        view.scope.show_channel[0].setChecked(False)
        app.processEvents()
        assert not view.scope.channel_1_curve.isVisible()
    finally:
        view.close()


def test_mixed_capture_draws_both_streams_on_one_axis(window, app):
    view, session = window
    connect(view, session, app)
    panel = view.mixed

    session.mixed_status_changed.emit(MixedStatus(1, 1, 0, 0, 0, 0))
    app.processEvents()
    assert "Armed" in panel.state_label.text()
    assert "logic" in panel.state_label.text()

    complete = MixedStatus(2, 1, 5, 2, 7, 9)
    session.mixed_status_changed.emit(complete)
    app.processEvents()
    assert session.calls[-1] == ("read_mixed_capture",)
    assert "restarts 2" in panel.state_label.text()

    scope_status = ScopeStatus(2, 1_000_000, 4, 2, 7, 0, 0, 0, 100)
    logic_status = LogicStatus(2, 10_000_000, 9_882_352, 8, 0, 9, 0, 0, 0, 0)
    analog = Capture(scope_status, (0, 1024, 2048, 4095), (4095, 2048, 1024, 0))
    digital = LogicCapture(logic_status, (0, 1, 0, 1, 0, 1, 0, 1))
    session.mixed_capture_ready.emit((analog, digital, scope_status, logic_status))
    app.processEvents()

    assert panel.channel_1_curve.xData.size == 4
    assert panel.traces[0].xData.size == 2 * 8 - 1
    # The scope window starts 100 samples after the shared start, at 1 MS/s, and zero is
    # the logic trigger. Each stream's first sample is one of its own periods after the
    # release, so the two are offset by 1 us - 1/9.88 MS/s on top of the window origin.
    expected = (100 + 1) / 1e6 - (0 + 1 + 0) / 9_882_352
    assert panel.channel_1_curve.xData[0] == pytest.approx(expected * 1e6, abs=1e-6)
    # Linked axes mean one timeline, not two drawn side by side.
    assert panel.digital_plot.getViewBox().linkedView(0) is panel.analog_plot.getViewBox()


def test_the_other_panels_leave_a_mixed_capture_alone(window, app):
    """A scope or logic read ends by stopping that stream, and the device answers an idle
    stream by restarting the pair, so acting on their status during a mixed capture tears
    it down before it can be drawn. Observed on hardware as a climbing restart count with
    the samples arriving in the wrong two tabs."""
    view, session = window
    connect(view, session, app)
    session.mixed_status_changed.emit(MixedStatus(1, 1, 0, 0, 0, 0))
    app.processEvents()
    session.calls.clear()

    # The routine poll reports both streams complete while mixed owns the hardware.
    session.device_status_changed.emit(
        device_status(owner=3, scope_state=2, logic_state=2, scope_capture_id=4, logic_capture_id=4)
    )
    app.processEvents()

    stolen = [
        call
        for call in session.calls
        if call[0] in ("read_capture", "read_logic_capture", "stop_scope", "stop_logic")
    ]
    assert stolen == []

    # With mixed out of the way the same status is read normally.
    session.calls.clear()
    session.device_status_changed.emit(device_status(owner=1, scope_state=2, scope_capture_id=5))
    app.processEvents()
    assert any(call[0] == "read_capture" for call in session.calls)


def test_a_failed_mixed_read_does_not_wedge_the_panel(window, app):
    view, session = window
    connect(view, session, app)
    session.mixed_status_changed.emit(MixedStatus(2, 1, 1, 0, 1, 1))
    app.processEvents()
    assert ("read_mixed_capture",) in session.calls

    # The transfer flag guards against overlapping reads; an error has to clear it or the
    # panel can never read again.
    session.error.emit("capture is no longer available")
    app.processEvents()
    session.calls.clear()
    session.mixed_status_changed.emit(MixedStatus(2, 1, 2, 0, 2, 2))
    app.processEvents()
    assert ("read_mixed_capture",) in session.calls


def test_the_reference_output_reaches_the_device(window, app):
    """The TIM3 square wave was firmware-only until now, reachable only from a script."""
    view, session = window
    connect(view, session, app)
    session.calls.clear()

    view.reference_output.frequency.setValue(250_000)
    view.reference_output.enabled.setChecked(True)
    app.processEvents()
    sent = [call for call in session.calls if call[0] == "configure_probe"]
    assert sent and sent[-1][1] == 250_000
    assert view.reference_output.enabled.text() == "Output on"

    # Zero is how the device is told to stop, so off needs no separate command.
    view.reference_output.enabled.setChecked(False)
    app.processEvents()
    assert [call for call in session.calls if call[0] == "configure_probe"][-1][1] == 0


def test_switching_the_display_stops_a_live_capture_behind_it(window, app):
    """A view the user has left should not keep claiming the acquisition hardware."""
    view, session = window
    connect(view, session, app)
    view.scope.run.click()
    app.processEvents()
    assert view._scope_live

    session.calls.clear()
    view.display.set_mode("logic")
    view.display.mode_changed.emit("logic")
    app.processEvents()
    assert not view._scope_live
    assert ("stop_scope",) in session.calls


def test_the_demoted_settings_live_in_the_advanced_panel(window, app):
    """Set-once and diagnostic controls belong out of the way, not in the capture rows."""
    view, _session = window
    for widget in (view.scope.reference, view.scope.scope_counts, view.logic.logic_counts):
        assert view.advanced.isAncestorOf(widget)
    for combo in view.logic.pattern:
        assert view.advanced.isAncestorOf(combo)
    # Still readable where the panel needs them, which is what keeps the config correct.
    assert view.scope.config().trigger_level == round(1.5 * 4095 / view.scope.reference.value())


def test_firmware_mismatch_warns_without_blocking_the_session(window, app):
    """Refusing would strand a student mid-measurement; silence would leave them guessing."""
    view, session = window
    connect(view, session, app)

    session.firmware_reported.emit(FirmwareVersion(0, 0, 9, 1, "old123"))
    app.processEvents()
    assert not view.firmware_warning.isHidden()
    assert "0.0.9" in view.firmware_warning.text()
    assert view._connected, "a mismatch must not drop the connection"
    assert view.scope.arm.isEnabled(), "and must not disable the instrument"

    session.firmware_reported.emit(FirmwareVersion(0, 1, 0, 1, "a82d489"))
    app.processEvents()
    assert view.firmware_warning.isHidden()
    assert view.firmware_label.text() == "0.1.0 (a82d489)"


def test_firmware_too_old_to_report_itself_is_named_as_such(window, app):
    view, session = window
    connect(view, session, app)
    session.firmware_reported.emit(None)
    app.processEvents()
    assert view.firmware_label.text() == "unknown"
    assert not view.firmware_warning.isHidden()
    assert "too old to report" in view.firmware_warning.text()

    session.disconnected.emit()
    app.processEvents()
    assert view.firmware_warning.isHidden()


def test_mixed_reports_when_the_windows_do_not_overlap(window, app):
    view, session = window
    connect(view, session, app)
    session.mixed_status_changed.emit(MixedStatus(2, 0, 1, 0, 1, 1))
    app.processEvents()

    # A scope window far past the end of a short digital capture.
    scope_status = ScopeStatus(2, 1_000_000, 4, 0, 1, 0, 0, 0, 50_000)
    logic_status = LogicStatus(2, 10_000_000, 10_000_000, 8, 0, 1, 0, 0, 0, 0)
    analog = Capture(scope_status, (0, 1, 2, 3), (0, 1, 2, 3))
    digital = LogicCapture(logic_status, (0, 1) * 4)
    session.mixed_capture_ready.emit((analog, digital, scope_status, logic_status))
    app.processEvents()
    assert "do not overlap" in view.mixed.overlap_label.text()


def test_mixed_arm_is_blocked_while_a_single_subsystem_holds_the_hardware(window, app):
    view, session = window
    connect(view, session, app)
    session.device_status_changed.emit(device_status(owner=1, scope_state=1))
    app.processEvents()
    assert not view.mixed.arm.isEnabled()

    session.device_status_changed.emit(device_status())
    app.processEvents()
    assert view.mixed.arm.isEnabled()

    view.mixed.arm.click()
    # The arm carries its own configuration, so the combined view no longer depends on
    # the analog and digital views having been run first.
    name, triggered, scope_config, logic_config = session.calls[-1]
    assert (name, triggered) == ("arm_mixed", "logic")
    assert scope_config is not None and logic_config is not None
    assert scope_config.trigger_edge == 0, "the follower must be forced to free-run"
    assert logic_config == view.logic.config(), "the leader passes through untouched"
