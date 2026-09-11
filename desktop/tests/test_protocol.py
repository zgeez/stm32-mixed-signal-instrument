from pathlib import Path

import pytest

from stm32_msi.protocol import Decoder, Frame, decode, encode


def vectors():
    for line in (Path(__file__).parents[2] / "protocol/vectors.txt").read_text().splitlines():
        version, command, sequence, payload, wire = line.split()
        yield (
            Frame(
                int(command),
                int(sequence),
                b"" if payload == "-" else bytes.fromhex(payload),
                int(version),
            ),
            bytes.fromhex(wire),
        )


@pytest.mark.parametrize("frame,wire", list(vectors()))
def test_shared_vectors(frame, wire):
    assert encode(frame) == wire
    assert decode(wire[:-1]) == frame
    for split in range(len(wire)):
        decoder = Decoder()
        assert decoder.feed(wire[:split]) + decoder.feed(wire[split:]) == [frame]


def test_recovery_and_combined_frames():
    frame = Frame(6, 10)
    wire = encode(frame)
    decoder = Decoder()
    assert decoder.feed(b"\xff" * 100 + b"\0\xff\x01\0" + wire * 3) == [frame] * 3
    assert len(decoder.buffer) == 0


@pytest.mark.parametrize("size", range(33))
def test_all_payload_sizes(size):
    for value in (0, 1, 255):
        frame = Frame(3, 65535, bytes([value]) * size)
        assert decode(encode(frame)[:-1]) == frame


def test_invalid_lengths():
    with pytest.raises(ValueError):
        encode(Frame(1, 0, bytes(33)))
    for data in (b"", b"\xff", b"\x01\x01", bytes(39)):
        with pytest.raises(ValueError):
            decode(data)
