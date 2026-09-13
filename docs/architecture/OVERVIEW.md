# Architecture

## Firmware configuration

STM32F407VGT6, generated with STM32CubeMX 6.18.1 and STM32CubeF4 1.28.3.
CubeMX owns pins, clocks and initialization. Application modules live in `App/`,
outside `Core/`; integration remains in generated USER CODE regions.

| Resource | Configuration |
| --- | --- |
| Clock | 8 MHz HSE; PLL M=8, N=336, P=2, Q=7 |
| Buses | HCLK 168 MHz; APB1 42 MHz; APB2 84 MHz |
| TIM6 | 84 MHz timer clock; PSC=0, ARR=209; 400 kHz update TRGO |
| DAC1/2 | PA4/PA5, TIM6 trigger, output buffers enabled |
| ADC1/2 | PC4/PC5, regular simultaneous IN14/15; 21 MHz ADC clock |
| TIM2 | 84 MHz timer clock; TRGO at 100, 500 or 1000 kS/s |
| TIM1 | 168 MHz timer clock; update event requests each logic sample |
| TIM3 | 84 MHz timer clock; PWM reference output on PC6, 1 Hz to 42 MHz |
| Logic 0..7 | PE7..PE14, GPIOE inputs with pull-downs so unconnected channels read low |
| DMA | DAC1: DMA1 S5 C7; DAC2: DMA1 S6 C7; ADC pair: DMA2 S0 C0; logic: DMA2 S5 C6 |
| Board control | PD4 low holds audio codec in reset; PE3 high deselects motion sensor; PC0 high disables USB host power switch |
| Debug | PA13/PA14 SWD; SysTick kernel tick, TIM7 HAL timebase |
| Status LED | Green LD4 on PD12; off when idle, slow blink while active, fast blink on fault |
| USB device | OTG_FS CDC, CN5; PA9 VBUS, PA11 DM, PA12 DP; 48 MHz PLLQ, IRQ priority 6 |

## Signal paths

| Function | Data path | Buffer / limits |
| --- | --- | --- |
| AWG | TIM6 -> DAC1/2, circular DMA, 32-bit DDS | 1024 samples/channel; 512-sample halves; 1.28 ms refill deadline |
| Scope | TIM2 -> simultaneous ADC1/2 -> packed 32-bit DMA pairs | 64..2048 pairs; raw buffer is twice capture length |
| Logic | TIM1 -> DMA read of GPIOE IDR -> D0..D7 | 64..4096 samples; raw buffer is twice capture length |
| Reference | TIM3 PWM -> PC6 | 1 Hz..42 MHz requested; status reports programmed rate |

AWG supports sine, triangle, square, sawtooth, DC and 2..256-entry arbitrary tables
at 1 Hz..20 kHz. Boot starts a 1 kHz sine on PA4. Amplitude is peak-to-peak and
offset is the center, both relative to DAC full scale; out-of-range combinations
are rejected. Arbitrary scaling is cached while stopped.

Both DMA streams must release a half before refill. Each callback faults and stops
TIM6 if the opposite half is unfinished. IRQ latency can allow stale samples before
shutdown. Cycle counters measure callback-to-refill latency and reset on Start.
PA4's audio connection can load DAC1; PA5 shares the deselected sensor's clock trace.

Scope and logic stop sampling before USB transfer. Missing triggers rearm and count
separately from DMA faults. Scope supports free-run and edge triggers; logic also
supports masked-pattern entry. Live scope view appends finite captures on a
cumulative captured-time axis, excluding transfer gaps.

Logic rates are 1, 2, 4.941 and 9.882 MS/s for requests of 1, 2, 5 and 10 MS/s.
GPIO reads occur when DMA gets bus access, not exactly at the timer edge. Pulses
can be missed without an error flag; asynchronous pulse limits remain uncharacterized.
The 10 MS/s setting is experimental.

The ADC runs at 21 MHz: 15 conversion cycles give a calculated 1.4 MS/s ceiling.
Source settling may require lower rates. Analog accuracy remains uncharacterized.

## Tasks and ownership

FreeRTOS 10 / CMSIS-RTOS v2 is vendored from CubeF4 under
`Middlewares/Third_Party/`. CubeMX owns peripherals; SysTick serves the kernel,
TIM7 the HAL.

| Task | Priority | Work | Wakeup |
| --- | --- | --- | --- |
| awg | High | DAC buffer refill | DMA half/full completion |
| acquire | AboveNormal | Scope/logic trigger search and capture processing | DMA completion/error |
| control | Normal | USB framing and commands | CDC RX/TX completion |
| status | Low | LD4 | Every 50 ms |

ISRs notify tasks; they do not render samples or parse commands. RTOS-aware
peripheral IRQs use priorities 5 or 6, with the syscall threshold at 5.
Hardware timers set sampling rates independently of task scheduling.

The acquisition arbiter permits scope or logic, never both. Arm claims ownership;
Stop or fault releases it. Complete retains ownership for reading/rearming.
Conflicting requests return busy and increment the refusal count.

## Memory and transport

| Memory | Size | Use |
| --- | --- | --- |
| SRAM1, 0x20000000 | 112 KiB | DMA buffers, globals, stacks and heap |
| SRAM2, 0x2001C000 | 16 KiB | Same DMA-accessible pool |
| CCM, 0x10000000 | 64 KiB | CPU only; DMA cannot access it |

Maximum capture storage: scope 24 KiB, logic 20 KiB. The FreeRTOS heap is 16 KiB.
Dual ADC at 1 MS/s produces 4 MB/s, exceeding USB Full Speed's 1.5 MB/s raw limit;
high-rate acquisition therefore uses finite captures.

CDC consumes one 64-byte packet before rearming RX and retains TX buffers until
completion. USB reset clears session data; AWG output continues.
See the [protocol](../../protocol/README.md) for layouts and error handling.

## Desktop

UI -> instrument model -> protocol -> serial transport. A Qt worker handles USB;
the host computes measurements and UART/SPI/I2C decoding. Scope navigation uses
ten horizontal and eight vertical divisions; horizontal pan/zoom pauses live following.

Measured performance and remaining limits are in [validation](../validation.md).

## References

- [RM0090: reference manual](https://www.st.com/resource/en/reference_manual/rm0090-stm32f407-advanced-armbased-32bit-mcus-stmicroelectronics.pdf): bus topology, DMA request tables, ADC/DAC and timers.
- [DS8626: STM32F407 datasheet](https://www.st.com/resource/en/datasheet/stm32f407vg.pdf): pin mappings and electrical limits.
- [UM1472: board manual](https://www.st.com/resource/en/user_manual/um1472-discovery-kit-with-stm32f407vg-mcu-stmicroelectronics.pdf): board connections and headers.
- [MB997 E-01 schematic](https://www.st.com/resource/en/schematic_pack/mb997-f407vgt6-e01_schematic.pdf): audio, motion sensor and USB wiring.
- [AN4031: DMA](https://www.st.com/resource/en/application_note/an4031-using-the-stm32f2-stm32f4-and-stm32f7-series-dma-controller-stmicroelectronics.pdf): arbitration and transfer latency.
- [AN4566: DAC performance](https://www.st.com/resource/en/application_note/an4566-how-to-extend-the-dac-performance-on-stm32-mcus-stmicroelectronics.pdf): update-rate limits and high-speed output stages.
