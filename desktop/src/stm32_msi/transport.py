"""Synchronous CDC requests; one outstanding request per connection."""

import secrets
import time

import serial

from .protocol import VERSION, Decoder, Frame, encode


class DeviceError(RuntimeError):
    def __init__(self, status: int):
        names = {
            1: "invalid request",
            2: "busy",
            3: "hardware fault",
            4: "unsupported version",
            5: "unknown command",
        }
        super().__init__(names.get(status, f"unknown status {status}"))
        self.status = status


class Transport:
    def __init__(self, port: str, timeout: float = 2.0):
        if timeout <= 0:
            raise ValueError("Timeout must be positive")
        self.timeout = timeout
        self.serial = serial.Serial(port, 115200, timeout=0.05, write_timeout=timeout)
        self.decoder = Decoder()
        self.sequence = secrets.randbelow(65536)
        try:
            self.serial.reset_input_buffer()
            if self.serial.write(b"\0") != 1:
                raise OSError("Incomplete session delimiter")
        except (OSError, serial.SerialException):
            self.close()
            raise

    def close(self) -> None:
        self.serial.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def request(self, command: int, payload: bytes = b"") -> bytes:
        self.sequence = (self.sequence + 1) & 0xFFFF
        packet = encode(Frame(command, self.sequence, payload))
        try:
            if self.serial.write(packet) != len(packet):
                raise OSError("Incomplete command write")
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                available = self.serial.in_waiting
                for frame in self.decoder.feed(self.serial.read(available or 1)):
                    if frame.sequence != self.sequence or frame.command != (command | 0x80):
                        continue
                    if frame.version != VERSION or not frame.payload:
                        raise OSError("Invalid protocol reply")
                    if frame.payload[0]:
                        raise DeviceError(frame.payload[0])
                    return frame.payload[1:]
            raise TimeoutError(
                "Reply timed out; command outcome is unknown. Reconnect and query status."
            )
        except (OSError, serial.SerialException):
            self.close()
            raise
