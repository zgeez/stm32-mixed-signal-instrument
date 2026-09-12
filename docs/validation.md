# Validation

STM32F407G-DISC1, STM32CubeF4 1.28.3, Arm GNU 14.3.1. Board checks use ST-LINK/GDB
and Debug firmware unless stated otherwise. Host tests do not validate analog output.

## Automated checks

- Debug/Release firmware builds and native C tests pass.
- AWG tests cover DDS frequency arithmetic, six waveform modes, scaling, phase and arbitrary tables.
- Refill tests cover dual-DMA ownership and missed-deadline detection.
- Shared C/Python vectors cover framing, fragmentation and malformed input.
- USB middleware stubs test backpressure, TX lifetime, partial-frame expiry and reset.
- Python tests cover command encoding, reply correlation, errors and timeouts.
- GUI tests cover AWG controls, scope and logic controls and plots, connection state and
  stable polling.
- Logic tests cover edge and pattern triggering, channel extraction, pulse and jitter
  measurement, and UART, SPI and I2C decoding of synthetic streams.

Milestone 5 host checks: 95 Python tests and five native C suites pass. They cover
scope triggering, framing, chunked capture decoding, measurements and GUI behavior.
Debug firmware uses 36,208 bytes RAM and 53,116 bytes flash; Release uses 36,200 bytes
RAM and 29,332 bytes flash.

Milestone 6 host checks: 137 Python tests and six native C suites pass. They add logic
edge and pattern triggering, the LOGIC command set and its shared vectors, chunked
byte-packed capture decoding, pulse and jitter measurement, protocol decoding and the
logic GUI. Debug firmware uses 56,896 bytes RAM and 55,972 bytes flash; Release uses
56,888 bytes RAM and 31,016 bytes flash. These are host checks only; no board
measurement of logic acquisition has been made.

## Board checks — 2026-09-10 to 2026-09-11

| Check | Result |
| --- | --- |
| Bring-up | Flash readback, clock registers, breakpoints and LED heartbeat passed |
| AWG sustained run | Sine, triangle and square at calculated 1 kHz; zero errors over 120 heartbeat intervals per shape (~60 s target runtime) |
| Timer configuration | Dividers checked at 1 Hz and 1 kHz |
| DAC sequencing | 202 output-register samples matched, including startup and two table wraps |
| AWG control | Invalid/active configuration rejected; ten stop/start cycles passed |
| Forced DMA starvation | One underrun stopped TIM6; stop/configure/start recovered |
| USB firmware | Flash verified; foreground loop and AWG startup passed |
| USB CDC | COM4 enumeration, HELLO, capabilities, status, configuration, start/stop and error replies passed |
| USB load | 300 status requests over 18.75 s while AWG ran; zero underruns/DMA errors |
| USB robustness | Bytewise/combined frames, oversized input, version rejection, partial timeout and ten reconnects passed |
| Desktop session | Native COM4 prioritized; threaded HELLO, capabilities and status exchange passed |
| Dual DDS | PA4 sine and PA5 triangle ran at 20 kHz and 400 kS/s; 300 alternating status requests completed with zero underruns, DMA errors or refill misses |
| Arbitrary playback | Five-sample table uploaded, committed and reported running at 321.125 Hz |
| Scope capture | 256 simultaneous pairs completed at 100, 500 and 1000 kS/s; a 2048-pair capture completed at 1 MS/s |
| Scope trigger retry | An unreachable rising edge rearmed repeatedly; overrun and DMA error counters remained zero |
| AWG loopback | PA4/PC4 sine measured 10.000, 10.001 and 10.016 kHz; PA5/PC5 triangle measured 15.000, 14.985 and 14.999 kHz at the three sample rates |
| Channel alignment | Identical 5 kHz outputs had zero-sample lag and 0.999997 correlation at 500 kS/s |
| Scope triggering | Rising and falling crossings landed at requested sample indices 64 and 192 |
| Live view | Five 64-pair captures refreshed in 0.56 s (~9 updates/s); scrolling history, scaling, stable controls and Stop behavior passed |
| Forced ADC overrun | Disabling DMA2 during capture entered fault state and incremented the overrun counter; a reset restored clean capture |

Debugger halts freeze TIM6. These checks establish digital behavior, not uninterrupted
analog timing. DAC sequence checks used manually generated TIM6 update events.

## Open measurements

Absolute frequency and voltage accuracy, distortion, analog bandwidth and refill timing
margins remain unmeasured. The loopback checks share the MCU clock and analog path, so
they establish function and channel alignment rather than calibrated performance.

Logic acquisition has no board measurement yet. The following are required before any
sampling rate is treated as usable rather than requested:

| Measurement | Why |
| --- | --- |
| Highest rate that captures a known pattern without loss | GPIO DMA has no sample-loss flag, so a completed transfer is not proof of capture |
| Minimum reliable pulse width at each rate | A pulse shorter than one interval can fall entirely between reads |
| Edge-position variation against a reference source | Bus arbitration moves the sampling instant away from the timer edge |
| Behavior with the scope running concurrently | Both acquisitions master DMA2 and contend for the bus |
| Whether DMA FIFO errors actually appear when sampling is too fast | The overrun counter is only useful if the flag fires in the case it claims to detect |

Patterns for these checks must place transitions at varied phase relative to the
sampler. A single alternating pattern can align with the sampling instant and hide a
timing problem.
