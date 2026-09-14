"""Board regression: wire PC6 to PC4 and PE7; disconnect other input drivers."""

import argparse
import time

import numpy as np
from stm32_msi.instrument import Instrument, LogicConfig, ScopeConfig
from stm32_msi.transport import Transport


def check_samples(samples, period):
    high = np.asarray(samples) > 2048
    edges = np.flatnonzero(high[1:] & ~high[:-1]) + 1
    edges = edges[edges > 12]
    if len(edges) < 3:
        raise RuntimeError("Missing reference edges; check PC6-to-PC4 wiring")
    # Fit later edges, then check the whole buffer, including its first samples.
    phase = np.angle(np.mean(np.exp(2j * np.pi * (edges - 0.5) / period)))
    position = (np.arange(len(high)) - phase * period / (2 * np.pi)) % period
    distance = np.minimum.reduce(
        [position, abs(position - period / 2), period - position]
    )
    valid = distance > 1  # Exclude crossings within one sampling interval.
    bad = np.flatnonzero(valid & (high != (position < period / 2)))
    if len(bad):
        raise RuntimeError(f"Samples disagree with reference: {bad.tolist()}")
    return int(np.count_nonzero(valid[:12]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    with Transport(args.port) as transport:
        instrument = Instrument(transport)
        instrument.stop()
        instrument.stop_mixed()
        instrument.stop_scope()
        instrument.stop_logic()
        baseline = instrument.scope_status()
        try:
            instrument.configure_probe(10700)
            probe = instrument.probe_status()
            frequency = 84_000_000 / ((probe.prescaler + 1) * (probe.reload + 1))
            for channel, wave in enumerate(("sine", "arbitrary")):
                if wave == "arbitrary":
                    instrument.upload_arbitrary(
                        channel, [(n * 997) % 4096 for n in range(256)]
                    )
                instrument.configure_channel(channel, wave, 20000, 60, 50, 0)
            for mixed in (False, True):
                for rate in (1_000_000, 500_000, 100_000):
                    checked = 0
                    for trial in range(args.repeats):
                        if trial % 2:
                            instrument.start()
                        instrument.configure_scope(ScopeConfig(rate, 512))
                        if mixed:
                            instrument.configure_logic(
                                LogicConfig(10_000_000, 4096, trigger_mode=1)
                            )
                            instrument.arm_mixed("logic")
                            get_status = instrument.mixed_status
                        else:
                            instrument.arm_scope()
                            get_status = instrument.scope_status
                        deadline = time.monotonic() + 5
                        status = get_status()
                        while status.state == 1 and time.monotonic() < deadline:
                            status = get_status()
                        if status.state != 2:
                            raise RuntimeError(f"Capture did not complete: {status}")
                        status = instrument.scope_status()
                        if (status.overruns, status.dma_errors) != (
                            baseline.overruns,
                            baseline.dma_errors,
                        ):
                            raise RuntimeError(f"Acquisition errors: {status}")
                        capture = instrument.read_capture(status)
                        checked += check_samples(capture.channel_1, rate / frequency)
                        instrument.stop_mixed() if mixed else instrument.stop_scope()
                        instrument.stop()
                    print(
                        f"mixed={mixed} rate={rate}: {args.repeats} passed; {checked} early samples checked",
                        flush=True,
                    )
        finally:
            instrument.stop()
            instrument.stop_mixed()
            instrument.stop_scope()
            instrument.stop_logic()
            instrument.configure_probe(0)


if __name__ == "__main__":
    main()
