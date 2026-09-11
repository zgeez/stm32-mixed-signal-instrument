# STM32 Mixed-Signal Instrument

A PC-controlled waveform generator, oscilloscope and logic analyzer built around
an STM32F407G-DISC1.

**Status:** basic waveform generation on PA4: sine, triangle and square, with
integer frequency settings from 1 to 1000 Hz. Startup selects a 1 kHz sine.
USB control is implemented and validated over the native CDC port. The desktop
application controls the current AWG. Acquisition and analog characterization
remain open.

## Platform

- STM32F407VGT6, Cortex-M4F, 168 MHz
- C, STM32 HAL, CMake, Ninja and Arm GNU Toolchain
- Python desktop package with a PySide6 interface
- Native USB CDC for device control; capture transfers planned

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

Planned features: two analog input channels, two internal DAC outputs and eight
digital inputs. Sampling and generation use timers and DMA; high-rate captures
are buffered in SRAM before transfer. Performance specifications are pending
characterization.

This is an unprotected low-voltage prototype. Inputs must stay within the board's
actual supply/reference limits. No mains, negative-voltage or automotive inputs.

[Architecture](docs/architecture/OVERVIEW.md) | [Roadmap](docs/PLAN.md) | [Validation](docs/validation.md)
