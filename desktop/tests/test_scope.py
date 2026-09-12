import numpy as np
import pytest

from stm32_msi.scope import adc_volts, measure


def test_adc_conversion_and_measurements():
    assert adc_volts([0, 4095], 3.0).tolist() == [0.0, 3.0]
    rate = 100_000
    frequency = 1000
    samples = 1.5 + np.sin(2 * np.pi * frequency * np.arange(500) / rate)
    result = measure(samples, rate)
    assert result.minimum == pytest.approx(0.5, abs=0.001)
    assert result.maximum == pytest.approx(2.5, abs=0.001)
    assert result.peak_to_peak == pytest.approx(2.0, abs=0.001)
    assert result.frequency == pytest.approx(frequency, rel=0.001)
    assert result.period == pytest.approx(1 / frequency, rel=0.001)


def test_measurement_rejects_empty_capture():
    with pytest.raises(ValueError):
        measure([], 100_000)


def test_frequency_ignores_noise_near_a_crossing():
    rate = 100_000
    samples = np.sin(2 * np.pi * 1000 * np.arange(500) / rate)
    for crossing in (100, 200, 300, 400):
        samples[crossing - 1 : crossing + 3] = (-0.01, 0.01, -0.01, 0.02)
    assert measure(samples, rate).frequency == pytest.approx(1000, rel=0.01)
