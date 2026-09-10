# Roadmap

| Milestone | Deliverable | Acceptance evidence |
| --- | --- | --- |
| 0. Bring-up | CubeMX/CMake firmware, SWD debug, Python package | Build, flash verification, breakpoints and clock registers |
| 1. Basic AWG | TIM6-triggered DAC DMA; sine, triangle, square | Frequency checks, restart tests, zero underruns |
| 2. Improved AWG | Second DAC, DDS, arbitrary tables, amplitude/offset/phase | Algorithm tests and refill-deadline measurements |
| 3. USB | CDC control, versioned framing, desktop transport/model | C/Python conformance tests, malformed input and reconnect tests |
| 4. Oscilloscope | Timer-triggered ADC DMA, finite/live capture, triggering | Sample counts/rates, loopback, pre-trigger and overrun tests |
| 5. Logic analyzer | Eight GPIO inputs sampled through DMA2 | Pattern captures, pulse detection and sampling-jitter measurements |
| 6. Integration | FreeRTOS orchestration and resource ownership | Concurrent-load tests, bounded queues, stack/RAM measurements |
| 7. Mixed capture | Common analog/digital timeline | Measured skew and jitter |
| 8. Desktop | Plots, measurements, FFT, decoders and export | Synthetic-signal tests and responsive UI under load |

Milestone 0 is validated: firmware builds, flash verification, reset/debug and LED
heartbeat pass on the board. No waveform application is implemented.

ADC progression: 100 kS/s, 500 kS/s, then 1 MS/s if validated. GPIO acquisition
starts at 1 MS/s, followed by 2 and 5 MS/s; 10 MS/s is an experiment. These are
validation targets, not specifications. Higher ADC rates require a clock review.

Each subsystem is validated independently before concurrent operation. Physical
results must identify configuration, equipment, duration, uncertainty and error
counts. Host CI does not perform hardware-in-the-loop testing.
