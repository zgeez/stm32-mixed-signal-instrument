import numpy as np
import pytest

from stm32_msi.logic import (
    channel_bits,
    decode_i2c,
    decode_spi,
    decode_uart,
    find_edges,
    measure,
)

SCL, SDA = 0, 1


def square(high: int, low: int, cycles: int, channel: int = 0) -> list[int]:
    return ([1 << channel] * high + [0] * low) * cycles


def uart_stream(values, span: int, channel: int = 0, parity: str = "none") -> list[int]:
    bits = [1] * (2 * span)
    for value in values:
        frame = [0] + [(value >> index) & 1 for index in range(8)]
        if parity != "none":
            ones = bin(value).count("1") % 2
            frame.append(ones if parity == "even" else 1 - ones)
        frame.append(1)
        for bit in frame:
            bits += [bit] * span
    return [bit << channel for bit in bits + [1] * span]


def spi_stream(
    words, bits: int = 8, cpol: int = 0, cpha: int = 0, select: int | None = None
) -> list[int]:
    idle = (1 << SCL) if cpol else 0
    active = idle ^ (1 << SCL)
    chip_select = (1 << select) if select is not None else 0
    out = [idle | chip_select, idle | chip_select, idle]
    for word in words:
        for index in range(bits - 1, -1, -1):
            data = (1 << SDA) if (word >> index) & 1 else 0
            # CPHA=1 presents the bit on the leading edge and holds it to the trailing one.
            out += [active | data, idle | data] if cpha else [idle | data, active | data]
        out.append(idle)
    return out + [idle | chip_select, idle | chip_select]


def i2c_stream(address: int, read: int, payload, acknowledged: bool = True) -> list[int]:
    clock, data = 1 << SCL, 1 << SDA
    out = [clock | data, clock | data, clock]
    for index, byte in enumerate([address << 1 | read] + list(payload)):
        for bit_index in range(7, -1, -1):
            bit = data if (byte >> bit_index) & 1 else 0
            out += [bit, bit | clock, bit]
        ack = 0 if acknowledged or index == 0 else data
        out += [ack, ack | clock, ack]
    return out + [0, clock, clock | data]


def test_channel_extraction_and_edges():
    samples = [0x00, 0x01, 0x81, 0x80, 0x00]
    assert channel_bits(samples, 0).tolist() == [0, 1, 1, 0, 0]
    assert channel_bits(samples, 7).tolist() == [0, 0, 1, 1, 0]
    rising, falling = find_edges(channel_bits(samples, 0))
    assert rising.tolist() == [1]
    assert falling.tolist() == [3]
    with pytest.raises(ValueError):
        channel_bits(samples, 8)
    with pytest.raises(ValueError):
        channel_bits([], 0)


def test_pulse_measurements_ignore_truncated_end_runs():
    # Interior runs are 3 high and 7 low; the first and last runs are cut by the window.
    samples = [1] * 2 + ([0] * 7 + [1] * 3) * 4 + [0] * 5
    result = measure(samples, 0, 1_000_000)
    assert result.transitions == 9
    assert result.shortest_high == pytest.approx(3e-6)
    assert result.shortest_low == pytest.approx(7e-6)
    assert result.frequency == pytest.approx(100_000)
    assert result.jitter == pytest.approx(0.0)


def test_narrow_pulse_survives_a_single_sample():
    samples = [0] * 10 + [1] + [0] * 10
    result = measure(samples, 0, 2_000_000)
    assert result.transitions == 2
    assert result.shortest_high == pytest.approx(500e-9)
    assert result.period is None and result.frequency is None


def test_sampling_jitter_is_reported_as_peak_deviation():
    steady = measure(square(5, 5, 20), 0, 1_000_000)
    assert steady.jitter == pytest.approx(0.0)

    # Six periods of ten samples and one of eleven. Jitter is the widest departure
    # from the mean period, not the difference between two adjacent periods.
    samples = square(5, 5, 4) + [1] * 5 + [0] * 6 + square(5, 5, 4)
    jittered = measure(samples, 0, 1_000_000)
    assert jittered.period == pytest.approx(71 / 7 * 1e-6)
    assert jittered.jitter == pytest.approx((11 - 71 / 7) * 1e-6)


def test_measurements_reject_a_non_positive_rate():
    with pytest.raises(ValueError):
        measure(square(5, 5, 4), 0, 0)


def test_uart_decodes_bytes_at_their_sample_positions():
    span = 16
    symbols = decode_uart(uart_stream([0x41, 0x7E, 0x00, 0xFF], span), 0, 1_000_000, 62_500)
    assert [symbol.value for symbol in symbols] == [0x41, 0x7E, 0x00, 0xFF]
    assert [symbol.text for symbol in symbols] == ["0x41", "0x7E", "0x00", "0xFF"]
    assert all(symbol.error is None for symbol in symbols)
    assert symbols[0].start == 2 * span
    assert symbols[1].start - symbols[0].start == 10 * span


