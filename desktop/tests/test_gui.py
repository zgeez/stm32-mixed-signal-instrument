import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from stm32_msi.gui import MainWindow, Port, parse_sample_table
from stm32_msi.instrument import Capture, ScopeStatus, Status


class FakeSession(QObject):
    connected = Signal(str, object, object)
    status_changed = Signal(object)
    scope_status_changed = Signal(object)
    capture_ready = Signal(object)
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
