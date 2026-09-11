# Validation

STM32F407G-DISC1, STM32CubeF4 1.28.3, Arm GNU 14.3.1. Board checks use ST-LINK/GDB
and Debug firmware unless stated otherwise. Host tests do not validate analog output.

## Automated checks

- Debug/Release firmware builds and native C tests pass.
- AWG tests cover table shape, bounds and all 1..1000 Hz timer settings.
- Shared C/Python vectors cover framing, fragmentation and malformed input.
- USB middleware stubs test backpressure, TX lifetime, partial-frame expiry and reset.
- Python tests cover command encoding, reply correlation, errors and timeouts.
- GUI tests cover port selection, connection state, stable polling and AWG controls.

## Board checks — 2026-09-10

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

Debugger halts freeze TIM6. These checks establish digital behavior, not uninterrupted
analog timing. DAC sequence checks used manually generated TIM6 update events.

## Open measurements

Analog frequency, shape, amplitude and distortion remain unmeasured. A DC multimeter
can check the average near VREF+/2; it cannot establish waveform quality.
