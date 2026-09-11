import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from stm32_msi.gui import MainWindow, Port
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

    def configure(self, waveform, frequency):
        self.calls.append(("configure", waveform, frequency))

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


def ready_status():
    return Status(1, 0, 1000, 1_000_000, 0, 0)


def test_instrument_port_is_selected_first(window):
    view, _ = window
    assert view.port_combo.currentData() == "COM4"
    assert view.connect_button.isEnabled()
    assert not view.start_button.isEnabled()


def test_connection_and_awg_controls(window, app):
    view, session = window
    view.connect_button.click()
    assert session.calls[-1] == ("connect", "COM4")

    session.connected.emit(
        "STM32-MSI",
        {"min_hz": 1, "max_hz": 1000},
        ready_status(),
    )
    session.busy_changed.emit(False)
    app.processEvents()
    assert view.connection_label.text() == "Connected"
    assert view.state_label.text() == "Ready"
    assert view.start_button.isEnabled()

    view.waveform_combo.setCurrentIndex(1)
    view.frequency_dial.setValue(500)
    assert view.frequency_spin.value() == 500
    view.frequency_spin.setValue(501)
    assert view.frequency_dial.value() == 501
    view.configure_button.click()
    assert session.calls[-1] == ("configure", "triangle", 501)


def test_running_status_enables_stop(window, app):
    view, session = window
    session.connected.emit(
        "STM32-MSI",
        {"min_hz": 1, "max_hz": 1000},
        Status(2, 2, 250, 250_000, 1, 0),
    )
    session.busy_changed.emit(False)
    app.processEvents()
    assert view.state_label.text() == "Running"
    assert view.waveform_label.text() == "Square"
    assert view.actual_label.text() == "250.000 Hz"
    assert view.frequency_error_label.text() == "+0.000 Hz (+0.000%)"
    assert not view.configure_button.isEnabled()
    assert not view.frequency_dial.isEnabled()
    assert view.stop_button.isEnabled()

    view.stop_button.click()
    assert session.calls[-1] == ("stop",)


def test_background_poll_keeps_controls_stable(window, app):
    view, session = window
    session.connected.emit(
        "STM32-MSI",
        {"min_hz": 1, "max_hz": 1000},
        ready_status(),
    )
    session.busy_changed.emit(False)
    app.processEvents()
    assert view.start_button.isEnabled()

    view._poll()
    assert session.calls[-1] == ("refresh",)
    assert view.start_button.isEnabled()
    refreshes = session.calls.count(("refresh",))
    view._poll()
    assert session.calls.count(("refresh",)) == refreshes

    session.status_changed.emit(Status(1, 0, 998, 997_625, 0, 0))
    app.processEvents()
    assert view.start_button.isEnabled()
    assert view.frequency_error_label.text() == "-0.375 Hz (-0.038%)"
    view._poll()
    assert session.calls.count(("refresh",)) == refreshes + 1


def test_empty_port_list_disables_connect(app):
    view = MainWindow(FakeSession(), list)
    assert view.port_combo.currentData() is None
    assert not view.connect_button.isEnabled()
    view.close()
