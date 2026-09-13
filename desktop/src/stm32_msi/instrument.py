"""AWG controls and device status."""

import struct
from dataclasses import dataclass

from .protocol import Command
from .transport import Transport

WAVEFORMS = {
    "sine": 0,
    "triangle": 1,
    "square": 2,
    "sawtooth": 3,
    "dc": 4,
    "arbitrary": 5,
}
MIN_FREQUENCY_MILLIHZ = 1000
MAX_FREQUENCY_MILLIHZ = 20_000_000
MAX_ARBITRARY_SAMPLES = 256
LOGIC_CHANNELS = 8
LOGIC_RATES = (1_000_000, 2_000_000, 5_000_000, 10_000_000)
LOGIC_MAX_SAMPLES = 4096
LOGIC_READ_MAX = 48
TIMER_CLOCK_HZ = 168_000_000
PROBE_CLOCK_HZ = 84_000_000
PROBE_MAX_HZ = PROBE_CLOCK_HZ // 2
ACQUISITION_OWNERS = ("none", "scope", "logic")
TASK_NAMES = ("awg", "acquire", "control", "status")


@dataclass(frozen=True)
class Status:
    state: int
    channel: int
    waveform: int
    frequency_millihz: int
    actual_millihz: int
    amplitude_permille: int = 750
    offset_permille: int = 500
    phase_decidegrees: int = 0
    underruns: int = 0
    dma_errors: int = 0
    refill_misses: int = 0
    arbitrary_length: int = 0

    @property
    def requested_hz(self) -> float:
        return self.frequency_millihz / 1000


@dataclass(frozen=True)
class ScopeConfig:
    sample_rate: int = 100_000
    sample_count: int = 512
    trigger_channel: int = 0
    trigger_edge: int = 0
    trigger_level: int = 2048
    pretrigger_permille: int = 500


@dataclass(frozen=True)
class ScopeStatus:
    state: int
    sample_rate: int
    sample_count: int
    trigger_index: int
    capture_id: int
    trigger_misses: int
    overruns: int
    dma_errors: int


@dataclass(frozen=True)
class Capture:
    status: ScopeStatus
    channel_1: tuple[int, ...]
    channel_2: tuple[int, ...]


@dataclass(frozen=True)
class LogicConfig:
    sample_rate: int = 1_000_000
    sample_count: int = 1024
    trigger_mode: int = 0
    trigger_channel: int = 0
    trigger_mask: int = 0
    trigger_value: int = 0
    pretrigger_permille: int = 500


@dataclass(frozen=True)
class LogicStatus:
    state: int
    sample_rate: int
    actual_rate: int
    sample_count: int
    trigger_index: int
    capture_id: int
    trigger_misses: int
    overruns: int
    dma_errors: int


@dataclass(frozen=True)
class LogicCapture:
    status: LogicStatus
    samples: tuple[int, ...]


def logic_actual_rate(sample_rate: int) -> int:
    """The timer divides a fixed clock, so not every requested rate is reachable."""
    if sample_rate <= 0:
        raise ValueError("Sample rate must be positive")
    divider = max(1, round(TIMER_CLOCK_HZ / sample_rate))
    return TIMER_CLOCK_HZ // divider


