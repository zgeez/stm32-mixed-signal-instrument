"""Board regression: every DMA stream busy at once, for as long as you like.

Two open questions share these conditions. Whether the historical dual-arbitrary freeze can
still be provoked, and whether the FIFO and direct-mode DMA error flags ever fire in normal
operation, having only ever been seeded in software.

Both want the same load: two arbitrary tables feeding the DAC at the fastest rate the AWG
allows, a mixed capture running the ADC pair and the GPIO sampler together, and the host
polling throughout. A freeze is watched for directly, because a counter cannot report one:
the AWG state is read every poll, and a mixed capture whose id stops advancing has stalled.

    python scripts/check_contention.py COM4 --seconds 180
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "desktop" / "src"))

from stm32_msi.instrument import Instrument, LogicConfig, ScopeConfig
from stm32_msi.transport import Transport

# A ramp rather than anything clever: the point is to keep the refill busy, and every entry
# differing from the last is the worst case for a cached-scaling shortcut.
TABLE = [(index * 16) % 4096 for index in range(256)]


def counters(status) -> dict:
    return {
        "AWG underruns": status.underruns,
        "AWG DMA errors": status.awg_dma_errors,
        "refill misses": status.refill_misses,
        "scope overruns": status.scope_overruns,
        "scope DMA errors": status.scope_dma_errors,
        "logic overruns": status.logic_overruns,
        "logic DMA errors": status.logic_dma_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--seconds", type=float, default=180.0)
    args = parser.parse_args()

    device = Instrument(Transport(args.port, 8.0))
    scope = ScopeConfig(sample_rate=1_000_000, sample_count=2048, trigger_edge=0)
    logic = LogicConfig(sample_rate=10_000_000, sample_count=4096, trigger_mode=0)
    captures = polls = stalls = 0
    states: set[int] = set()
    last_id = None
    try:
        device.stop_mixed()
        device.stop_scope()
        device.stop_logic()
        device.stop()
        for channel in (0, 1):
            device.upload_arbitrary(channel, TABLE)
            device.configure_channel(channel, "arbitrary", 20_000.0, 100.0, 50.0, 0.0)
        device.start()
        time.sleep(0.2)

        before = counters(device.device_status())
        started = time.monotonic()
        deadline = started + args.seconds
        while time.monotonic() < deadline:
            device.stop_mixed()
            device.configure_scope(scope)
            device.configure_logic(logic)
            device.arm_mixed("scope")
            limit = time.monotonic() + 3.0
            status = device.mixed_status()
            while status.state == 1 and time.monotonic() < limit:
                status = device.mixed_status()
                states.add(device.device_status().awg_state)
                polls += 1
            if status.state == 2:
                captures += 1
                stalls += status.capture_id == last_id
                last_id = status.capture_id
                device.read_capture(device.scope_status())
                device.read_logic_capture(device.logic_status())
            else:
                stalls += 1
            device.stop_mixed()
        elapsed = time.monotonic() - started
        after = counters(device.device_status())
    finally:
        device.stop()
        device.stop_mixed()
        device.stop_scope()
        device.stop_logic()

    moved = {name: after[name] - value for name, value in before.items()}
    print(f"{elapsed:.0f} s, {captures} mixed captures, {polls} status polls")
    print(f"AWG states seen: {sorted(states)} (2 is running, 3 is fault)")
    for name, delta in moved.items():
        print(f"  {name:<18} {delta:+d}")

    problems = []
    if states != {2}:
        problems.append(f"the AWG left the running state: {sorted(states)}")
    if stalls:
        problems.append(f"{stalls} captures stalled")
    if captures < 10:
        problems.append(f"only {captures} captures completed")
    if any(moved.values()):
        problems.append(
            "counters moved: "
            + ", ".join(f"{name} {delta:+d}" for name, delta in moved.items() if delta)
        )
    if problems:
        print("\nFAILED: " + "; ".join(problems))
        return 1
    # Absence over a long run bounds these; it does not prove them impossible.
    print("\nPassed: no freeze, no stall, no counter moved under maximum contention")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
