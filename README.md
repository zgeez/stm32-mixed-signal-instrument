# STM32 Mixed-Signal Instrument

A PC-controlled waveform generator, oscilloscope and logic analyzer built around
an STM32F407G-DISC1.

**Status:** basic waveform generation on PA4: sine, triangle and square, with
integer frequency settings from 1 to 1000 Hz. Startup selects a 1 kHz sine.
USB control, acquisition and analog characterization remain open.

## Platform

- STM32F407VGT6, Cortex-M4F, 168 MHz
- C, STM32 HAL, CMake, Ninja and Arm GNU Toolchain
- Python desktop package; PySide6/pyqtgraph planned
- Native USB CDC planned for device control and capture transfers

## Repository

| Directory | Contents |
| --- | --- |
| `firmware/` | AWG application, host C tests, CubeMX initialization and vendor drivers |
| `desktop/` | Python package and host tests |
| `protocol/` | Shared communication contract |
| `docs/` | Architecture and roadmap |
| `scripts/` | Host validation |

## Scope

Planned features: two analog input channels, two internal DAC outputs and eight
digital inputs. Sampling and generation use timers and DMA; high-rate captures
are buffered in SRAM before transfer. Performance specifications are pending
characterization.

This is an unprotected low-voltage prototype. Inputs must stay within the board's
actual supply/reference limits. No mains, negative-voltage or automotive inputs.

[Architecture](docs/architecture/OVERVIEW.md) | [Roadmap](docs/PLAN.md) | [Validation](docs/validation.md)
