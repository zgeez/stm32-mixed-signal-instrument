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
            elif request.command == Command.AWG_STATUS_EXT:
                payload += struct.pack(
                    "<BBBIIHHHIIIH",
                    1,
                    request.payload[0],
                    3,
                    123456,
                    123455,
                    600,
                    500,
                    900,
                    1,
                    2,
                    3,
                    17,
                )
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
    for waveform, hz in [("bad", 100), ("sine", 0), ("sine", 20_001)]:
        with pytest.raises(ValueError):
            device.configure(waveform, hz)
    assert not transport.serial.requests
    device.configure("triangle", 500)
    assert transport.serial.requests[-1].payload == struct.pack("<BI", 1, 500)


def test_extended_configuration_status_and_upload(transport):
    device = Instrument(transport)
    device.configure_channel(1, "sawtooth", 123.456, 60, 50, 90)
    request = transport.serial.requests[-1]
    assert request.command == Command.AWG_CONFIG_EXT
    assert request.payload == struct.pack("<BBIHHH", 1, 3, 123456, 600, 500, 900)

    status = device.channel_status(1)
    assert status.channel == 1
    assert status.requested_hz == pytest.approx(123.456)
    assert status.refill_misses == 3
    assert status.arbitrary_length == 17

    samples = list(range(30))
    device.upload_arbitrary(0, samples)
    uploads = [frame for frame in transport.serial.requests if frame.command == Command.AWG_UPLOAD]
    assert [frame.payload[3] for frame in uploads] == [14, 14, 2]
    assert transport.serial.requests[-1].command == Command.AWG_COMMIT


@pytest.mark.parametrize(
    "settings",
    [
        (2, "sine", 100, 75, 50, 0),
        (0, "bad", 100, 75, 50, 0),
        (0, "sine", 0.5, 75, 50, 0),
        (0, "sine", 100, 100, 25, 0),
        (0, "sine", 100, 75, 50, 360),
    ],
)
def test_extended_configuration_validation(transport, settings):
    with pytest.raises(ValueError):
        Instrument(transport).configure_channel(*settings)
