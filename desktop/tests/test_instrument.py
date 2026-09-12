import struct

from stm32_msi.instrument import Instrument, ScopeStatus
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
