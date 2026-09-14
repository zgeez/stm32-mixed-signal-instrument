"""Characterization that needs equipment the board does not contain.

The instrument cannot check its own time base or its own volt: comparing a DAC against the
ADC beside it shares every error they have in common. Each subcommand here brings in one
outside reference and records what that reference was, because a measurement is only as
good as the thing it was compared against and an unrecorded instrument makes the number
unrepeatable.

Every subcommand requires --equipment describing the reference and its specification. That
is deliberate: a result with no stated reference is not a measurement, and the accuracy
quoted here can never be better than what the reference guarantees.

Procedures, wiring and safety notes are in testing.md.
"""

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from stm32_msi.instrument import Instrument, LogicConfig, ScopeConfig
from stm32_msi.logic import channel_bits, measure
from stm32_msi.transport import Transport

LOGIC_RATES = (1_000_000, 2_000_000, 5_000_000, 10_000_000)


def open_device(port: str) -> Instrument:
    device = Instrument(Transport(port, 8.0))
    device.stop_mixed()
    device.stop_scope()
    device.stop_logic()
    device.stop()
    device.configure_probe(0)
    return device


def emit(args, payload: dict) -> int:
    record = {
        "recorded": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "equipment": args.equipment,
        "measurement": payload,
    }
    print(json.dumps(record, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(f"\nwritten to {args.out}")
    return 0


# --- time base --------------------------------------------------------------------------


def run_timebase(args) -> int:
    """Compare the sampler against a source whose own accuracy is known.

    The board divides one crystal for everything, so it cannot detect its own frequency
    error: every rate is wrong by the same fraction and the arithmetic still agrees. Only an
    independent source separates the two.
    """
    device = open_device(args.port)
    results = []
    try:
        for rate in args.rates:
            device.configure_logic(
                LogicConfig(sample_rate=rate, sample_count=4096, trigger_mode=0)
            )
            readings = []
            for _ in range(args.repeats):
                device.arm_logic()
                deadline = time.monotonic() + 3.0
                status = device.logic_status()
                while status.state == 1 and time.monotonic() < deadline:
                    status = device.logic_status()
                if status.state != 2:
                    continue
                capture = device.read_logic_capture(status)
                reading = measure(capture.samples, args.channel, status.actual_rate)
                if reading.frequency:
                    readings.append(reading.frequency)
            device.stop_logic()
            if not readings:
                results.append({"rate_hz": rate, "error": "no edges; check the source"})
                continue
            median = statistics.median(readings)
            error_ppm = (median - args.source_hz) / args.source_hz * 1e6
            # Each edge is placed to one sample, so the frequency estimate cannot beat one
            # interval over the span of the capture. That depends on the capture length, not
            # on the source frequency.
            quantization_ppm = 1e6 / (4096 - 1)
            results.append(
                {
                    "requested_rate_hz": rate,
                    "actual_rate_hz": status.actual_rate,
                    "measured_hz": median,
                    "spread_hz": max(readings) - min(readings),
                    "captures": len(readings),
                    "error_ppm": error_ppm,
                    "source_uncertainty_ppm": args.source_ppm,
                    "quantization_ppm": quantization_ppm,
                    "significant": abs(error_ppm) > args.source_ppm + quantization_ppm,
                }
            )
    finally:
        device.stop_logic()
        device.transport.close()

    return emit(
        args,
        {
            "kind": "time-base accuracy",
            "source_hz": args.source_hz,
            "source_uncertainty_ppm": args.source_ppm,
            "channel": args.channel,
            "results": results,
            "note": "An error inside the source uncertainty is not resolved, only bounded.",
        },
    )


# --- asynchronous pulse capture ----------------------------------------------------------


def run_pulse(args) -> int:
    """Can a pulse of a stated width be caught whatever its phase?

    The board's own reference shares the sampler's clock, so its pulses land at a repeating
    phase and a shared-clock result says nothing about an arbitrary one. The source here is
    free-running, so repeated captures sweep the phase.
    """
    device = open_device(args.port)
    results = []
    try:
        for rate in args.rates:
            device.configure_logic(
                LogicConfig(sample_rate=rate, sample_count=4096, trigger_mode=0)
            )
            seen, missing, widths = 0, 0, []
            for _ in range(args.repeats):
                device.arm_logic()
                deadline = time.monotonic() + 3.0
                status = device.logic_status()
                while status.state == 1 and time.monotonic() < deadline:
                    status = device.logic_status()
                if status.state != 2:
                    continue
                capture = device.read_logic_capture(status)
                bits = channel_bits(capture.samples, args.channel)
                edges = np.flatnonzero(np.diff(bits.astype(int)) != 0)
                if edges.size < 2:
                    missing += 1
                    continue
                seen += 1
                runs = np.diff(edges)
                high = [
                    int(run)
                    for run, level in zip(runs, bits[edges[:-1] + 1], strict=True)
                    if level
                ]
                if high:
                    widths.append(min(high) / status.actual_rate)
            device.stop_logic()
            interval = 1.0 / status.actual_rate
            results.append(
                {
                    "requested_rate_hz": rate,
                    "actual_rate_hz": status.actual_rate,
                    "sample_interval_ns": interval * 1e9,
                    "captures_with_pulses": seen,
                    "captures_without": missing,
                    "shortest_high_ns": min(widths) * 1e9 if widths else None,
                    "stated_width_ns": args.width_ns,
                    # A pulse narrower than one interval can fall between samples whatever
                    # the sampler does, so absence there is not a defect.
                    "below_one_interval": args.width_ns < interval * 1e9,
                }
            )
    finally:
        device.stop_logic()
        device.transport.close()

    return emit(
        args,
        {
            "kind": "asynchronous pulse capture",
            "stated_width_ns": args.width_ns,
            "channel": args.channel,
            "results": results,
            "note": "Misses matter only for a width above one sample interval.",
        },
    )


# --- readings entered by the operator ----------------------------------------------------


def paired_readings(values: list[str]) -> list[tuple[float, float]]:
    pairs = []
    for item in values:
        left, _, right = item.partition(":")
        if not right:
            raise argparse.ArgumentTypeError(
                f"Expected commanded:measured, got {item!r}"
            )
        pairs.append((float(left), float(right)))
    return pairs


def run_dc(args) -> int:
    """Absolute output accuracy, from meter readings taken against commanded levels.

    The board cannot supply this: its ADC shares VDDA with its DAC, so a reference error
    cancels and reads as correct. The meter's own specification bounds the result.
    """
    pairs = paired_readings(args.reading)
    if len(pairs) < 3:
        raise SystemExit("At least three commanded:measured pairs are needed for a fit")
    commanded = np.array([p for p, _ in pairs])
    meter = np.array([m for _, m in pairs])
    # Commanded percent to the code the host actually sends, then to its ideal voltage.
    codes = np.array(
        [min((4096 * round(p * 10) + 500) // 1000, 4095) for p in commanded]
    )
    ideal = args.vdda * codes / 4095
    gain, offset = np.polyfit(ideal, meter, 1)
    residual = meter - (gain * ideal + offset)
    uncertainty = (
        args.meter_percent / 100 * np.abs(meter) + args.meter_counts * args.meter_lsb
    )
    return emit(
        args,
        {
            "kind": "DC output accuracy",
            "vdda_volts": args.vdda,
            "gain": float(gain),
            "offset_v": float(offset),
            "worst_residual_v": float(np.max(np.abs(residual))),
            "points": [
                {
                    "commanded_percent": float(c),
                    "dac_code": int(k),
                    "ideal_v": float(i),
                    "meter_v": float(m),
                    "error_v": float(m - i),
                    "meter_uncertainty_v": float(u),
                    "resolved": bool(abs(m - i) > u),
                }
                for c, k, i, m, u in zip(
                    commanded, codes, ideal, meter, uncertainty, strict=True
                )
            ],
            "note": "An error smaller than the meter uncertainty is bounded, not measured.",
        },
    )


def run_response(args) -> int:
    """Amplitude against frequency, from reference-scope readings at the same node.

    Comparing the capture against the scope at one node measures the acquisition path. A
    sweep that never reaches the chosen threshold bounds the bandwidth from below; it does
    not establish a cutoff.
    """
    pairs = paired_readings(args.reading)
    if not pairs:
        raise SystemExit(
            "Provide frequency:amplitude readings from the reference scope"
        )
    device = open_device(args.port)
    entries = []
    try:
        for frequency, reference_vpp in pairs:
            rate = min(1_000_000, max(100_000, int(frequency * args.oversample)))
            rate = min((100_000, 500_000, 1_000_000), key=lambda r: abs(r - rate))
            device.configure_scope(
                ScopeConfig(sample_rate=rate, sample_count=2048, trigger_edge=0)
            )
            device.arm_scope()
            deadline = time.monotonic() + 3.0
            status = device.scope_status()
            while status.state == 1 and time.monotonic() < deadline:
                status = device.scope_status()
            if status.state != 2:
                continue
            capture = device.read_capture(status)
            device.stop_scope()
            codes = np.asarray(capture.channel_1, dtype=float)
            captured_vpp = (codes.max() - codes.min()) * args.vdda / 4095
            entries.append(
                {
                    "frequency_hz": frequency,
                    "sample_rate_hz": rate,
                    "samples_per_period": rate / frequency,
                    "reference_vpp": reference_vpp,
                    "captured_vpp": captured_vpp,
                    "ratio_db": 20 * float(np.log10(captured_vpp / reference_vpp)),
                }
            )
    finally:
        device.stop_scope()
        device.transport.close()

    reached = [e for e in entries if e["ratio_db"] <= -args.threshold_db]
    return emit(
        args,
        {
            "kind": "acquisition amplitude response",
            "threshold_db": -args.threshold_db,
            "entries": entries,
            "threshold_reached": bool(reached),
            "note": "Without a point past the threshold this bounds bandwidth, not a cutoff.",
        },
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--equipment", required=True, help="reference instrument and its spec"
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="write the record as JSON here"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    timebase = subparsers.add_parser(
        "timebase", help="sampler frequency against a known source"
    )
    timebase.add_argument("--port", required=True)
    timebase.add_argument("--source-hz", type=float, required=True)
    timebase.add_argument(
        "--source-ppm", type=float, required=True, help="source accuracy"
    )
    timebase.add_argument("--channel", type=int, default=0)
    timebase.add_argument("--rates", type=int, nargs="+", default=list(LOGIC_RATES))
    timebase.add_argument("--repeats", type=int, default=8)
    timebase.set_defaults(func=run_timebase)

    pulse = subparsers.add_parser(
        "pulse", help="narrow pulses at an unsynchronized phase"
    )
    pulse.add_argument("--port", required=True)
    pulse.add_argument(
        "--width-ns", type=float, required=True, help="width on the reference"
    )
    pulse.add_argument("--channel", type=int, default=0)
    pulse.add_argument("--rates", type=int, nargs="+", default=list(LOGIC_RATES))
    pulse.add_argument("--repeats", type=int, default=40)
    pulse.set_defaults(func=run_pulse)

    dc = subparsers.add_parser("dc", help="output accuracy from meter readings")
    dc.add_argument("--vdda", type=float, required=True)
    dc.add_argument(
        "--reading", nargs="+", required=True, help="percent:volts, repeatable"
    )
    dc.add_argument(
        "--meter-percent", type=float, required=True, help="meter spec, percent"
    )
    dc.add_argument(
        "--meter-counts", type=float, default=0.0, help="meter spec, counts"
    )
    dc.add_argument(
        "--meter-lsb", type=float, default=0.001, help="volts per meter count"
    )
    dc.set_defaults(func=run_dc)

    response = subparsers.add_parser(
        "response", help="amplitude response against a scope"
    )
    response.add_argument("--port", required=True)
    response.add_argument("--vdda", type=float, required=True)
    response.add_argument(
        "--reading", nargs="+", required=True, help="hz:vpp, repeatable"
    )
    response.add_argument("--oversample", type=float, default=20.0)
    response.add_argument("--threshold-db", type=float, default=3.0)
    response.set_defaults(func=run_response)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
