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
- GUI tests cover AWG controls, scope controls and plots, connection state and stable polling.

Milestone 5 host checks: 95 Python tests and five native C suites pass. They cover
scope triggering, framing, chunked capture decoding, measurements and GUI behavior.
Debug firmware uses 36,208 bytes RAM and 53,116 bytes flash; Release uses 36,200 bytes
RAM and 29,332 bytes flash.

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
