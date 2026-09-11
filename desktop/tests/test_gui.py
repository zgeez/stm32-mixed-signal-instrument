import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from stm32_msi.gui import MainWindow, Port, parse_sample_table
from stm32_msi.instrument import Status


class FakeSession(QObject):
    connected = Signal(str, object, object)
    status_changed = Signal(object)
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

    def start(self):
        self.calls.append(("start",))

    def stop(self):
        self.calls.append(("stop",))

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


def test_both_outputs_are_visible_and_configurable(window, app):
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
    first.apply.click()
    assert session.calls[-1] == (
        "configure",
        0,
        "sawtooth",
        501.125,
        65.0,
        50.0,
        90.0,
        None,
    )

    session.busy_changed.emit(False)
    second.waveform.setCurrentIndex(2)
    second.frequency.setValue(2500)
    second.apply.click()
    assert session.calls[-1][1:5] == (1, "square", 2500.0, 75.0)


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
    panel.apply.click()
    assert "load an arbitrary table" in view.statusBar().currentMessage()
    view._tables[1] = [0, 4095]
    panel.set_table_count(2)
    panel.apply.click()
    assert session.calls[-1][-1] == [0, 4095]


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
    assert not view.outputs[0].apply.isEnabled()
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


def test_empty_port_list_disables_connect(app):
    view = MainWindow(FakeSession(), list)
    assert view.port_combo.currentData() is None
    assert not view.connect_button.isEnabled()
    view.close()
