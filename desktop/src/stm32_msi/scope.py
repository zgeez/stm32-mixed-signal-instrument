"""Oscilloscope capture analysis."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Measurements:
    minimum: float
    maximum: float
    mean: float
    rms: float
    peak_to_peak: float
    frequency: float | None
    period: float | None


def adc_volts(samples, reference: float) -> np.ndarray:
    return np.asarray(samples, dtype=float) * reference / 4095.0


def measure(samples, sample_rate: float) -> Measurements:
    values = np.asarray(samples, dtype=float)
    if values.size == 0 or sample_rate <= 0:
        raise ValueError("A capture and positive sample rate are required")
    center = float(np.mean(values))
    hysteresis = float(np.ptp(values)) * 0.05
    low, high = center - hysteresis, center + hysteresis
    crossings = []
    armed = False
    below = None
    for index, value in enumerate(values):
        if value <= low:
            armed = True
        if value < center:
            below = index
        elif armed and value >= high and below is not None and below + 1 < values.size:
            span = values[below + 1] - values[below]
            crossings.append(below + (center - values[below]) / span if span else float(below))
            armed = False
            below = None
    frequency = period = None
    if len(crossings) >= 2:
        period = float(np.mean(np.diff(crossings)) / sample_rate)
        if period > 0:
            frequency = 1.0 / period
    return Measurements(
        float(np.min(values)),
        float(np.max(values)),
        center,
        float(np.sqrt(np.mean(values * values))),
        float(np.ptp(values)),
        frequency,
        period,
    )
