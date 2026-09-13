import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication

from stm32_msi.instrument import LogicConfig
from stm32_msi.protocol import Command
from stm32_msi.session import DeviceSession


class TransportStub:
    def __init__(self, port):
        self.port = port
        self.state = 1
        self.waveforms = [0, 0]
        self.frequencies = [1000, 1000]
        self.logic_state = 0
        self.logic_rate = 1_000_000
        self.closed = False

    def request(self, command, payload=b""):
        if command == Command.HELLO:
            return b"STM32-MSI"
        if command == Command.CAPABILITIES:
            return struct.pack("<BBIIB", 2, 63, 1, 1000, 100)
        if command == Command.AWG_CONFIG:
            self.waveforms[0], self.frequencies[0] = struct.unpack("<BI", payload)
        elif command == Command.AWG_CONFIG_EXT:
            channel, waveform, frequency, *_rest = struct.unpack("<BBIHHH", payload)
            self.waveforms[channel] = waveform
            self.frequencies[channel] = frequency / 1000
        elif command == Command.AWG_START:
            self.state = 2
        elif command == Command.AWG_STOP:
            self.state = 1
        if command == Command.AWG_STATUS_EXT:
            channel = payload[0]
            return struct.pack(
                "<BBBIIHHHIIIH",
                self.state,
                channel,
                self.waveforms[channel],
                round(self.frequencies[channel] * 1000),
                round(self.frequencies[channel] * 1000),
                750,
                500,
                0,
                0,
                0,
                0,
                0,
            )
        if command == Command.SCOPE_STATUS:
            return struct.pack("<BIHHIIII", 0, 100_000, 512, 256, 0, 0, 0, 0)
        if command == Command.LOGIC_CONFIG:
            self.logic_rate = struct.unpack_from("<I", payload)[0]
        elif command == Command.LOGIC_ARM:
            self.logic_state = 1
        elif command == Command.LOGIC_STOP:
            self.logic_state = 0
        if command == Command.LOGIC_STATUS:
            return struct.pack(
                "<BIIHHIIII",
                self.logic_state,
                self.logic_rate,
                self.logic_rate,
                1024,
                512,
                0,
                0,
                0,
                0,
            )
        if command == Command.DEVICE_STATUS:
            # Arming logic takes the acquisition hardware; stopping hands it back.
            owner = 2 if self.logic_state else 0
            return struct.pack(
                "<BIBIIIBIIIIBIIII",
                owner,
                0,
                self.state,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                self.logic_state,
                0,
                0,
                0,
                0,
            )
        return b""

    def close(self):
        self.closed = True


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def wait_for(signal, action, match=None):
    """Wait for an emission, optionally one that satisfies ``match``.

    Every command reports several subsystems, so emissions from the previous command
    can still be in flight. Waiting for the first arrival would sometimes read that
    stale one; matching on the expected condition ignores it.
    """
    result = []
    loop = QEventLoop()

    def receive(*args):
        if match is not None and not match(*args):
            return
        result.append(args)
        loop.quit()

    signal.connect(receive)
    QTimer.singleShot(2000, loop.quit)
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
        name, capabilities, statuses = wait_for(
            session.connected, lambda: session.connect_device("test")
        )
        assert name == "STM32-MSI"
        assert capabilities["max_hz"] == 1000
        assert capabilities["channels"] == 2
        assert [status.channel for status in statuses] == [0, 1]
        assert all(status.state == 1 for status in statuses)
        assert worker_threads[0] != app.thread()

        (statuses,) = wait_for(session.status_changed, session.start)
        assert all(status.state == 2 for status in statuses)
        (statuses,) = wait_for(session.status_changed, session.stop)
        assert all(status.state == 1 for status in statuses)
        configurations = [
            (0, "triangle", 250, 75, 50, 0, None),
            (1, "sawtooth", 500, 60, 50, 90, None),
        ]
        (statuses,) = wait_for(session.status_changed, lambda: session.start(configurations))
        assert [item.waveform for item in statuses] == [1, 3]
        assert [item.requested_hz for item in statuses] == [250, 500]
        (statuses,) = wait_for(session.status_changed, session.stop)
        assert all(status.state == 1 for status in statuses)
        (statuses,) = wait_for(
            session.status_changed,
            lambda: session.configure(1, "sawtooth", 123.456, 60, 50, 90),
        )
        status = statuses[1]
        assert status.channel == 1
        assert status.waveform == 3
        assert status.requested_hz == pytest.approx(123.456)

        (logic,) = wait_for(
            session.logic_status_changed,
            lambda: session.arm_logic(LogicConfig(sample_rate=2_000_000)),
            match=lambda status: status.state == 1,
        )
        assert logic.sample_rate == 2_000_000

        # The unified snapshot must agree with the per-subsystem read.
        (device,) = wait_for(
            session.device_status_changed,
            session.refresh,
            match=lambda status: status.logic_state == 1,
        )
        assert device.owner_name == "logic"

        (logic,) = wait_for(
            session.logic_status_changed,
            session.stop_logic,
            match=lambda status: status.state == 0,
        )
        assert logic.sample_rate == 2_000_000
    finally:
        session.shutdown()
