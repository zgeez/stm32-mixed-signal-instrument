import numpy as np
import pytest

from stm32_msi.mixed import (
    SAMPLE_ZERO_DELAY,
    Stream,
    align,
    edge_time,
    edge_times,
    nearest_edge,
    skew,
    summarise,
)


def scope_stream(rate=1_000_000, origin=0, trigger=256, count=512):
    return Stream("scope", rate, origin, trigger, count)


def logic_stream(rate=9_882_352, origin=0, trigger=0, count=4096):
    return Stream("logic", rate, origin, trigger, count)


def test_sample_times_come_from_the_shared_start():
    stream = Stream("scope", 1_000_000, window_origin=100, trigger_index=10, count=4)
    # Sample zero is the hundredth after the release, and the release itself yields no
    # sample: the first arrives one period later, so sample zero sits at 101 us.
    assert stream.times().tolist() == pytest.approx([101e-6, 102e-6, 103e-6, 104e-6])
    assert stream.start == pytest.approx(101e-6)
    assert stream.end == pytest.approx(104e-6)
    assert stream.trigger_time == pytest.approx(111e-6)


def test_the_release_instant_itself_carries_no_sample():
    # Measured on hardware: leaving this out put the analog edge 1050 ns from the shared
    # instant at 1 MS/s, where correcting for it leaves 152 ns. The error is the
    # difference of the two periods, so it shows up as skew between the streams.
    scope = Stream("scope", 1_000_000, window_origin=0, trigger_index=0, count=8)
    logic = Stream("logic", 9_882_352, window_origin=0, trigger_index=0, count=8)
    assert scope.start == pytest.approx(1e-6)
    assert logic.start == pytest.approx(1 / 9_882_352)
    assert scope.start - logic.start == pytest.approx(899e-9, rel=1e-2)
    assert SAMPLE_ZERO_DELAY == 1


def test_streams_at_different_rates_share_one_origin():
    # 1 MS/s and 9.88 MS/s: neither rate divides the other, and nothing is resampled.
    scope = scope_stream(rate=1_000_000, origin=0, trigger=256, count=512)
    logic = logic_stream(rate=9_882_352, origin=0, trigger=0, count=4096)
    alignment = align([scope, logic], triggered="scope")

    assert alignment.origin == pytest.approx(257e-6)
    scope_relative = alignment.relative(scope)
    logic_relative = alignment.relative(logic)
    # Zero sits on the scope's trigger sample, and the logic stream is measured against
    # the same instant rather than its own start.
    assert scope_relative[256] == pytest.approx(0.0)
    assert logic_relative[0] == pytest.approx(logic.start - scope.trigger_time)


def test_overlap_is_reported_not_assumed():
    # A slow scope covers 5.12 ms; a fast logic capture covers only 414 us.
    scope = scope_stream(rate=100_000, count=512)
    logic = logic_stream(rate=9_882_352, count=4096)
    alignment = align([scope, logic], triggered="scope")
    assert alignment.complete
    assert alignment.overlap == pytest.approx(logic.end - scope.start)
    assert alignment.overlap < scope.end / 10


def test_streams_that_do_not_overlap_report_it():
    scope = Stream("scope", 1_000_000, window_origin=0, trigger_index=0, count=10)
    logic = Stream("logic", 1_000_000, window_origin=5_000, trigger_index=0, count=10)
    alignment = align([scope, logic], triggered="scope")
    assert not alignment.complete
    assert alignment.overlap == 0.0


def test_a_window_origin_shifts_a_stream_on_the_timeline():
    early = Stream("logic", 1_000_000, window_origin=0, trigger_index=0, count=4)
    late = Stream("logic", 1_000_000, window_origin=1_000, trigger_index=0, count=4)
    assert late.times()[0] - early.times()[0] == pytest.approx(1e-3)


def test_align_rejects_inputs_it_cannot_place():
    scope = scope_stream()
    with pytest.raises(ValueError):
        align([scope], triggered="scope")
    with pytest.raises(ValueError):
        align([scope, logic_stream()], triggered="probe")
    with pytest.raises(ValueError):
        align([scope, Stream("logic", 0, 0, 0, 4)], triggered="scope")
    with pytest.raises(ValueError):
        align([scope, scope_stream()], triggered="scope")


def test_edge_time_interpolates_between_the_straddling_samples():
    # Crossing 2048 exactly halfway between sample 2 and 3, at 1 MS/s.
    samples = [0, 1000, 2000, 2096, 4000]
    at = edge_time(samples, rate=1_000_000, window_origin=0, threshold=2048)
    assert at == pytest.approx((2 + 0.5 + SAMPLE_ZERO_DELAY) * 1e-6)


