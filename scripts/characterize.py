"""Milestone 9 characterization: repeatable measurements with their configuration recorded.

Every result is written with the board state that produced it, so a number can be compared
against a later run rather than merely believed. Results go to JSON for that comparison and
to a table for reading.

Wiring is declared on the command line, not detected: the instrument cannot tell a
disconnected input from a quiet one, and guessing would silently turn a wiring mistake into
a measurement. A measurement whose wiring is absent is reported as skipped, never omitted.

Measurements here use only the board. Those needing an external reference live in
characterize_external.py, because the board cannot check its own time base or voltage.
"""

import argparse
import json
import platform
import statistics
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from stm32_msi.instrument import Instrument, LogicConfig, ScopeConfig
from stm32_msi.protocol import VERSION
from stm32_msi.transport import Transport

REPO = Path(__file__).resolve().parent.parent
HCLK_HZ = 168_000_000
APB2_TIMER_HZ = 84_000_000
DAC_UPDATE_HZ = 400_000
DDS_ACCUMULATOR_BITS = 32
ADC_CLOCK_HZ = APB2_TIMER_HZ / 4
ADC_SAMPLE_CYCLES = 3
ADC_CONVERSION_CYCLES = 12


@dataclass
class Context:
    instrument: Instrument
    vdda: float
    wiring: set[str]
    repeats: int


@dataclass
class Measurement:
    name: str
    summary: str
    run: Callable[[Context], dict]
    needs: tuple[str, ...] = ()
    notes: str = ""


REGISTRY: list[Measurement] = []


def measurement(name: str, summary: str, needs: tuple[str, ...] = (), notes: str = ""):
    def register(function):
        REGISTRY.append(Measurement(name, summary, function, needs, notes))
        return function

    return register


# --- configuration ---------------------------------------------------------------------


def git_revision() -> dict:
    def run(*args):
        try:
            out = subprocess.run(
                ["git", *args],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    return {
        "revision": run("rev-parse", "--short", "HEAD"),
        "dirty": bool(run("status", "--porcelain")),
    }


def firmware_image() -> dict:
    """Identify the built image by content.

    This is the image in the build tree, not necessarily the one on the board: the device
    reports no build identity, so nothing here can prove what it is running. Recorded so a
    run can at least be tied to a build that existed at the time.
    """
    import hashlib

    results = {}
    for name in ("Debug", "Release"):
        path = REPO / "firmware" / "build" / name / "firmware.elf"
        if not path.exists():
            results[name] = None
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        results[name] = {
            "sha256_prefix": digest,
            "bytes": path.stat().st_size,
            "modified": datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).isoformat(),
        }
    return results


def configuration(context: Context, port: str, equipment: str | None) -> dict:
    device = context.instrument
    return {
        "recorded": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": platform.node(),
        "python": platform.python_version(),
        "port": port,
        "git": git_revision(),
        "firmware_build": firmware_image(),
        "device": {
            "name": device.hello(),
            "protocol_version": VERSION,
            "capabilities": device.capabilities(),
            "build_identity": None,  # the device exposes none; see docs/characterization.md
        },
        "clocks_hz": {
            "hclk": HCLK_HZ,
            "apb2_timer": APB2_TIMER_HZ,
            "dac_update": DAC_UPDATE_HZ,
            "adc_clock": ADC_CLOCK_HZ,
        },
        "operator": {
            "vdda_volts": context.vdda,
            "wiring": sorted(context.wiring),
            "equipment": equipment,
        },
    }


# --- helpers ---------------------------------------------------------------------------


def quiesce(device: Instrument) -> None:
    device.stop_mixed()
    device.stop_scope()
    device.stop_logic()
    device.stop()
    device.configure_probe(0)


def capture_scope(device: Instrument, rate: int, count: int, timeout: float = 3.0):
    device.configure_scope(
        ScopeConfig(sample_rate=rate, sample_count=count, trigger_edge=0)
    )
    device.arm_scope()
    deadline = time.monotonic() + timeout
    status = device.scope_status()
    while status.state == 1 and time.monotonic() < deadline:
        status = device.scope_status()
    capture = device.read_capture(status) if status.state == 2 else None
    device.stop_scope()
    return capture


def codes_to_volts(codes, vdda: float) -> float:
    return float(np.mean(codes)) * vdda / 4095.0


# --- measurements ----------------------------------------------------------------------