def test_uart_decodes_a_channel_other_than_zero():
    symbols = decode_uart(uart_stream([0x5A], 8, channel=5), 5, 1_000_000, 125_000)
    assert [symbol.value for symbol in symbols] == [0x5A]


def test_uart_reports_parity_and_framing_errors():
    good = decode_uart(uart_stream([0x37], 16, parity="even"), 0, 1e6, 62_500, parity="even")
    assert good[0].error is None and good[0].value == 0x37

    wrong = decode_uart(uart_stream([0x37], 16, parity="odd"), 0, 1e6, 62_500, parity="even")
    assert wrong[0].error == "parity"
    assert "parity" in wrong[0].text

    broken = uart_stream([0x37], 16)
    broken[2 * 16 + 9 * 16 + 8] = 0  # Hold the stop bit low at its sampling point.
    assert decode_uart(broken, 0, 1e6, 62_500)[0].error == "framing"


def test_uart_rejects_impossible_settings():
    samples = uart_stream([0x41], 16)
    with pytest.raises(ValueError):
        decode_uart(samples, 0, 1_000_000, 1_000_000)
    with pytest.raises(ValueError):
        decode_uart(samples, 0, 1_000_000, 0)
    with pytest.raises(ValueError):
        decode_uart(samples, 0, 1_000_000, 62_500, data_bits=4)
    with pytest.raises(ValueError):
        decode_uart(samples, 0, 1_000_000, 62_500, parity="mark")


@pytest.mark.parametrize("cpol", (0, 1))
@pytest.mark.parametrize("cpha", (0, 1))
def test_spi_decodes_words_on_each_clock_mode(cpol, cpha):
    stream = spi_stream([0xAB, 0x3C], cpol=cpol, cpha=cpha)
    symbols = decode_spi(stream, SCL, SDA, cpol=cpol, cpha=cpha)
    assert [symbol.value for symbol in symbols] == [0xAB, 0x3C]


def test_spi_reads_the_wrong_edge_when_the_mode_is_wrong():
    stream = spi_stream([0xFF, 0x00], cpol=0, cpha=0)
    assert [symbol.value for symbol in decode_spi(stream, SCL, SDA, cpha=1)] != [0xFF, 0x00]


def test_spi_honours_least_significant_bit_first():
    symbols = decode_spi(spi_stream([0x01]), SCL, SDA, msb_first=False)
    assert symbols[0].value == 0x80


def test_spi_discards_bits_clocked_while_deselected():
    select = 4
    stream = spi_stream([0xAB], select=select)
    # Two extra clock pulses while the select line is high must not shift the word.
    noise = [(1 << select), (1 << select) | (1 << SCL), (1 << select)] * 2
    symbols = decode_spi(noise + stream, SCL, SDA, select=select)
    assert [symbol.value for symbol in symbols] == [0xAB]


def test_spi_rejects_overlapping_or_invalid_channels():
    stream = spi_stream([0xAB])
    with pytest.raises(ValueError):
        decode_spi(stream, SCL, SCL)
    with pytest.raises(ValueError):
        decode_spi(stream, SCL, SDA, select=SDA)
    with pytest.raises(ValueError):
        decode_spi(stream, SCL, SDA, cpol=2)
    with pytest.raises(ValueError):
        decode_spi(stream, SCL, SDA, word_bits=32)


def test_i2c_decodes_a_write_transfer():
    symbols = decode_i2c(i2c_stream(0x50, 0, [0xA3, 0x01]), SCL, SDA)
    assert [symbol.text for symbol in symbols] == [
        "Start",
        "0x50 write ACK",
        "0xA3 ACK",
        "0x01 ACK",
        "Stop",
    ]


def test_i2c_reports_the_read_bit_and_a_nack():
    symbols = decode_i2c(i2c_stream(0x1D, 1, [0xFF], acknowledged=False), SCL, SDA)
    assert symbols[1].text == "0x1D read ACK"
    assert symbols[2].text == "0xFF NACK"
    assert symbols[2].error == "nack"


def test_i2c_rejects_one_channel_for_both_lines():
    with pytest.raises(ValueError):
        decode_i2c(i2c_stream(0x50, 0, [0x00]), SCL, SCL)


def test_decoders_return_nothing_for_an_idle_capture():
    idle = [0xFF] * 256
    assert decode_uart(idle, 0, 1_000_000, 62_500) == []
    assert decode_spi(idle, SCL, SDA) == []
    assert decode_i2c(np.zeros(256, dtype=np.uint8), SCL, SDA) == []
