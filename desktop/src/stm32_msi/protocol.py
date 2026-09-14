"""Version 1 command framing over a CDC byte stream."""

import struct
from dataclasses import dataclass
from enum import IntEnum

VERSION = 1
MAX_PAYLOAD = 57
MAX_ENCODED = 63


class Command(IntEnum):
    HELLO = 1
    CAPABILITIES = 2
    AWG_CONFIG = 3
    AWG_START = 4
    AWG_STOP = 5
    STATUS = 6
    AWG_CONFIG_EXT = 7
    AWG_STATUS_EXT = 8
    AWG_UPLOAD = 9
    AWG_COMMIT = 10
    SCOPE_CONFIG = 11
    SCOPE_ARM = 12
    SCOPE_STOP = 13
    SCOPE_STATUS = 14
    SCOPE_READ = 15
    LOGIC_CONFIG = 16
    LOGIC_ARM = 17
    LOGIC_STOP = 18
    LOGIC_STATUS = 19
    LOGIC_READ = 20
    DEVICE_STATUS = 21
    RTOS_STATUS = 22
    PROBE_CONFIG = 23
    PROBE_STATUS = 24
    MIXED_ARM = 25
    MIXED_STOP = 26
    MIXED_STATUS = 27


@dataclass(frozen=True)
class Frame:
    command: int
    sequence: int
    payload: bytes = b""
    version: int = VERSION


def encode(frame: Frame) -> bytes:
    if len(frame.payload) > MAX_PAYLOAD:
        raise ValueError(f"Payload exceeds {MAX_PAYLOAD} bytes")
    raw = struct.pack("<BBHB", frame.version, frame.command, frame.sequence, len(frame.payload))
    out = bytearray(b"\0")
    code_at, code = 0, 1
    for byte in raw + frame.payload:
        if byte == 0:
            out[code_at] = code
            code_at, code = len(out), 1
            out.append(0)
        else:
            out.append(byte)
            code += 1
    out[code_at] = code
    out.append(0)
    return bytes(out)


def decode(encoded: bytes) -> Frame:
    if not 1 <= len(encoded) <= MAX_ENCODED or 0 in encoded:
        raise ValueError("Invalid encoded frame")
    raw = bytearray()
    at = 0
    while at < len(encoded):
        code = encoded[at]
        at += 1
        if at + code - 1 > len(encoded):
            raise ValueError("Truncated COBS block")
        raw.extend(encoded[at : at + code - 1])
        at += code - 1
        if code != 255 and at < len(encoded):
            raw.append(0)
    if len(raw) < 5 or raw[4] > MAX_PAYLOAD or len(raw) != 5 + raw[4]:
        raise ValueError("Invalid payload length")
    version, command, sequence, _ = struct.unpack_from("<BBHB", raw)
    return Frame(command, sequence, bytes(raw[5:]), version)


class Decoder:
    def __init__(self):
        self.buffer = bytearray()
        self.discard = False

    def feed(self, data: bytes) -> list[Frame]:
        frames = []
        for byte in data:
            if byte:
                if len(self.buffer) < MAX_ENCODED and not self.discard:
                    self.buffer.append(byte)
                else:
                    self.discard = True
            else:
                if self.buffer and not self.discard:
                    try:
                        frames.append(decode(bytes(self.buffer)))
                    except ValueError:
                        pass
                self.buffer.clear()
                self.discard = False
        return frames
