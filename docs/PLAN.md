# Roadmap

| Milestone | Deliverable | Acceptance evidence |
| --- | --- | --- |
| 0. Bring-up | CubeMX/CMake firmware, SWD debug, Python package | Build, flash verification, breakpoints and clock registers |
| 1. Basic AWG | TIM6-triggered DAC DMA; sine, triangle, square | Frequency checks, restart tests, zero underruns |
| 2. USB | CDC control, versioned framing, desktop transport/model | C/Python conformance tests, malformed input and reconnect tests |
| 3. Improved AWG | Second DAC, DDS, arbitrary tables, amplitude/offset/phase | Algorithm tests and refill-deadline measurements |
| 4. Oscilloscope | Timer-triggered ADC DMA, finite/live capture, triggering | Sample counts/rates, loopback, pre-trigger and overrun tests |
| 5. Logic analyzer | Eight GPIO inputs sampled through DMA2 | Pattern captures, pulse detection and sampling-jitter measurements |
| 6. Integration | FreeRTOS orchestration and resource ownership | Concurrent-load tests, bounded queues, stack/RAM measurements |
| 7. Mixed capture | Common analog/digital timeline | Measured skew and jitter |
| 8. Desktop | Plots, measurements, FFT, decoders and export | Synthetic-signal tests and responsive UI under load |

Bring-up and AWG digital checks pass. USB communication is the next milestone.
Analog output is not yet characterized. See [validation](validation.md).

ADC progression: 100 kS/s, 500 kS/s, then 1 MS/s if validated. GPIO acquisition
starts at 1 MS/s, followed by 2 and 5 MS/s; 10 MS/s is an experiment. These are
validation targets, not specifications. Higher ADC rates require a clock review.

Validate each subsystem before concurrent operation. CI covers host tests and
firmware compilation; board measurements are recorded separately.
