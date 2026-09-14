import struct

import pytest

from stm32_msi.instrument import (
    Instrument,
    LogicConfig,
    LogicStatus,
    ScopeConfig,
    ScopeStatus,
    logic_actual_rate,
)
from stm32_msi.protocol import Command


class ScopeTransport:
    def __init__(self):
        self.read_offsets = []

    def request(self, command, payload=b""):
        if command == Command.SCOPE_STATUS:
            return struct.pack("<BIHHIIIIH", 2, 500_000, 13, 6, 7, 1, 2, 3, 40)
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
    assert status == ScopeStatus(2, 500_000, 13, 6, 7, 1, 2, 3, 40)

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
                "<BIIHHIIIIH", 2, 5_000_000, 4_941_176, self.sample_count, 25, 4, 1, 2, 3, 60
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
    assert status == LogicStatus(2, 5_000_000, 4_941_176, 100, 25, 4, 1, 2, 3, 60)

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


class UnifiedTransport:
    def __init__(self, owner=2, conflicts=3):
        self.owner = owner
        self.conflicts = conflicts
        self.commands = []

    def request(self, command, payload=b""):
        self.commands.append(command)
        if command == Command.DEVICE_STATUS:
            return struct.pack(
                "<BIBIIIBIIIIBIIII",
                self.owner,
                self.conflicts,
                2,
                10,
                11,
                12,  # AWG
                2,
                20,
                21,
                22,
                23,  # scope
                1,
                30,
                31,
                32,
                33,  # logic
            )
        if command == Command.RTOS_STATUS:
            return struct.pack("<B4III", 4, 640, 720, 1200, 256, 8192, 6144)
        return b""


def test_device_status_is_one_round_trip():
    transport = UnifiedTransport()
    status = Instrument(transport).device_status()
    assert transport.commands == [Command.DEVICE_STATUS]
    assert status.owner_name == "logic"
    assert status.conflicts == 3
    assert (status.awg_state, status.underruns, status.refill_misses) == (2, 10, 12)
    assert (status.scope_state, status.scope_capture_id) == (2, 20)
    assert (status.logic_state, status.logic_overruns) == (1, 32)


def test_snapshot_rebuilds_panel_status_from_the_sent_configuration():
    status = Instrument(UnifiedTransport()).device_status()
    scope = status.scope_status(ScopeConfig(500_000, 512, pretrigger_permille=250))
    assert (scope.state, scope.sample_rate, scope.trigger_index) == (2, 500_000, 128)
    assert scope.capture_id == 20

    logic = status.logic_status(LogicConfig(5_000_000, 1024, pretrigger_permille=500))
    assert logic.sample_rate == 5_000_000
    # The device reports what the timer can actually produce, not the request.
    assert logic.actual_rate == 168_000_000 // 34
    assert logic.trigger_index == 512


def test_unknown_owner_value_does_not_crash_the_label():
    assert Instrument(UnifiedTransport(owner=9)).device_status().owner_name == "?"


def test_rtos_status_reports_headroom_and_heap():
    status = Instrument(UnifiedTransport()).rtos_status()
    assert status.stack_headroom == (640, 720, 1200, 256)
    assert status.named_headroom == {"awg": 640, "acquire": 720, "control": 1200, "status": 256}
    assert (status.heap_free, status.heap_low_water) == (8192, 6144)


class ProbeTransport:
    def __init__(self):
        self.sent = None
        self.enabled = False

    def request(self, command, payload=b""):
        if command == Command.PROBE_CONFIG:
            self.sent = payload
            frequency = struct.unpack_from("<I", payload)[0]
            self.enabled = frequency != 0
            return b""
        if command == Command.PROBE_STATUS:
            # 84 MHz over 84 ticks is exactly 1 MHz.
            return struct.pack("<BIIHHH", int(self.enabled), 1_000_000, 1_000_000, 500, 0, 83)
        return b""


def test_probe_configuration_is_packed_and_read_back():
    transport = ProbeTransport()
    instrument = Instrument(transport)
    instrument.configure_probe(1_000_000, 50.0)
    assert transport.sent == struct.pack("<IH", 1_000_000, 500)

    status = instrument.probe_status()
    assert status.enabled and status.actual_hz == 1_000_000
    assert status.reload == 83
    # Half a microsecond, the useful figure when choosing a sample rate.
    assert status.half_period_ns == pytest.approx(500.0)


def test_probe_zero_frequency_disables_without_a_duty_check():
    transport = ProbeTransport()
    Instrument(transport).configure_probe(0)
    assert transport.sent == struct.pack("<IH", 0, 500)
    assert not transport.enabled


def test_disabled_probe_reports_no_half_period():
    transport = ProbeTransport()
    transport.enabled = False
    assert Instrument(transport).probe_status().half_period_ns is None


@pytest.mark.parametrize(
    "frequency,duty",
    ((42_000_001, 50.0), (-1, 50.0), (1_000_000, 0.0), (1_000_000, 100.0)),
)
def test_probe_rejects_settings_that_cannot_produce_an_edge(frequency, duty):
    with pytest.raises(ValueError):
        Instrument(ProbeTransport()).configure_probe(frequency, duty)
