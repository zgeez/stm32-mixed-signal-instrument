"""Board regression: does the logic capture ever drop a sample?

Two failure modes, two detectors, because they look nothing alike.

Steady loss makes the capture shorter than it should be, so edges arrive closer together
than the reported sample rate implies. Fitting a line through the edge positions and
comparing its slope against that rate finds it, and the spread between captures says how
small a loss rate the run can rule out.

A single dropped sample shifts every later edge by one against that same line. No straight
line absorbs a step, so it survives in the residuals.

Periodicity does not hide either one. A square wave is fine here: only losing a whole
period could pass unnoticed, and the slope test above already bounds that.

Wiring: PC6 to a logic input. The on-board TIM3 reference is used because it is a real
digital signal; the DAC cannot make an edge fast enough, taking about 4 us to cross, which
is 40 samples of ambiguity at 9.882 MS/s where one dropped sample moves an edge by one.

    python scripts/check_sample_loss.py COM4
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "desktop" / "src"))

from stm32_msi.instrument import Instrument, LogicConfig
from stm32_msi.logic import channel_bits
from stm32_msi.transport import Transport

# A dropped sample shifts every later edge by exactly one, because loss is whole samples.
# The statistic below is a maximum over many split points, so it has a noise floor of its
# own: each edge is placed to about a third of a sample, and taking the largest of seventy
# comparisons pushes the worst innocent value to roughly 0.6. Half way between that and the
# 1.0 a real drop produces is the place to draw the line.
MARGIN = 5  # edges required either side, since a split with two is mostly noise
DROP_STEP = 0.75


def worst_step(residual: np.ndarray) -> float:
    """Largest shift between the residuals either side of any split point.

    Splits close to either end are excluded: averaging two or three residuals is dominated
    by their own scatter and says nothing about a shift.
    """
    if residual.size < 2 * MARGIN + 2:
        return 0.0
    best = 0.0
    for split in range(MARGIN, residual.size - MARGIN):
        best = max(
            best, abs(float(np.mean(residual[split:]) - np.mean(residual[:split])))
        )
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument(
        "--channel", type=int, default=0, help="logic channel PC6 reaches"
    )
    parser.add_argument("--reference-hz", type=int, default=37_000)
    parser.add_argument("--rate", type=int, default=10_000_000)
    parser.add_argument("--captures", type=int, default=30)
    args = parser.parse_args()

    device = Instrument(Transport(args.port, 8.0))
    slopes: list[float] = []
    steps: list[float] = []
    used = 0
    try:
        device.stop_mixed()
        device.stop_scope()
        device.stop_logic()
        device.stop()
        device.configure_probe(args.reference_hz, 50.0)
        actual_hz = device.probe_status().actual_hz
        time.sleep(0.2)

        for _ in range(args.captures):
            device.configure_logic(
                LogicConfig(sample_rate=args.rate, sample_count=4096, trigger_mode=0)
            )
            device.arm_logic()
            limit = time.monotonic() + 3.0
            status = device.logic_status()
            while status.state == 1 and time.monotonic() < limit:
                status = device.logic_status()
            if status.state != 2:
                device.stop_logic()
                continue
            bits = channel_bits(device.read_logic_capture(status).samples, args.channel)
            device.stop_logic()

            changes = np.flatnonzero(bits[1:] != bits[:-1])
            if changes.size < 12:
                continue
            positions = changes + 0.5
            # Edges of a square wave fall every half period, so their ordinal number is
            # the x axis and the slope is samples per half period.
            ordinal = np.arange(positions.size, dtype=float)
            slope, intercept = np.polyfit(ordinal, positions, 1)
            residual = positions - (slope * ordinal + intercept)
            expected = status.actual_rate / (2 * actual_hz)
            slopes.append(slope / expected)
            steps.append(worst_step(residual))
            used += 1
    finally:
        device.configure_probe(0)
        device.stop_logic()

    if used < 10:
        print(
            f"FAILED: only {used} captures produced edges; is PC6 wired to the input?"
        )
        return 1

    ratio = float(np.mean(slopes))
    spread = float(np.std(slopes))
    uncertainty = spread / np.sqrt(used)
    worst = max(steps)
    print(
        f"{used} captures, reference {actual_hz} Hz, sampler {args.rate // 1_000_000} MS/s"
    )
    print(f"  fitted spacing / expected : {ratio:.7f}   (1.0 means nothing missing)")
    print(f"  spread between captures   : {spread * 1e6:.0f} ppm")
    print(
        f"  worst step in residuals   : {worst:.3f} samples"
        f"   (a drop would be 1.0, flagged above {DROP_STEP})"
    )
    bound = 1.0 / max(abs(1.0 - ratio), uncertainty)
    print(f"  steady loss bounded at    : better than 1 in {bound:,.0f} samples")

    problems = []
    # The floor allows for the reference being reported as a whole hertz: near 37 kHz one
    # count is about 11 ppm, which would otherwise look like a shortfall at every rate.
    if abs(1.0 - ratio) > 3 * uncertainty + 2e-5:
        problems.append(f"fitted spacing is off by {(1 - ratio) * 1e6:.0f} ppm")
    # A dropped sample is a step of one. Quantisation alone keeps each edge within half a
    # sample, so anything under that cannot be a drop.
    if worst > DROP_STEP:
        problems.append(f"a step of {worst:.2f} samples suggests an isolated drop")
    if problems:
        print("\nFAILED: " + "; ".join(problems))
        return 1
    print("\nPassed: no steady loss above the bound, and no isolated drop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