def test_edge_time_accounts_for_the_window_origin():
    samples = [0, 4095]
    without = edge_time(samples, 1_000_000, window_origin=0, threshold=2048)
    with_origin = edge_time(samples, 1_000_000, window_origin=50, threshold=2048)
    assert with_origin - without == pytest.approx(50e-6)


def test_edge_time_handles_falling_edges_and_absent_crossings():
    # 2047/4095 of the way down, not exactly half: the interpolation is not rounded.
    falling = edge_time([4095, 0], 1_000_000, 0, 2048, rising=False)
    assert falling == pytest.approx((2047 / 4095 + SAMPLE_ZERO_DELAY) * 1e-6)
    assert edge_time([4095, 0], 1_000_000, 0, 2048, rising=True) is None
    assert edge_time([0, 0, 0], 1_000_000, 0, 2048) is None
    assert edge_time([0], 1_000_000, 0, 2048) is None


def test_a_flat_step_does_not_divide_by_zero():
    # Both samples exactly on the threshold: no fraction can be inferred.
    assert edge_time([2048, 2048], 1_000_000, 0, 2048) is None
    assert edge_time([0, 2048, 2048], 1_000_000, 0, 2048) == pytest.approx(2e-6)


def test_skew_is_analog_minus_digital():
    assert skew(1.2e-6, 1.0e-6) == pytest.approx(200e-9)
    assert skew(1.0e-6, 1.2e-6) == pytest.approx(-200e-9)
    assert skew(None, 1.0e-6) is None
    assert skew(1.0e-6, None) is None


def test_summarise_separates_offset_from_spread():
    result = summarise([100e-9, 120e-9, 140e-9, None, 110e-9])
    assert result["count"] == 4
    assert result["mean"] == pytest.approx(117.5e-9)
    assert result["median"] == pytest.approx(115e-9)
    assert result["spread"] == pytest.approx(40e-9)
    assert result["minimum"] == pytest.approx(100e-9)
    assert result["maximum"] == pytest.approx(140e-9)


def test_summarise_needs_something_to_summarise():
    with pytest.raises(ValueError):
        summarise([None, None])


def test_alignment_survives_chunked_transfer_and_a_trimmed_stream():
    # Reading a capture in chunks must not move it: the origin is what places it, not
    # the order the bytes arrived in.
    full = logic_stream(rate=2_000_000, origin=300, trigger=0, count=64)
    chunks = [full.times()[i : i + 12] for i in range(0, full.count, 12)]
    assert np.concatenate(chunks).tolist() == pytest.approx(full.times().tolist())

    # A short read leaves the remaining samples at their true instants.
    trimmed = Stream("logic", 2_000_000, window_origin=300, trigger_index=0, count=40)
    assert trimmed.times().tolist() == pytest.approx(full.times()[:40].tolist())


def test_edge_times_returns_every_crossing():
    # Three rising crossings of 2048 at 1 MS/s.
    samples = [0, 4095, 0, 4095, 0, 4095]
    times = edge_times(samples, 1_000_000, 0, 2048)
    assert times.size == 3
    assert times.tolist() == pytest.approx([1.5e-6, 3.5e-6, 5.5e-6], rel=1e-3)
    assert edge_times([0, 0, 0], 1_000_000, 0, 2048).size == 0


def test_nearest_edge_picks_the_one_a_common_instant_shares():
    # A 20 us period: taking the first crossing instead of the nearest would pair edges
    # a whole period apart and report that as skew.
    times = [-30e-6, -10e-6, 0.2e-6, 20e-6, 40e-6]
    assert nearest_edge(times, 0.0) == pytest.approx(0.2e-6)
    assert nearest_edge(times, 21e-6) == pytest.approx(20e-6)
    assert nearest_edge(times, -9e-6) == pytest.approx(-10e-6)
    assert nearest_edge([], 0.0) is None


def test_pairing_the_first_edge_is_what_produced_a_false_skew():
    # Two windows over the same 50 kHz square, offset so their first crossings are
    # different edges. Nearest-to-zero recovers the shared edge; first-crossing does not.
    period = 20e-6
    analog = [0.3e-6 + n * period for n in range(-1, 4)]
    digital = [0.1e-6 + n * period for n in range(-3, 2)]
    assert skew(analog[0], digital[0]) == pytest.approx(40.2e-6, rel=1e-3)
    paired = skew(nearest_edge(analog, 0.0), nearest_edge(digital, 0.0))
    assert paired == pytest.approx(200e-9, abs=1e-9)
