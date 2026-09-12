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
