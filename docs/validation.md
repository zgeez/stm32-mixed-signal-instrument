# Validation

STM32F407G-DISC1, STM32CubeF4 1.28.3, Arm GNU 14.3.1.
Debug firmware unless stated. Shared-clock loopback verifies function, not calibration.

## Host checks and build sizes

Tests cover DDS/refills, protocol framing, USB backpressure, acquisition ownership,
measurements, UART/SPI/I2C decoding and GUI behavior. All passed, including Ruff and
Debug/Release builds, on 2026-09-13.

| Milestone | Python tests | C suites | Debug RAM / flash (bytes) | Release RAM / flash (bytes) |
| --- | --- | --- | --- | --- |
| 5 | 95 | 5 | 36,208 / 53,116 | 36,200 / 29,332 |
| 6 | 137 | 6 | 56,896 / 55,972 | 56,888 / 31,016 |
| 7 | 164 | 8 | 75,960 / 75,448 | 75,952 / 41,512 |

Milestone 7 includes a 16 KiB RTOS heap, TIM3 reference output and 1 KiB of cached
arbitrary DAC codes.

## Integration checks

Recorded 2026-09-12 using ST-LINK and native CDC.

| Check | Result |
| --- | --- |
| Boot and GUI | Four RTOS tasks; CDC enumeration; connection, polling and both capture tabs passed |
| Acquisition ownership | Conflicting Arm returns busy; 20 alternating handovers passed |
| Scope | 100/500/1000 kS/s; up to 2048 pairs; 512 pairs transferred in ~40 ms |
| Logic | Up to 4096 samples at actual 1/2/4.941/9.882 MS/s; 1024 samples transferred in ~10 ms |
| Triggers | Missing edges rearm; held patterns do not retrigger; unreachable patterns produce no capture |
| AWG + scope | 435 captures in 20 s with both outputs at 20 kHz; zero errors |
| AWG + logic | 115 captures of 4096 samples at 9.88 MS/s in 10 s; zero overruns |
| Status latency | Median 1.16 ms, p99 2.32 ms, maximum 2.38 ms under load |
| Protocol | Malformed/partial frames, invalid commands, stale capture IDs and bytewise delivery handled correctly |
| Reconnect | Ten cycles passed; AWG continued; capture transfer recovered |
| Physical checks | Unplug/replug recovered; LED off when idle and slow blink when active |

## Signal checks

Recorded 2026-09-12. PA4 to PC4/PE7, PA5 to PC5/PE8; entered VDDA 3.300 V.

| Signal | Measured result |
| --- | --- |
| PA4 sine, 10 kHz, 75% FS | 10,000.372 Hz; Vpp 2.489 V versus 2.475 V expected; mean 1.657 V |
| PA5 triangle, 20 kHz, 60% FS | 20,001.423 Hz; Vpp 1.980 V |
| D0 square, 10 kHz | 10.000 kHz; duty 50.1%; minimum high/low 50/49 us |
| D1 square, 5 kHz | 5.000 kHz; duty 52.3%; minimum high/low 105/95 us |
| Arbitrary patterns | 32..256-entry tables; pin agreement 99.2..100%; identical channels agreed on all samples |
| UART, 20 kbaud | Eight byte values decoded at 1/2/4.94 MS/s; wrong baud produced framing errors |
| SPI, mode 0 | Three word sequences decoded; wrong phase did not reproduce them |
| I2C | Three read/write transfers decoded through address, data, ACK and Stop |

UART framing-error recovery has a host regression. These decoder checks used AWG
patterns, not independent external devices.

### Logic timing

TIM3 PC6 to PE7, sharing the sampler's clock. Narrowest tested pulse whose measured
high/low durations were within one sample interval of nominal:

| Actual rate | Sample interval | Narrowest resolved pulse |
| --- | --- | --- |
| 1 MS/s | 1000 ns | 1000 ns |
| 2 MS/s | 500 ns | 500 ns |
| 4.941 MS/s | 202.4 ns | 250 ns |
| 9.882 MS/s | 101.2 ns | 101.2 ns |

