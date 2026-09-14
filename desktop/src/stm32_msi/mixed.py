"""Placing an analog and a digital capture on one timeline.

Both streams start from the same timer event, so a sample's time is its index divided by
its own rate, plus the offset of its window from that shared start. The two rates differ
and neither is a multiple of the other, so nothing is resampled here: the raw samples and
their true instants are kept, and the overlap is reported rather than assumed.

Sharing an origin is not the same as sampling at the same instants. The ADC holds its
input for three cycles after its trigger while a GPIO read lands whenever the DMA wins
the bus, so a constant skew remains between the two paths. It is measured, not corrected
for, and `align` deliberately does not fold it in.
"""

from dataclasses import dataclass

import numpy as np

# Neither timer produces a sample at the instant it is released: the first one arrives on
# the first update, a whole sample period later. So sample i sits at window_origin + i + 1
# on the shared grid, not window_origin + i. The two streams run at different rates, so
# leaving this out pulls them apart by one digital period minus one analog period - 899 ns
# between a 1 MS/s analog stream and a 9.88 MS/s digital one, which is most of a sample.
SAMPLE_ZERO_DELAY = 1


def sample_time(index, rate: float, window_origin: int):
    """Seconds from the shared release to a stream's sample, by index within the window."""
    return (window_origin + SAMPLE_ZERO_DELAY + index) / rate


@dataclass(frozen=True)
class Stream:
    """One capture placed against the shared start."""

    name: str
    rate: float
    window_origin: int
    trigger_index: int
    count: int

    def times(self) -> np.ndarray:
        """Seconds from the shared start, one entry per captured sample."""
        return sample_time(np.arange(self.count), self.rate, self.window_origin)

    @property
    def start(self) -> float:
        return sample_time(0, self.rate, self.window_origin)

    @property
    def end(self) -> float:
        return sample_time(self.count - 1, self.rate, self.window_origin)

    @property
    def trigger_time(self) -> float:
        return sample_time(self.trigger_index, self.rate, self.window_origin)


@dataclass(frozen=True)
class Alignment:
    """How two streams relate on one timeline, all times in seconds."""

    origin: float
    overlap_start: float
    overlap_end: float
    streams: tuple[Stream, ...]

    @property
    def overlap(self) -> float:
        return max(0.0, self.overlap_end - self.overlap_start)

    @property
    def complete(self) -> bool:
        """True when every stream covers the whole overlap, so nothing is extrapolated."""
        return self.overlap > 0

    def relative(self, stream: Stream) -> np.ndarray:
        """Sample times measured from the trigger instant, which is what a reader sees."""
        return stream.times() - self.origin


def align(streams, triggered: str) -> Alignment:
    """Put streams on a common axis with zero at the triggering stream's edge."""
    streams = tuple(streams)
    if len(streams) < 2:
        raise ValueError("Alignment needs at least two streams")
    if any(s.rate <= 0 for s in streams):
        raise ValueError("Every stream needs a positive sample rate")
    names = [s.name for s in streams]
    if triggered not in names:
        raise ValueError(f"{triggered!r} is not among {names}")
    if len(set(names)) != len(names):
        raise ValueError("Stream names must be unique")
    leader = streams[names.index(triggered)]
    return Alignment(
        origin=leader.trigger_time,
        overlap_start=max(s.start for s in streams),
        overlap_end=min(s.end for s in streams),
        streams=streams,
    )


def edge_times(
    samples, rate: float, window_origin: int, threshold: float, rising: bool = True
) -> np.ndarray:
    """Every threshold crossing, in seconds from the shared start.

    Each crossing is placed by linear interpolation between the two samples that straddle
    it. That assumes the signal is monotonic across a single interval, which is fair for
    a clean edge and wrong for a noisy or slew-limited one; the caller states which.
    """
    values = np.asarray(samples, dtype=float)
    if values.size < 2 or rate <= 0:
        return np.empty(0)
    if rising:
        crossings = np.flatnonzero((values[:-1] < threshold) & (values[1:] >= threshold))
    else:
        crossings = np.flatnonzero((values[:-1] > threshold) & (values[1:] <= threshold))
    if crossings.size == 0:
        return np.empty(0)
    span = values[crossings + 1] - values[crossings]
    safe = np.where(span == 0, 1.0, span)
    fraction = np.where(span == 0, 0.0, (threshold - values[crossings]) / safe)
    return sample_time(crossings + fraction, rate, window_origin)


def edge_time(samples, rate: float, window_origin: int, threshold: float, rising: bool = True):
    """Time of the first threshold crossing, or None if there is none."""
    times = edge_times(samples, rate, window_origin, threshold, rising)
    return float(times[0]) if times.size else None


def nearest_edge(times, reference: float):
    """The crossing closest to a reference instant, or None if there are none.

    Skew has to compare the *same* edge on both paths. Taking the first crossing in each
    window pairs whichever edges happen to fall first, and on a periodic signal that
    differs by a whole period at random, which looks like an enormous skew. Both streams
    share an origin, so the edge nearest a common instant is the one they have in common.
    """
    times = np.asarray(times, dtype=float)
    if times.size == 0:
        return None
    return float(times[int(np.argmin(np.abs(times - reference)))])


def skew(analog_edge: float | None, digital_edge: float | None):
    """Analog edge time minus digital edge time. Positive means the analog path lags."""
    if analog_edge is None or digital_edge is None:
        return None
    return analog_edge - digital_edge


def summarise(skews) -> dict:
    """Mean and spread of repeated skew measurements.

    The mean estimates the systematic offset between the two acquisition paths; the
    spread carries jitter together with threshold and quantisation effects, which this
    cannot separate.
    """
    values = np.asarray([s for s in skews if s is not None], dtype=float)
    if values.size == 0:
        raise ValueError("No usable skew measurements")
    return {
        "count": int(values.size),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "spread": float(np.max(values) - np.min(values)),
        "deviation": float(np.std(values)),
        "minimum": float(np.min(values)),
        "maximum": float(np.max(values)),
    }
