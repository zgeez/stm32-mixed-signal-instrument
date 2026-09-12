# Roadmap

| Milestone | Deliverable | Acceptance evidence |
| --- | --- | --- |
| 0. Bring-up | CubeMX/CMake firmware, SWD debug, Python package | Build, flash verification, breakpoints and clock registers |
| 1. Basic AWG | TIM6-triggered DAC DMA; sine, triangle, square | Frequency checks, restart tests, zero underruns |
| 2. USB | CDC control, versioned framing, desktop transport/model | C/Python conformance tests, malformed input and reconnect tests |
| 3. Desktop foundation | Device connection, AWG controls, status and errors | GUI tests, responsive serial operations and live board control |
| 4. Improved AWG | Second DAC, DDS, arbitrary tables, amplitude/offset/phase and matching controls | Algorithm, UI and refill-deadline tests |
| 5. Oscilloscope | Timer-triggered ADC DMA with plots, triggering and measurements | Sample-rate, loopback, plot and overrun tests |
| 6. Logic analyzer | GPIO DMA capture with digital traces and decoders | Pattern, pulse, decoder and sampling-jitter tests |
| 7. Integration | FreeRTOS ownership with unified device/session UI | Concurrent-load, reconnect, queue and responsiveness tests |
| 8. Mixed capture | Common analog/digital timeline and synchronized display | Measured skew, jitter and display alignment |
| 9. Characterization | Measured limits, error budgets and performance reports | Repeatable measurements with configuration and equipment recorded |
| 10. Distribution | Packaged desktop releases, firmware installation and compatibility checks | Clean-machine install, flash, verification, reconnect and upgrade tests |

Milestones 0 through 5 pass their host and board checks. Analog accuracy and bandwidth
characterization remain in milestone 9. See [validation](validation.md).

ADC progression: 100 kS/s, 500 kS/s, then 1 MS/s if validated. GPIO acquisition
starts at 1 MS/s, followed by 2 and 5 MS/s; 10 MS/s is an experiment. These are
validation targets, not specifications. Higher ADC rates require a clock review.

Each firmware milestone includes its desktop controls and host tests. Validate each
subsystem before concurrent operation. Board measurements are recorded separately.