@measurement(
    "awg-frequency",
    "Frequency resolution and quantization of the DDS",
    notes="Self-consistent only. Absolute accuracy is the HSE crystal; see the external set.",
)
def awg_frequency(context: Context) -> dict:
    """Compare requested, device-reported and independently recomputed frequency.

    The protocol carries millihertz, but the accumulator steps in 93 microhertz, so the
    reported figure is itself rounded. Recomputing the accumulator word here checks the
    firmware's arithmetic rather than trusting what it reports about itself.
    """
    device = context.instrument
    step_hz = DAC_UPDATE_HZ / (2**DDS_ACCUMULATOR_BITS)
    points = []
    for requested in (
        1.0,
        7.3,
        250.0,
        1000.0,
        1234.567,
        4999.999,
        10_000.0,
        19_999.999,
    ):
        device.configure_channel(1, "sine", requested, 50.0, 50.0, 0.0)
        status = device.channel_status(1)
        word = round(requested * (2**DDS_ACCUMULATOR_BITS) / DAC_UPDATE_HZ)
        recomputed = word * DAC_UPDATE_HZ / (2**DDS_ACCUMULATOR_BITS)
        points.append(
            {
                "requested_hz": requested,
                "reported_hz": status.actual_millihz / 1000,
                "recomputed_hz": recomputed,
                "quantization_hz": recomputed - requested,
                "report_vs_recomputed_hz": status.actual_millihz / 1000 - recomputed,
            }
        )
    worst_quantization = max(abs(p["quantization_hz"]) for p in points)
    worst_disagreement = max(abs(p["report_vs_recomputed_hz"]) for p in points)
    return {
        "headline": f"quantization <= {worst_quantization * 1e6:.1f} uHz, "
        f"firmware agrees to {worst_disagreement * 1000:.3f} mHz",
        "accumulator_step_hz": step_hz,
        "protocol_resolution_hz": 1e-3,
        "worst_quantization_hz": worst_quantization,
        "worst_report_disagreement_hz": worst_disagreement,
        "points": points,
    }


@measurement("acquisition-rates", "Requested against achievable sample rates")
def acquisition_rates(context: Context) -> dict:
    """Both samplers divide a fixed timer clock, so only some rates are reachable."""
    device = context.instrument
    scope = []
    for rate in (100_000, 500_000, 1_000_000):
        divider = APB2_TIMER_HZ / rate
        achievable = APB2_TIMER_HZ / round(divider)
        capture = capture_scope(device, rate, 64)
        scope.append(
            {
                "requested_hz": rate,
                "divider": divider,
                "achievable_hz": achievable,
                "error_ppm": (achievable - rate) / rate * 1e6,
                "exact": divider == round(divider),
                "captured": capture is not None,
            }
        )

    logic = []
    for rate in (1_000_000, 2_000_000, 5_000_000, 10_000_000):
        device.configure_logic(
            LogicConfig(sample_rate=rate, sample_count=64, trigger_mode=0)
        )
        status = device.logic_status()
        logic.append(
            {
                "requested_hz": rate,
                "actual_hz": status.actual_rate,
                "error_ppm": (status.actual_rate - rate) / rate * 1e6,
                "exact": status.actual_rate == rate,
            }
        )
    device.stop_logic()

    worst = max(abs(entry["error_ppm"]) for entry in scope + logic)
    return {
        "headline": f"scope exact at every rate, logic off by up to {worst / 1e4:.2f}%",
        "scope": scope,
        "logic": logic,
        "worst_error_ppm": worst,
    }


@measurement("command-latency", "Round-trip time for a status request")
def command_latency(context: Context) -> dict:
    """Idle and under load, because the figure that matters is the loaded one."""
    device = context.instrument

    def sample(count: int) -> list[float]:
        times = []
        for _ in range(count):
            start = time.perf_counter()
            device.device_status()
            times.append((time.perf_counter() - start) * 1e3)
        return times

    idle = sample(200)

    device.configure_channel(0, "sine", 20_000.0, 60.0, 50.0, 0.0)
    device.configure_channel(1, "sine", 10_000.0, 100.0, 50.0, 0.0)
    device.start()
    device.configure_logic(
        LogicConfig(sample_rate=10_000_000, sample_count=4096, trigger_mode=0)
    )
    device.arm_logic()
    loaded = sample(200)
    device.stop_logic()
    device.stop()

    def describe(values: list[float]) -> dict:
        ordered = sorted(values)
        return {
            "count": len(ordered),
            "median_ms": statistics.median(ordered),
            "p99_ms": ordered[int(len(ordered) * 0.99) - 1],
            "max_ms": ordered[-1],
        }

    return {
        "headline": f"median {statistics.median(idle):.2f} ms idle, "
        f"{statistics.median(loaded):.2f} ms loaded",
        "idle": describe(idle),
        "loaded": describe(loaded),
    }


