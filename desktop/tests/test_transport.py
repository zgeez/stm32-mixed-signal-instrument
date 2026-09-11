import struct

import pytest

from stm32_msi.instrument import Instrument
from stm32_msi.protocol import Command, Frame, decode, encode
from stm32_msi.transport import DeviceError, Transport


class SerialStub:
    def __init__(self, *_args, **_kwargs):
        self.incoming = bytearray()
        self.closed = False
        self.reply_status = 0
        self.reply_version = 1
        self.silent = False
        self.short_write = False
        self.requests = []

    def reset_input_buffer(self):
        self.incoming.clear()

    def write(self, wire):
        if wire == b"\0":
            return 1
        request = decode(wire[:-1])
        self.requests.append(request)
        if self.short_write:
            return len(wire) - 1
        if not self.silent:
            payload = bytes([self.reply_status])
            if request.command == Command.STATUS:
                payload += struct.pack("<BBIIII", 2, 0, 1000, 1000000, 0, 0)
            else:
                payload += b"STM32-MSI"
            stale = Frame(request.command | 0x80, (request.sequence - 1) & 0xFFFF, b"\0old")
            reply = Frame(request.command | 0x80, request.sequence, payload, self.reply_version)
            self.incoming.extend(encode(stale) + encode(reply))
        return len(wire)

    def read(self, _size):
        data = bytes(self.incoming[:1])
        del self.incoming[:1]
        return data

    def close(self):
        self.closed = True


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr("stm32_msi.transport.serial.Serial", SerialStub)
    with Transport("test", timeout=0.01) as connection:
        yield connection


def test_fragmented_reply_and_stale_sequence(transport):
    transport.sequence = 65535
    assert Instrument(transport).hello() == "STM32-MSI"
    assert transport.sequence == 0
    assert Instrument(transport).status().actual_millihz == 1000000


def test_device_error_keeps_connection(transport):
    transport.serial.reply_status = 2
    with pytest.raises(DeviceError, match="busy"):
        transport.request(Command.AWG_START)
    assert not transport.serial.closed


@pytest.mark.parametrize("mode", ["silent", "short_write", "reply_version"])
def test_failed_exchange_closes_connection(transport, mode):
    setattr(transport.serial, mode, 2 if mode == "reply_version" else True)
    with pytest.raises(OSError):
        transport.request(Command.HELLO)
    assert transport.serial.closed


def test_configuration_validation_and_encoding(transport):
    device = Instrument(transport)
    for waveform, hz in [("bad", 100), ("sine", 0), ("sine", 1001)]:
        with pytest.raises(ValueError):
            device.configure(waveform, hz)
    assert not transport.serial.requests
    device.configure("triangle", 500)
    assert transport.serial.requests[-1].payload == struct.pack("<BI", 1, 500)
