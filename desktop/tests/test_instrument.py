import struct

import pytest

from stm32_msi.instrument import (
    Instrument,
    LogicConfig,
    LogicStatus,
    ScopeStatus,
    logic_actual_rate,
)
from stm32_msi.protocol import Command


class ScopeTransport:
    def __init__(self):
        self.read_offsets = []

    def request(self, command, payload=b""):
        if command == Command.SCOPE_STATUS:
            return struct.pack("<BIHHIIII", 2, 500_000, 13, 6, 7, 1, 2, 3)
        if command == Command.SCOPE_READ:
            capture_id, offset, count = struct.unpack("<IHB", payload)
            self.read_offsets.append(offset)
            pairs = [sample | ((1000 + sample) << 16) for sample in range(offset, offset + count)]
            return struct.pack(f"<IHB{count}I", capture_id, offset, count, *pairs)
        return b""


def test_scope_status_and_chunked_capture():
    transport = ScopeTransport()
    instrument = Instrument(transport)
    status = instrument.scope_status()
    assert status == ScopeStatus(2, 500_000, 13, 6, 7, 1, 2, 3)

    capture = instrument.read_capture(status)
    assert transport.read_offsets == [0, 12]
    assert capture.channel_1 == tuple(range(13))
    assert capture.channel_2 == tuple(range(1000, 1013))


class LogicTransport:
    def __init__(self, sample_count=100):
        self.sample_count = sample_count
        self.read_offsets = []
        self.configured = None

    def request(self, command, payload=b""):
        if command == Command.LOGIC_CONFIG:
            self.configured = payload
            return b""
        if command == Command.LOGIC_STATUS:
            return struct.pack(
                "<BIIHHIIII", 2, 5_000_000, 4_941_176, self.sample_count, 25, 4, 1, 2, 3
            )
        if command == Command.LOGIC_READ:
            capture_id, offset, count = struct.unpack("<IHB", payload)
            self.read_offsets.append(offset)
            body = bytes((sample & 0xFF) for sample in range(offset, offset + count))
            return struct.pack("<IHB", capture_id, offset, count) + body
        return b""


def test_logic_status_and_chunked_capture():
    transport = LogicTransport()
    instrument = Instrument(transport)
    status = instrument.logic_status()
    assert status == LogicStatus(2, 5_000_000, 4_941_176, 100, 25, 4, 1, 2, 3)

    capture = instrument.read_logic_capture(status)
    assert transport.read_offsets == [0, 48, 96]
    assert capture.samples == tuple(range(100))


def test_logic_capture_rejects_a_mismatched_chunk():
    class Stale(LogicTransport):
        def request(self, command, payload=b""):
            if command == Command.LOGIC_READ:
                return struct.pack("<IHB", 99, 0, 1) + bytes(1)
            return super().request(command, payload)

    instrument = Instrument(Stale())
    with pytest.raises(RuntimeError):
        instrument.read_logic_capture(instrument.logic_status())


def test_logic_configuration_is_packed_little_endian():
    transport = LogicTransport()
    Instrument(transport).configure_logic(LogicConfig(2_000_000, 512, 3, 4, 0x0F, 0x0A, 250))
    assert transport.configured == struct.pack("<IHBBBBH", 2_000_000, 512, 3, 4, 0x0F, 0x0A, 250)


@pytest.mark.parametrize(
    "config",
    (
        LogicConfig(sample_rate=3_000_000),
        LogicConfig(sample_count=32),
        LogicConfig(sample_count=8192),
        LogicConfig(trigger_mode=4),
        LogicConfig(trigger_channel=8),
        LogicConfig(trigger_mask=256),
        LogicConfig(trigger_value=-1),
        LogicConfig(trigger_mode=3, trigger_mask=0),
        LogicConfig(pretrigger_permille=901),
    ),
)
def test_logic_configuration_rejects_invalid_settings(config):
    with pytest.raises(ValueError):
        Instrument(LogicTransport()).configure_logic(config)


def test_reachable_rates_report_the_divided_timer_clock():
    assert logic_actual_rate(1_000_000) == 1_000_000
    assert logic_actual_rate(2_000_000) == 2_000_000
    # 168 MHz does not divide evenly by 5 or 10 MHz, so the real rate is lower.
    assert logic_actual_rate(5_000_000) == 168_000_000 // 34
    assert logic_actual_rate(10_000_000) == 168_000_000 // 17
    with pytest.raises(ValueError):
        logic_actual_rate(0)
