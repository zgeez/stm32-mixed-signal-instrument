# STM32 Mixed-Signal Instrument

A PC-controlled waveform generator, oscilloscope and logic analyzer built around
an STM32F407G-DISC1.

**Status:** the two-channel AWG covers 1 Hz to 20 kHz on PA4 and PA5. The desktop
application controls both outputs and captures two analog inputs on PC4 and PC5 at
100 kS/s to 1 MS/s. Analog characterization remains open.

## Platform

- STM32F407VGT6, Cortex-M4F, 168 MHz
- C, STM32 HAL, CMake, Ninja and Arm GNU Toolchain
- Python desktop package with a PySide6 interface
- Native USB CDC for device control and finite capture transfer

## Repository

| Directory | Contents |
| --- | --- |
| `firmware/` | AWG application, host C tests, CubeMX initialization and vendor drivers |
| `desktop/` | Python package and host tests |
| `protocol/` | Shared communication contract |
| `docs/` | Architecture and roadmap |
| `scripts/` | Host validation |

## Device control

The desktop application and CLI use the native CDC port on CN5, separate from
ST-LINK. Install with `python -m pip install ./desktop`, then run:

```text
stm32-msi-gui
```

The CLI remains available for direct checks:

```text
stm32-msi --port COM5 status
stm32-msi --port COM5 stop
stm32-msi --port COM5 configure triangle 500
stm32-msi --port COM5 start
```

Replace COM5 with the enumerated CDC port. [Protocol](protocol/README.md)

## Scope

The oscilloscope captures 64 to 2048 simultaneous sample pairs from PC4 and PC5.
It supports free-run, rising and falling triggers, adjustable pre-trigger position,
single or continuously refreshed plots, time/div and volts/div scaling, pan/zoom,
and basic voltage and timing measurements.
Logic inputs are planned.

This is an unprotected low-voltage prototype. Inputs must stay within the board's
actual supply/reference limits. No mains, negative-voltage or automotive inputs.

[Architecture](docs/architecture/OVERVIEW.md) | [Roadmap](docs/PLAN.md) | [Validation](docs/validation.md)
