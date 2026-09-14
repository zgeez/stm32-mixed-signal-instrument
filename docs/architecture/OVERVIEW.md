# Architecture

STM32F407VGT6, generated with STM32CubeMX 6.18.1 and STM32CubeF4 1.28.3. CubeMX owns pins,
clocks and initialization; application modules live in `App/`.

## Peripherals

| Resource | Configuration |
| --- | --- |
| Clock | 8 MHz HSE; PLL M=8, N=336, P=2, Q=7 |
| Buses | HCLK 168 MHz; APB1 42 MHz; APB2 84 MHz |
| TIM6 | 84 MHz; PSC=0, ARR=209; 400 kHz update TRGO |
| DAC1/2 | PA4/PA5, TIM6 trigger, output buffers enabled |
| ADC1/2 | PC4/PC5, regular simultaneous IN14/15; 21 MHz clock, calculated 1.4 MS/s ceiling |
| TIM2 | 84 MHz; TRGO at 100, 500 or 1000 kS/s |
| TIM1 | 168 MHz; update event requests each logic sample |
| TIM3 | 84 MHz; PWM reference output on PC6, 1 Hz to 42 MHz |
| Timer link | TIM1 trigger output fires on enable; TIM2 follows through ITR0 for mixed capture |
| Logic 0..7 | PE7..PE14, GPIOE inputs with pull-downs so unconnected channels read low |
| DMA | DAC1: DMA1 S5 C7; DAC2: DMA1 S6 C7; ADC pair: DMA2 S0 C0; logic: DMA2 S5 C6 |
| Board control | PD4 low holds audio codec in reset; PE3 high deselects motion sensor; PC0 high disables USB host power switch |
| Debug | PA13/PA14 SWD; SysTick kernel tick, TIM7 HAL timebase |
| Status LED | Green LD4 on PD12; off idle, slow blink active, fast blink fault |
| USB device | OTG_FS CDC, CN5; PA9 VBUS, PA11 DM, PA12 DP; 48 MHz PLLQ, IRQ priority 6 |

## Signal paths

| Function | Data path | Buffer and limits |
| --- | --- | --- |
| AWG | TIM6 -> DAC1/2, circular DMA, 32-bit DDS | 1024 samples/channel; 512-sample halves; 1.28 ms refill deadline |
| Scope | TIM2 -> simultaneous ADC1/2 -> packed 32-bit DMA pairs | 64..2048 pairs; raw buffer twice capture length |
| Logic | TIM1 -> DMA read of GPIOE IDR -> D0..D7 | 64..4096 samples, raw buffer twice that; 1, 2, 4.941, 9.882 MS/s |
| Reference | TIM3 PWM -> PC6 | 1 Hz..42 MHz requested |
| Mixed | TIM1 TRGO -> TIM2 ITR0 releases both | shared origin; window origin per stream |

**AWG.** Sine, triangle, square, sawtooth, DC and 2..256-entry arbitrary tables; boot starts
a 1 kHz sine on PA4. Amplitude is peak-to-peak and offset the center, both relative to full
scale. A refill callback faults and stops TIM6 if the opposite half is unfinished.

**Scope and logic.** Normal DMA preserves each completed buffer and sampling stops before USB
transfer. Scope offers free-run and edge triggers, logic adds masked patterns; missing
triggers rearm and count separately from DMA faults.

**Mixed capture.** Only the nominated stream searches for an edge, so a follower that is not
free-running is refused; one that misses its trigger parks idle and the coordinator rearms
both. That policy lives in `mixed_policy.c`, free of HAL calls so it is host-testable.

Neither timer yields a sample at the release instant, so sample `i` sits at
`(window_origin + i + 1) / rate`. A shared origin is not a shared sampling instant, so skew
between the paths is measured, not assumed away; see [validation](../validation.md).

## Tasks and ownership

FreeRTOS 10 with CMSIS-RTOS v2, vendored from CubeF4 under `Middlewares/Third_Party/`.
SysTick serves the kernel, TIM7 the HAL.

| Task | Priority | Work | Wakeup |
| --- | --- | --- | --- |
| awg | High | DAC buffer refill | DMA half/full completion |
| acquire | AboveNormal | Trigger search and capture processing | DMA completion/error |
| control | Normal | USB framing and commands | CDC RX/TX completion |
| status | Low | LD4 | Every 50 ms |

ISRs only notify tasks. RTOS-aware IRQs use priority 5 or 6 with the syscall threshold at 5,
and hardware timers set sampling rates independently of scheduling.

The arbiter grants scope, logic or mixed, never more than one. Complete keeps ownership for
reading and rearming; conflicting requests return busy and increment the refusal count.

## Memory and transport

| Memory | Size | Use |
| --- | --- | --- |
| SRAM1, 0x20000000 | 112 KiB | DMA buffers, globals, stacks and heap |
| SRAM2, 0x2001C000 | 16 KiB | Same DMA-accessible pool |
| CCM, 0x10000000 | 64 KiB | CPU only; DMA cannot access it |

Capture storage is 24 KiB for scope and 20 KiB for logic; the FreeRTOS heap is 16 KiB. Dual
ADC at 1 MS/s produces 4 MB/s against USB Full Speed's 1.5 MB/s, so high-rate acquisition
uses finite captures. See the [protocol](../../protocol/README.md) for layouts and errors.

## Desktop

UI -> instrument model -> protocol -> serial transport. A Qt worker handles USB; the host
computes measurements and UART/SPI/I2C decoding. Flashing lives in `flashing.py`, shared by
the Flash button and `scripts/flash.py`, and drives an installed STM32CubeProgrammer because
ST's tool cannot be redistributed. The live scope view appends finite captures
on a cumulative time axis, excluding transfer gaps.

The window is one workspace: sources on the left, a single display on the right switching
between analog, digital and both on one timeline. A combined capture carries its own
acquisition settings with the arm, so it stands alone rather than inheriting whatever the
other views last pushed. Settings chosen once and the error counters sit behind Advanced.

## References

- [RM0090: reference manual](https://www.st.com/resource/en/reference_manual/rm0090-stm32f407-advanced-armbased-32bit-mcus-stmicroelectronics.pdf): bus topology, DMA request tables, ADC/DAC and timers.
- [DS8626: STM32F407 datasheet](https://www.st.com/resource/en/datasheet/stm32f407vg.pdf): pin mappings and electrical limits.
- [UM1472: board manual](https://www.st.com/resource/en/user_manual/um1472-discovery-kit-with-stm32f407vg-mcu-stmicroelectronics.pdf): board connections and headers.
- [MB997 E-01 schematic](https://www.st.com/resource/en/schematic_pack/mb997-f407vgt6-e01_schematic.pdf): audio, motion sensor and USB wiring.
- [AN4031: DMA](https://www.st.com/resource/en/application_note/an4031-using-the-stm32f2-stm32f4-and-stm32f7-series-dma-controller-stmicroelectronics.pdf): arbitration and transfer latency.
- [AN4566: DAC performance](https://www.st.com/resource/en/application_note/an4566-how-to-extend-the-dac-performance-on-stm32-mcus-stmicroelectronics.pdf): update-rate limits and high-speed output stages.
