# Characterization

Measured limits, error budgets and performance for the STM32F407G-DISC1 mixed-signal
instrument. Pass/fail results are in [validation](validation.md); this document holds the
numbers and what bounds them.

Every figure below comes from `characterization-baseline.json`, written by the harness with
the configuration that produced it. Re-running writes a comparable file.

```text
python scripts/characterize.py --port COM4 --vdda 3.000 --wiring PA5-PC4,PA5-PE7 \
    --repeats 12 --out docs/characterization-baseline.json
```

| | |
| --- | --- |
| Recorded | 2026-09-14, Release firmware |
| Wiring | PA5 to PC4 and PE7, one DAC output on both an analog and a digital input |
| VDDA | 3.000 V, declared by the operator and not measured |
| Reference | None. Every figure here is the board against itself. |

## 1. What is recorded, and one gap

The harness records the host, the UTC time, the git revision and whether the tree was dirty,
a content hash of each built image, the device name, protocol version and capabilities, the
clock constants the arithmetic assumes, and the operator's declared VDDA, wiring and
equipment. Wiring is declared rather than detected: the instrument cannot distinguish a
disconnected input from a quiet one, and a measurement whose wiring is absent is reported as
skipped rather than silently omitted.

The gap: **the device reports no build identity.** It answers with a name, a protocol version
and a capability set, none of which change between firmware builds. A result can therefore be
tied to an image that existed on the host at the time, but nothing proves which image the
board was running. Closing this needs a command returning a build identifier.

## 2. Error budgets

### Generated frequency

| Term | Value | Basis |
| --- | --- | --- |
| Accumulator step | 93.13 uHz | 400 kS/s over a 32-bit accumulator |
| Worst quantization over the sampled set | 43.1 uHz | Measured, 8 frequencies from 1 Hz to 20 kHz |
| Protocol resolution | 1 mHz | Frequency is carried in millihertz |
| Firmware agreement | 0.043 mHz | Reported actual against independent recomputation |
| Crystal accuracy | **unmeasured** | Needs an independent reference |

Quantization is 2.2 parts per billion at 20 kHz, four orders below anything the crystal is
likely to contribute. The generated frequency is therefore set by the crystal, and the
crystal has not been measured. The reported figure agrees with recomputation to within the
millihertz the report is rounded to, so the firmware's arithmetic is not a contributor.

### Sample rate

| Requested | Actual | Error | Note |
| --- | --- | --- | --- |
| Scope 100 / 500 / 1000 kS/s | as requested | 0 ppm | 84 MHz divides exactly by 840, 168 and 84 |
| Logic 1 MS/s | 1,000,000 | 0 ppm | |
| Logic 2 MS/s | 2,000,000 | 0 ppm | |
| Logic 5 MS/s | 4,941,176 | -11,765 ppm | 168 MHz over 34 |
| Logic 10 MS/s | 9,882,352 | -11,765 ppm | 168 MHz over 17 |

The 1.18% error on the two fastest logic rates is exact and reported, so times computed from
the actual rate carry none of it. It becomes an error only if the requested rate is used for
arithmetic. Like the frequency budget, everything here is relative to the same crystal.

### Voltage, through the DAC and ADC together

| Term | Value | Basis |
| --- | --- | --- |
| LSB | 732 uV | VDDA 3.000 V over 4095 |
| ADC quantization | +/- 366 uV | Half an LSB |
| Combined gain error | +0.175% of reading | Measured, straight-line fit over 19 levels |
| Combined offset | +5.68 mV | Same fit |
| Departure from that line | 1.72 LSB, 1.26 mV | Worst residual |
| Noise, one sample | 2.69 mV rms | Measured, 3.67 LSB |
| Noise, mean of 512 samples | 0.37 mV rms | Measured between captures, 0.51 LSB |
| VDDA | **unmeasured** | Scales every figure above |

Gain, offset and nonlinearity are the DAC and the ADC together and cannot be attributed to
either: a loopback shares VDDA, so a reference error cancels and reads as correct. The
declared 3.000 V scales the whole column, so an error in it moves every voltage
proportionally without changing anything the board can see.

### Edge placement in time

| Term | Value | Basis |
| --- | --- | --- |
| Digital edge, 9.882 MS/s | +/- 50.6 ns | Half a sample interval |
| Analog edge, 1 MS/s | +/- 500 ns | Half a sample interval, fast edge |
| Analog edge spread | 289 ns rms | One interval over root twelve, confirmed at 293.7 ns |
| Analog-to-digital skew | -119.7 ns | Measured, the ADC sample and hold |
| Trigger placement | 0 samples | Exact at 0, 100, 250, 500, 750 and 900 permille |