Across six captures per condition with 200 kHz..2 MHz sources sampled at least twice
per half-period, maximum reported jitter was 0.94 sample intervals.

A separate 20 kHz square test used eight 4096-sample captures per rate:

| Rate | Measured frequency | Maximum jitter (samples) | Maximum period error (samples) |
| --- | --- | --- | --- |
| 1 MS/s | 20.0000 kHz | 0.00 | 0.00 |
| 2 MS/s | 20.0000 kHz | 0.00 | 0.00 |
| 4.941 MS/s | 19.9997 kHz | 0.94 | 0.01 |
| 9.882 MS/s | 19.9997 kHz | 0.88 | 0.12 |

Repeats under AWG/USB load at 1 and 9.88 MS/s had unchanged jitter and zero errors.
No loss was detected in these patterns; periodic signals can hide loss. These results
do not guarantee capture of one-sample pulses at arbitrary phase.

## Refill and fault checks

Recorded 2026-09-13; the dual-arbitrary regression also passed on 2026-09-12.

| Check | Result |
| --- | --- |
| Dual arbitrary | 90 starts: 2/17/256 entries at 1/1000/20000 Hz; 3 s silent and 10 s with 251 paired polls; no added errors |
| Refill deadline | Host tests cover both halves, callback orders and unfinished work; injected ownership fault latched and Stop/Start recovered |
| Logic transfer error | DMA read from inaccessible CCM generated a hardware error; ownership released and next capture completed |
| FIFO/direct-mode handling | Software-seeded error codes incremented overruns and recovered; hardware generation of these errors remains untested |
| USB backpressure | Writes blocked after 206 requests; TX remained blocked for 60 s while AWG refills continued; draining 12,360 bytes restored requests without reconnecting or added errors |

The historical dual-arbitrary freeze did not reproduce on the RTOS build before
optimization; its original cause remains unconfirmed. Deadline shutdown is IRQ-driven
and may occur after a stale sample reaches the DAC.

### Refill latency

DWT measurements with dual 256-entry arbitrary tables at 20 kHz:

| Concurrent load (~20 s) | Transfers | Refills | Maximum callback-to-finish |
| --- | --- | --- | --- |
| Scope, 2048 pairs at 1 MS/s | 6 | 16,625 | 107,868 cycles / 642.07 us |
| Logic, 4096 samples at 9.88 MS/s | 11 | 15,843 | 106,766 cycles / 635.51 us |

Zero errors; largest observed latency leaves 637.93 us against the 1.28 ms interval.
Measurement excludes IRQ entry and earlier HAL work, so it is not a worst-case bound.
Debugger-readable `refill_max_cycles` and `refill_count` reset on Start; cycles / 168
gives microseconds. Statistics were read after stopping output.

Minimum free stack: awg 1808, acquire 1864, control 2276, status 664 bytes.
Heap free and low water: 5752 bytes.

## Earlier bring-up checks

Recorded 2026-09-10/11: flash/clock/debug verification, 202 matching DAC register
samples, ten AWG restart cycles, dual DDS at 20 kHz, 300 USB status requests under
load, scope trigger positions, and forced DAC underrun/ADC overrun recovery passed.
Identical 5 kHz loopback channels had zero-sample lag and 0.999997 correlation.
Live scope completed five 64-pair captures in 0.56 s with working Stop and scrolling.

## Limits

- Independent time-base accuracy, asynchronous pulse limits, analog accuracy,
  distortion and bandwidth remain uncharacterized.
- Timing results cover the listed loads, not every waveform or scheduling condition.
- FIFO/direct-mode tests establish software handling, not hardware fault generation.
- Debugger halts freeze TIM6. Backpressure snapshots briefly halted the CPU; DAC
  sequencing used manual timer events. Neither proves uninterrupted analog timing.