@dataclass(frozen=True)
class DeviceStatus:
    """One snapshot of every subsystem, so a poll costs a single round trip."""

    owner: int
    conflicts: int
    awg_state: int
    underruns: int
    awg_dma_errors: int
    refill_misses: int
    scope_state: int
    scope_capture_id: int
    scope_trigger_misses: int
    scope_overruns: int
    scope_dma_errors: int
    logic_state: int
    logic_capture_id: int
    logic_trigger_misses: int
    logic_overruns: int
    logic_dma_errors: int

    @property
    def owner_name(self) -> str:
        return ACQUISITION_OWNERS[self.owner] if self.owner < len(ACQUISITION_OWNERS) else "?"

    def scope_status(self, config: ScopeConfig) -> ScopeStatus:
        return ScopeStatus(
            self.scope_state,
            config.sample_rate,
            config.sample_count,
            round(config.sample_count * config.pretrigger_permille / 1000),
            self.scope_capture_id,
            self.scope_trigger_misses,
            self.scope_overruns,
            self.scope_dma_errors,
        )

    def logic_status(self, config: LogicConfig) -> LogicStatus:
        return LogicStatus(
            self.logic_state,
            config.sample_rate,
            logic_actual_rate(config.sample_rate),
            config.sample_count,
            round(config.sample_count * config.pretrigger_permille / 1000),
            self.logic_capture_id,
            self.logic_trigger_misses,
            self.logic_overruns,
            self.logic_dma_errors,
        )


@dataclass(frozen=True)
class ProbeStatus:
    """The TIM3 reference square wave on PC6.

    The DAC cannot produce an edge faster than its 2.5 us update period, which is far
    too slow to reach the logic analyzer's limit. This output can, so it is what the
    minimum-pulse and lossless-rate checks are driven from.
    """

    enabled: bool
    requested_hz: int
    actual_hz: int
    duty_permille: int
    prescaler: int
    reload: int

    @property
    def half_period_ns(self) -> float | None:
        if not self.enabled or not self.actual_hz:
            return None
        return 5e8 / self.actual_hz


@dataclass(frozen=True)
class RtosStatus:
    stack_headroom: tuple[int, ...]
    heap_free: int
    heap_low_water: int

    @property
    def named_headroom(self) -> dict:
        return dict(zip(TASK_NAMES, self.stack_headroom, strict=False))