@measurement("transfer-throughput", "Capture transfer time against depth")
def transfer_throughput(context: Context) -> dict:
    """Sampling stops before transfer, so this bounds how often a capture can be refreshed."""
    device = context.instrument
    entries = []
    for count in (64, 256, 512, 1024, 2048):
        device.configure_scope(
            ScopeConfig(sample_rate=1_000_000, sample_count=count, trigger_edge=0)
        )
        elapsed = []
        for _ in range(max(3, context.repeats // 2)):
            device.arm_scope()
            status = device.scope_status()
            deadline = time.monotonic() + 3.0
            while status.state == 1 and time.monotonic() < deadline:
                status = device.scope_status()
            if status.state != 2:
                continue
            start = time.perf_counter()
            device.read_capture(status)
            elapsed.append((time.perf_counter() - start) * 1e3)
        device.stop_scope()
        if not elapsed:
            continue
        median = statistics.median(elapsed)
        payload = count * 4  # a packed pair of 16-bit channels per sample
        entries.append(
            {
                "samples": count,
                "payload_bytes": payload,
                "median_ms": median,
                "throughput_kb_s": payload / median,
            }
        )
    if not entries:
        raise RuntimeError("No capture completed")
    best = max(entry["throughput_kb_s"] for entry in entries)
    return {
        "headline": f"up to {best:.0f} kB/s, {entries[-1]['median_ms']:.1f} ms at depth "
        f"{entries[-1]['samples']}",
        "scope": entries,
        "peak_kb_s": best,
    }


@measurement(
    "loopback-transfer",
    "Combined DAC-to-ADC gain, offset and linearity",
    needs=("PA5-PC4",),
    notes="Loopback cannot separate the DAC from the ADC; that needs an external reference.",
)
def loopback_transfer(context: Context) -> dict:
    """Sweep a DC level through the DAC and read it back through the ADC.

    A straight-line fit gives gain and offset; the worst departure from that line is the
    combined nonlinearity of both converters plus whatever the board contributes. None of
    it can be attributed to one converter without an external reference.
    """
    device = context.instrument
    requested, measured, codes = [], [], []
    for percent in range(5, 100, 5):
        device.configure_channel(1, "dc", 1000.0, 0.0, float(percent), 0.0)
        device.start()
        time.sleep(0.05)
        capture = capture_scope(device, 100_000, 256)
        device.stop()
        if capture is None:
            continue
        # The ideal is the code actually commanded, not the percentage asked for: the host
        # rounds a permille to a DAC code, and charging that rounding to the hardware would
        # appear as gain error the converters never had.
        code = min((4096 * round(percent * 10) + 500) // 1000, 4095)
        codes.append(code)
        requested.append(context.vdda * code / 4095)
        measured.append(codes_to_volts(capture.channel_1, context.vdda))

    if len(requested) < 5:
        raise RuntimeError("Too few usable points; check the PA5 to PC4 link")
    x = np.asarray(requested)
    y = np.asarray(measured)
    gain, offset = np.polyfit(x, y, 1)
    residual = y - (gain * x + offset)
    worst = float(np.max(np.abs(residual)))
    lsb = context.vdda / 4095
    return {
        "headline": f"gain {gain:.4f}, offset {offset * 1000:+.1f} mV, "
        f"worst departure {worst * 1000:.1f} mV ({worst / lsb:.1f} LSB)",
        "points": [
            {"dac_code": int(c), "ideal_v": float(a), "measured_v": float(b)}
            for c, a, b in zip(codes, x, y, strict=True)
        ],
        "gain": float(gain),
        "offset_v": float(offset),
        "worst_residual_v": worst,
        "worst_residual_lsb": worst / lsb,
        "lsb_v": lsb,
    }


@measurement(
    "noise-floor",
    "Spread of a held DC level, within and between captures",
    needs=("PA5-PC4",),
)
def noise_floor(context: Context) -> dict:
    """Within a capture this is sample noise; between captures it adds drift and settling."""
    device = context.instrument
    device.configure_channel(1, "dc", 1000.0, 0.0, 50.0, 0.0)
    device.start()
    time.sleep(0.1)
    within, means = [], []
    for _ in range(context.repeats):
        capture = capture_scope(device, 1_000_000, 512)
        if capture is None:
            continue
        codes = np.asarray(capture.channel_1, dtype=float)
        within.append(float(np.std(codes)))
        means.append(float(np.mean(codes)))
    device.stop()
    if len(means) < 3:
        raise RuntimeError("Too few usable captures; check the PA5 to PC4 link")
    lsb_uv = context.vdda / 4095 * 1e6
    within_lsb = float(np.mean(within))
    between_lsb = float(np.std(means))
    return {
        "headline": f"{within_lsb:.2f} LSB within a capture, {between_lsb:.2f} LSB between",
        "within_capture_lsb": within_lsb,
        "within_capture_uv": within_lsb * lsb_uv,
        "between_capture_lsb": between_lsb,
        "between_capture_uv": between_lsb * lsb_uv,
        "captures": len(means),
        "lsb_uv": lsb_uv,
    }


@measurement(
    "trigger-position", "Where the trigger lands against the requested pretrigger"
)
def trigger_position(context: Context) -> dict:
    """The window is cut around the trigger, so a wrong index misplaces every sample."""
    device = context.instrument
    entries = []
    for permille in (0, 100, 250, 500, 750, 900):
        count = 512
        device.configure_scope(
            ScopeConfig(
                sample_rate=1_000_000,
                sample_count=count,
                trigger_edge=0,
                pretrigger_permille=permille,
            )
        )
        device.arm_scope()
        status = device.scope_status()
        deadline = time.monotonic() + 3.0
        while status.state == 1 and time.monotonic() < deadline:
            status = device.scope_status()
        device.stop_scope()
        expected = count * permille // 1000
        entries.append(
            {
                "pretrigger_permille": permille,
                "expected_index": expected,
                "reported_index": status.trigger_index,
                "error_samples": status.trigger_index - expected,
            }
        )
    worst = max(abs(entry["error_samples"]) for entry in entries)
    return {
        "headline": f"worst trigger index error {worst} samples",
        "entries": entries,
        "worst_error_samples": worst,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="CDC port, for example COM4")
    parser.add_argument(
        "--vdda",
        type=float,
        required=True,
        help="measured VDDA in volts; every voltage here is relative to it",
    )
    parser.add_argument(
        "--wiring",
        default="",
        help="comma-separated links actually fitted, for example PA5-PC4,PA5-PE7",
    )
    parser.add_argument(
        "--repeats", type=int, default=8, help="repeats per measurement"
    )
    parser.add_argument(
        "--only", default="", help="comma-separated measurement names to run"
    )
    parser.add_argument(
        "--equipment", default=None, help="external equipment used, if any"
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="write results as JSON here"
    )
    args = parser.parse_args()

    wanted = {name.strip() for name in args.only.split(",") if name.strip()}
    wiring = {link.strip().upper() for link in args.wiring.split(",") if link.strip()}

    transport = Transport(args.port, 8.0)
    device = Instrument(transport)
    context = Context(device, args.vdda, wiring, args.repeats)
    results = []
    try:
        quiesce(device)
        config = configuration(context, args.port, args.equipment)
        for entry in REGISTRY:
            if wanted and entry.name not in wanted:
                continue
            missing = [link for link in entry.needs if link not in wiring]
            if missing:
                results.append(
                    {
                        "name": entry.name,
                        "skipped": f"needs wiring {', '.join(missing)}",
                    }
                )
                print(f"  {entry.name:<28} skipped, needs {', '.join(missing)}")
                continue
            try:
                value = entry.run(context)
            except Exception as exc:  # noqa: BLE001 - report, never abandon the run
                results.append({"name": entry.name, "failed": str(exc)})
                print(f"  {entry.name:<28} FAILED: {exc}")
                continue
            finally:
                quiesce(device)
            results.append({"name": entry.name, "summary": entry.summary, **value})
            print(f"  {entry.name:<28} {value.get('headline', 'done')}")
    finally:
        quiesce(device)
        transport.close()

    report = {"configuration": config, "results": results}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n  written to {args.out}")
    return 0 if all("failed" not in item for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
