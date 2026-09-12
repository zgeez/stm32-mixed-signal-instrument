"""Logic capture analysis and protocol decoding."""

from dataclasses import dataclass

import numpy as np

CHANNELS = 8


@dataclass(frozen=True)
class Measurements:
    transitions: int
    duty: float
    shortest_high: float | None
    shortest_low: float | None
    period: float | None
    frequency: float | None
    jitter: float | None


@dataclass(frozen=True)
class Symbol:
    start: int
    end: int
    text: str
    value: int | None = None
    error: str | None = None


def channel_bits(samples, channel: int) -> np.ndarray:
    """Extract one channel from packed capture bytes as a 0/1 array."""
    if channel not in range(CHANNELS):
        raise ValueError(f"Channel must be 0..{CHANNELS - 1}")
    values = np.asarray(samples, dtype=np.uint8)
    if values.size == 0:
        raise ValueError("A capture is required")
    return ((values >> channel) & 1).astype(np.int8)


def find_edges(bits) -> tuple[np.ndarray, np.ndarray]:
    """Return the indices of rising and falling transitions.

    An edge is reported at the first differing sample, so its true position lies
    somewhere in the preceding sample interval.
    """
    values = np.asarray(bits, dtype=np.int8)
    changes = np.flatnonzero(np.diff(values)) + 1
    return changes[values[changes] == 1], changes[values[changes] == 0]


def _bit_center(start: int, span: float, bit_index: int) -> int:
    """Sample each bit at its middle, which is the least sensitive to phase error."""
    return start + round(span * (0.5 + bit_index))


def _runs(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    boundaries = np.flatnonzero(np.diff(values)) + 1
    starts = np.concatenate(([0], boundaries))
    lengths = np.diff(np.concatenate((starts, [values.size])))
    return starts, lengths


def measure(samples, channel: int, sample_rate: float) -> Measurements:
    """Summarize one channel. Interior runs only, since edge runs are truncated."""
    if sample_rate <= 0:
        raise ValueError("A positive sample rate is required")
    bits = channel_bits(samples, channel)
    interval = 1.0 / sample_rate
    starts, lengths = _runs(bits)
    interior = lengths[1:-1] if starts.size > 2 else np.empty(0, dtype=int)
    levels = bits[starts][1:-1] if starts.size > 2 else np.empty(0, dtype=np.int8)
    highs, lows = interior[levels == 1], interior[levels == 0]
    rising, _ = find_edges(bits)
    period = frequency = jitter = None
    if rising.size >= 3:
        spacing = np.diff(rising).astype(float)
        period = float(np.mean(spacing)) * interval
        jitter = float(np.max(np.abs(spacing - np.mean(spacing)))) * interval
        if period > 0:
            frequency = 1.0 / period
    return Measurements(
        transitions=int(starts.size - 1),
        duty=float(np.mean(bits)),
        shortest_high=float(np.min(highs)) * interval if highs.size else None,
        shortest_low=float(np.min(lows)) * interval if lows.size else None,
        period=period,
        frequency=frequency,
        jitter=jitter,
    )


def decode_uart(
    samples,
    channel: int,
    sample_rate: float,
    baud: float,
    data_bits: int = 8,
    parity: str = "none",
    stop_bits: float = 1.0,
) -> list[Symbol]:
    """Decode idle-high asynchronous serial data sampled at ``sample_rate``."""
    if baud <= 0 or sample_rate <= 0:
        raise ValueError("Baud rate and sample rate must be positive")
    if not 5 <= data_bits <= 9:
        raise ValueError("Data bits must be 5..9")
    if parity not in ("none", "even", "odd"):
        raise ValueError("Parity must be none, even or odd")
    span = sample_rate / baud
    if span < 2:
        raise ValueError("Sampling is too slow to decode this baud rate")
    bits = channel_bits(samples, channel)
    parity_bits = 0 if parity == "none" else 1
    symbols: list[Symbol] = []
    at = 0
    while at < bits.size - 1:
        if bits[at] != 1 or bits[at + 1] != 0:
            at += 1
            continue
        start = at + 1
        stop_at = _bit_center(start, span, data_bits + parity_bits + 1)
        end = start + round(span * (1 + data_bits + parity_bits + stop_bits))
        if end > bits.size or stop_at >= bits.size:
            break
        value = 0
        for index in range(data_bits):
            value |= int(bits[_bit_center(start, span, index + 1)]) << index
        error = None
        if parity_bits:
            expected = bin(value).count("1") % 2
            received = int(bits[_bit_center(start, span, data_bits + 1)])
            if (expected if parity == "odd" else 1 - expected) == received:
                error = "parity"
        if bits[stop_at] != 1:
            error = "framing"
        text = f"0x{value:02X}" if error is None else f"0x{value:02X} {error}"
        symbols.append(Symbol(start, end, text, value, error))
        at = end - 1
    return symbols


def decode_spi(
    samples,
    clock: int,
    data: int,
    select: int | None = None,
    cpol: int = 0,
    cpha: int = 0,
    word_bits: int = 8,
    msb_first: bool = True,
) -> list[Symbol]:
    """Decode SPI words, treating ``select`` as active low when it is given."""
    if cpol not in (0, 1) or cpha not in (0, 1):
        raise ValueError("CPOL and CPHA must be 0 or 1")
    if not 4 <= word_bits <= 16:
        raise ValueError("Word length must be 4..16 bits")
    if clock == data or select in (clock, data):
        raise ValueError("Clock, data and select must be different channels")
    clock_bits = channel_bits(samples, clock)
    data_bits = channel_bits(samples, data)
    select_bits = channel_bits(samples, select) if select is not None else None
    rising, falling = find_edges(clock_bits)
    sampling = rising if cpol == cpha else falling
    symbols: list[Symbol] = []
    value, count, start = 0, 0, 0
    for index in sorted(sampling.tolist()):
        if select_bits is not None and select_bits[index] == 1:
            value, count = 0, 0
            continue
        if count == 0:
            start = index
        bit = int(data_bits[index])
        value = (value << 1) | bit if msb_first else value | (bit << count)
        count += 1
        if count == word_bits:
            symbols.append(Symbol(start, index + 1, f"0x{value:02X}", value))
            value, count = 0, 0
    return symbols


def decode_i2c(samples, scl: int, sda: int) -> list[Symbol]:
    """Decode I2C transfers, reporting start, address, data and stop events."""
    if scl == sda:
        raise ValueError("SCL and SDA must be different channels")
    clock = channel_bits(samples, scl)
    data = channel_bits(samples, sda)
    symbols: list[Symbol] = []
    value, count, start, expect_address = 0, 0, 0, False
    for index in range(1, clock.size):
        if clock[index] == 1 and clock[index - 1] == 1 and data[index] != data[index - 1]:
            symbols.append(Symbol(index, index + 1, "Start" if data[index] == 0 else "Stop"))
            value, count = 0, 0
            expect_address = data[index] == 0
            continue
        if clock[index] != 1 or clock[index - 1] != 0:
            continue
        if count == 0:
            start = index
        if count < 8:
            value = (value << 1) | int(data[index])
            count += 1
            continue
        acknowledged = data[index] == 0
        if expect_address:
            direction = "read" if value & 1 else "write"
            text = f"0x{value >> 1:02X} {direction}"
        else:
            text = f"0x{value:02X}"
        text += " ACK" if acknowledged else " NACK"
        symbols.append(Symbol(start, index + 1, text, value, None if acknowledged else "nack"))
        value, count, expect_address = 0, 0, False
    return symbols
