"""AWG controls and device status."""

import struct
from dataclasses import dataclass

from .protocol import Command
from .transport import Transport

WAVEFORMS = {"sine": 0, "triangle": 1, "square": 2}


@dataclass(frozen=True)
class Status:
    state: int
    waveform: int
    requested_hz: int
    actual_millihz: int
    underruns: int
    dma_errors: int


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
            channels=channels, waveforms=waveforms, min_hz=minimum, max_hz=maximum, samples=samples
        )

    def status(self) -> Status:
        return Status(*struct.unpack("<BBIIII", self.transport.request(Command.STATUS)))

    def configure(self, waveform: str, frequency_hz: int) -> None:
        if waveform not in WAVEFORMS or not 1 <= frequency_hz <= 1000:
            raise ValueError("Expected sine, triangle or square at 1..1000 Hz")
        self.transport.request(
            Command.AWG_CONFIG, struct.pack("<BI", WAVEFORMS[waveform], frequency_hz)
        )

    def start(self) -> None:
        self.transport.request(Command.AWG_START)

    def stop(self) -> None:
        self.transport.request(Command.AWG_STOP)