Interpolating a step edge cannot do better than half a sample interval, because both
straddling samples sit at the rails and the midpoint is the only available estimate. Skew and
its derivation are recorded in validation V-21.

## 3. Performance

| Quantity | Idle | Under load |
| --- | --- | --- |
| Command round trip, median | 0.221 ms | 0.232 ms |
| Command round trip, p99 | 0.320 ms | 0.664 ms |
| Command round trip, max | 0.361 ms | 0.933 ms |

Load is both DAC channels running with a 4096-sample logic capture armed. 200 requests each.

| Capture depth | Transfer | Throughput |
| --- | --- | --- |
| 64 samples | 1.36 ms | 188 kB/s |
| 256 samples | 5.16 ms | 199 kB/s |
| 512 samples | 10.53 ms | 195 kB/s |
| 1024 samples | 20.31 ms | 202 kB/s |
| 2048 samples | 39.79 ms | 206 kB/s |

Sampling stops before transfer, so these times bound how often a capture can be refreshed.
Throughput rises with depth because each transfer carries a fixed per-request cost.

These are one run. Across four runs the idle median moved between 0.22 and 0.26 ms and the
2048-sample transfer between 39.8 and 46.3 ms, so treat the third digit as noise. The
converter figures are steadier: gain held at 1.0017 to 1.0018 and offset at +5.5 to
+5.7 mV, while the worst residual ranged 0.7 to 1.7 LSB and single-sample noise 3.3 to
3.7 LSB. Quoting a spread rather than one run is the point of keeping the baseline file.

### A defect this found

The first run measured a command round trip of **19.997 ms idle and 20.003 ms loaded**, with
almost no spread, and transfers that were exact multiples of it: 2048 samples took 3419.7 ms
at 2.40 kB/s. A latency identical under load and quantized to 20 ms is not a device limit but
a fixed floor.

`tasks_notify_control()` was defined and declared but never called. The CDC receive callback
buffered the packet without waking the control task, which therefore ran only on its 10 ms
idle timeout, and reception is not re-armed until that task consumes the packet. Every
request waited for the timer instead of the interrupt. The transmit-complete callback had the
same gap, throttling any reply longer than one packet.

Calling the notify from both callbacks, inside the CubeMX user-code regions, gives the
figures in the tables above:

| | Before | After | |
| --- | --- | --- | --- |
| Command round trip, median | 19.997 ms | 0.221 ms | 90x |
| Transfer, 2048 samples | 3419.7 ms | 39.79 ms | 86x |
| Throughput | 2.40 kB/s | 206 kB/s | 86x |

This is why validation V-08 recorded 1.16 ms: that figure predates the milestone 7 move of
USB handling into a task, which introduced the regression. The figures above supersede it.

## 4. Measured limits

| Limit | Value | Conditions |
| --- | --- | --- |
| Generated frequency resolution | 93.13 uHz, 1 mHz over the protocol | DDS accumulator |
| Analog sample rate | 1 MS/s, exact | Calculated ceiling 1.4 MS/s at 21 MHz ADC clock |
| Digital sample rate | 9.882 MS/s | 10 MS/s setting is experimental |
| Combined converter nonlinearity | 1.72 LSB worst of four runs | 19 levels, 5% to 95% of full scale |
| Noise floor | 3.3 to 3.7 LSB rms per sample | DC level held, 12 captures per run |
| Narrowest resolved pulse | one sample interval | Shared clock; see V-14 and the gap below |
| Sample loss | not established either way | Attempted with an aperiodic table; see testing.md |
| Command round trip | 0.22 to 0.26 ms median | 200 requests per run |
| Capture throughput | 186 to 206 kB/s | 2048 samples |

## 5. What still needs equipment

Each of these compares the board against something outside it. `scripts/characterize_external.py`
runs them and records the reference used; the procedures and wiring are in the local
`testing.md`. Every subcommand requires `--equipment`, because a result with no stated
reference is not a measurement.

| Gap | Why the board cannot close it | Command |
| --- | --- | --- |
| Crystal accuracy | One crystal drives everything, so every rate is wrong by the same fraction and the arithmetic still agrees | `characterize_external.py timebase` |
| Absolute voltage | DAC and ADC share VDDA, so a reference error cancels | `characterize_external.py dc` |
| Bandwidth and distortion | Needs a source and detector better than the path under test | `characterize_external.py response` |
| Asynchronous pulse capture | The board's own reference shares the sampler's clock, so its pulses land at a repeating phase | `characterize_external.py pulse` |

Until those are run, every figure in this document is the board measured against itself.
Quantization, linearity, noise, latency and throughput are genuine because they are relative.
Anything absolute — a volt, a hertz, a second — is bounded only by the crystal and by the
declared VDDA, neither of which has been checked.