class Instrument:
    def __init__(self, transport: Transport):
        self.transport = transport

    def hello(self) -> str:
        return self.transport.request(Command.HELLO).decode("ascii")

    def capabilities(self) -> dict:
        channels, waveforms, minimum, maximum, samples = struct.unpack(
            "<BBIIB", self.transport.request(Command.CAPABILITIES)
        )
        return dict(
            channels=channels,
            waveforms=waveforms,
            min_hz=minimum,
            max_hz=maximum,
            samples=samples,
        )

    def status(self) -> Status:
        state, waveform, requested_hz, actual, underruns, dma_errors = struct.unpack(
            "<BBIIII", self.transport.request(Command.STATUS)
        )
        return Status(
            state,
            0,
            waveform,
            requested_hz * 1000,
            actual,
            underruns=underruns,
            dma_errors=dma_errors,
        )

    def channel_status(self, channel: int) -> Status:
        if channel not in range(2):
            raise ValueError("Channel must be 0 or 1")
        values = struct.unpack(
            "<BBBIIHHHIIIH",
            self.transport.request(Command.AWG_STATUS_EXT, bytes([channel])),
        )
        return Status(*values)

    def configure(self, waveform: str, frequency_hz: int) -> None:
        if waveform not in ("sine", "triangle", "square") or not 1 <= frequency_hz <= 20_000:
            raise ValueError("Expected sine, triangle or square at 1..20000 Hz")
        self.transport.request(
            Command.AWG_CONFIG, struct.pack("<BI", WAVEFORMS[waveform], frequency_hz)
        )

    def configure_channel(
        self,
        channel: int,
        waveform: str,
        frequency_hz: float,
        amplitude_percent: float,
        offset_percent: float,
        phase_degrees: float,
    ) -> None:
        if channel not in range(2) or waveform not in WAVEFORMS:
            raise ValueError("Invalid AWG channel or waveform")
        frequency = round(frequency_hz * 1000)
        amplitude = round(amplitude_percent * 10)
        offset = round(offset_percent * 10)
        phase = round(phase_degrees * 10)
        if not MIN_FREQUENCY_MILLIHZ <= frequency <= MAX_FREQUENCY_MILLIHZ:
            raise ValueError("Frequency must be between 1 and 20000 Hz")
        if not 0 <= amplitude <= 1000 or not 0 <= offset <= 1000 or not 0 <= phase < 3600:
            raise ValueError("Amplitude, offset or phase is outside its range")
        span = min((4096 * amplitude + 500) // 1000, 4095)
        center = min((4096 * offset + 500) // 1000, 4095)
        lower = (span + 1) // 2
        if center < lower or center + span - lower > 4095:
            raise ValueError("Amplitude and offset would exceed the DAC range")
        payload = struct.pack(
            "<BBIHHH", channel, WAVEFORMS[waveform], frequency, amplitude, offset, phase
        )
        self.transport.request(Command.AWG_CONFIG_EXT, payload)

    def upload_arbitrary(self, channel: int, samples: list[int]) -> None:
        if channel not in range(2) or not 2 <= len(samples) <= MAX_ARBITRARY_SAMPLES:
            raise ValueError("Arbitrary tables require 2..256 samples")
        if any(not isinstance(sample, int) or not 0 <= sample <= 4095 for sample in samples):
            raise ValueError("Arbitrary samples must be integer DAC codes from 0 to 4095")
        for offset in range(0, len(samples), 14):
            chunk = samples[offset : offset + 14]
            payload = struct.pack("<BHB", channel, offset, len(chunk)) + struct.pack(
                f"<{len(chunk)}H", *chunk
            )
            self.transport.request(Command.AWG_UPLOAD, payload)
        self.transport.request(Command.AWG_COMMIT, struct.pack("<BH", channel, len(samples)))

    def start(self) -> None:
        self.transport.request(Command.AWG_START)

    def stop(self) -> None:
        self.transport.request(Command.AWG_STOP)

    def configure_scope(self, config: ScopeConfig) -> None:
        if config.sample_rate not in (100_000, 500_000, 1_000_000):
            raise ValueError("Sample rate must be 100, 500 or 1000 kS/s")
        if not 64 <= config.sample_count <= 2048:
            raise ValueError("Sample count must be between 64 and 2048")
        if config.trigger_channel not in (0, 1) or config.trigger_edge not in (0, 1, 2):
            raise ValueError("Invalid trigger source or edge")
        if not 0 <= config.trigger_level <= 4095 or not 0 <= config.pretrigger_permille <= 900:
            raise ValueError("Trigger level or position is outside its range")
        self.transport.request(
            Command.SCOPE_CONFIG,
            struct.pack(
                "<IHBBHH",
                config.sample_rate,
                config.sample_count,
                config.trigger_channel,
                config.trigger_edge,
                config.trigger_level,
                config.pretrigger_permille,
            ),
        )

    def arm_scope(self) -> None:
        self.transport.request(Command.SCOPE_ARM)

    def stop_scope(self) -> None:
        self.transport.request(Command.SCOPE_STOP)

    def scope_status(self) -> ScopeStatus:
        return ScopeStatus(
            *struct.unpack("<BIHHIIII", self.transport.request(Command.SCOPE_STATUS))
        )

    def read_capture(self, status: ScopeStatus) -> Capture:
        first, second = [], []
        for offset in range(0, status.sample_count, 12):
            count = min(12, status.sample_count - offset)
            payload = self.transport.request(
                Command.SCOPE_READ, struct.pack("<IHB", status.capture_id, offset, count)
            )
            capture_id, returned_offset, returned_count = struct.unpack_from("<IHB", payload)
            if (capture_id, returned_offset, returned_count) != (status.capture_id, offset, count):
                raise RuntimeError("Capture chunk does not match the request")
            packed = struct.unpack_from(f"<{count}I", payload, 7)
            first.extend(value & 0xFFFF for value in packed)
            second.extend(value >> 16 for value in packed)
        return Capture(status, tuple(first), tuple(second))

    def configure_logic(self, config: LogicConfig) -> None:
        if config.sample_rate not in LOGIC_RATES:
            raise ValueError("Sample rate must be 1, 2, 5 or 10 MS/s")
        if not 64 <= config.sample_count <= LOGIC_MAX_SAMPLES:
            raise ValueError(f"Sample count must be between 64 and {LOGIC_MAX_SAMPLES}")
        if config.trigger_mode not in range(4):
            raise ValueError("Invalid trigger mode")
        if config.trigger_channel not in range(LOGIC_CHANNELS):
            raise ValueError(f"Trigger channel must be 0..{LOGIC_CHANNELS - 1}")
        if not 0 <= config.trigger_mask <= 255 or not 0 <= config.trigger_value <= 255:
            raise ValueError("Trigger mask and value must be single bytes")
        if config.trigger_mode == 3 and config.trigger_mask == 0:
            raise ValueError("A pattern trigger needs at least one selected channel")
        if not 0 <= config.pretrigger_permille <= 900:
            raise ValueError("Trigger position is outside its range")
        self.transport.request(
            Command.LOGIC_CONFIG,
            struct.pack(
                "<IHBBBBH",
                config.sample_rate,
                config.sample_count,
                config.trigger_mode,
                config.trigger_channel,
                config.trigger_mask,
                config.trigger_value,
                config.pretrigger_permille,
            ),
        )

    def arm_logic(self) -> None:
        self.transport.request(Command.LOGIC_ARM)

    def stop_logic(self) -> None:
        self.transport.request(Command.LOGIC_STOP)

    def logic_status(self) -> LogicStatus:
        return LogicStatus(
            *struct.unpack("<BIIHHIIII", self.transport.request(Command.LOGIC_STATUS))
        )

    def device_status(self) -> DeviceStatus:
        return DeviceStatus(
            *struct.unpack("<BIBIIIBIIIIBIIII", self.transport.request(Command.DEVICE_STATUS))
        )

    def rtos_status(self) -> RtosStatus:
        payload = self.transport.request(Command.RTOS_STATUS)
        count = payload[0]
        headroom = struct.unpack_from(f"<{count}I", payload, 1)
        heap_free, heap_low = struct.unpack_from("<II", payload, 1 + 4 * count)
        return RtosStatus(headroom, heap_free, heap_low)

    def configure_probe(self, frequency_hz: int, duty_percent: float = 50.0) -> None:
        """Set the reference output. A frequency of zero turns it off."""
        if frequency_hz and not 1 <= frequency_hz <= PROBE_MAX_HZ:
            raise ValueError(f"Probe frequency must be 1..{PROBE_MAX_HZ} Hz")
        duty = round(duty_percent * 10)
        if frequency_hz and not 1 <= duty <= 999:
            raise ValueError("Probe duty must leave a real edge, 0.1..99.9 %")
        self.transport.request(Command.PROBE_CONFIG, struct.pack("<IH", frequency_hz, duty))

    def probe_status(self) -> ProbeStatus:
        enabled, requested, actual, duty, prescaler, reload = struct.unpack(
            "<BIIHHH", self.transport.request(Command.PROBE_STATUS)
        )
        return ProbeStatus(bool(enabled), requested, actual, duty, prescaler, reload)

    def read_logic_capture(self, status: LogicStatus) -> LogicCapture:
        samples: list[int] = []
        for offset in range(0, status.sample_count, LOGIC_READ_MAX):
            count = min(LOGIC_READ_MAX, status.sample_count - offset)
            payload = self.transport.request(
                Command.LOGIC_READ, struct.pack("<IHB", status.capture_id, offset, count)
            )
            capture_id, returned_offset, returned_count = struct.unpack_from("<IHB", payload)
            if (capture_id, returned_offset, returned_count) != (status.capture_id, offset, count):
                raise RuntimeError("Capture chunk does not match the request")
            samples.extend(payload[7 : 7 + count])
        return LogicCapture(status, tuple(samples))
