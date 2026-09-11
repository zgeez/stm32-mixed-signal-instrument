import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication

from stm32_msi.protocol import Command
from stm32_msi.session import DeviceSession


class TransportStub:
    def __init__(self, port):
        self.port = port
        self.state = 1
        self.waveform = 0
        self.frequency = 1000
        self.closed = False

    def request(self, command, payload=b""):
        if command == Command.HELLO:
            return b"STM32-MSI"
        if command == Command.CAPABILITIES:
            return struct.pack("<BBIIB", 1, 7, 1, 1000, 100)
        if command == Command.AWG_CONFIG:
            self.waveform, self.frequency = struct.unpack("<BI", payload)
        elif command == Command.AWG_START:
            self.state = 2
        elif command == Command.AWG_STOP:
            self.state = 1
        if command == Command.STATUS:
            return struct.pack(
                "<BBIIII",
                self.state,
                self.waveform,
                self.frequency,
                self.frequency * 1000,
                0,
                0,
            )
        return b""

    def close(self):
        self.closed = True


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def wait_for(signal, action):
    result = []
    loop = QEventLoop()

    def receive(*args):
        result.append(args)
        loop.quit()

    signal.connect(receive)
    QTimer.singleShot(1000, loop.quit)
    action()
    loop.exec()
    signal.disconnect(receive)
    assert result
    return result[0]


def test_session_runs_connection_and_commands_on_worker_thread(app):
    worker_threads = []

    def factory(port):
        worker_threads.append(QThread.currentThread())
        return TransportStub(port)

    session = DeviceSession(factory)
    try:
        name, capabilities, status = wait_for(
            session.connected, lambda: session.connect_device("test")
        )
        assert name == "STM32-MSI"
        assert capabilities["max_hz"] == 1000
        assert status.state == 1
        assert worker_threads[0] != app.thread()

        (status,) = wait_for(session.status_changed, session.start)
        assert status.state == 2
        (status,) = wait_for(session.status_changed, session.stop)
        assert status.state == 1
    finally:
        session.shutdown()
