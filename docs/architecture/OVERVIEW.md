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
| DMA | DAC1: DMA1 S5 C7; DAC2: DMA1 S6 C7; circular half-word transfers |
| Board control | PD4 low holds audio codec in reset; PE3 high deselects motion sensor; PC0 high disables USB host power switch |
| Debug | PA13/PA14 SWD; SysTick HAL timebase |
| Heartbeat | Green LD4 on PD12; nonblocking 500 ms tick check |
| USB device | OTG_FS CDC, CN5; PA9 VBUS, PA11 DM, PA12 DP; 48 MHz PLLQ, IRQ priority 6 |

## AWG

Boot starts a 1 kHz sine on PA4. TIM6 supplies a fixed 400 kS/s trigger; each output
uses a 32-bit phase accumulator with 1 mHz configuration units. Sine, triangle, square,
sawtooth, DC and 2..256-sample arbitrary tables share the same 1 Hz to 20 kHz path.

Each channel owns a 1024-sample circular DMA buffer. Half-transfer and completion
interrupts release the inactive half only after every active DMA stream has crossed the
boundary. The foreground loop refills it; reuse before completion increments the refill
miss counter and stops TIM6. The 512-sample half gives a 1.28 ms refill deadline.

Amplitude is peak-to-peak and offset is the center, normalized to DAC full scale. Invalid
combinations that exceed codes 0..4095 are rejected. Both channels start from their
configured phase on the same timer. PA4's audio connection can load DAC1; PA5 also drives
the deselected motion sensor's clock trace. Analog accuracy remains unmeasured.

## Planned acquisition resources

| Function | Candidate | Constraint |
| --- | --- | --- |
| Analog CH1/CH2 | PC4/PC5, ADC1/2 IN14/15 | No ADC3 mapping; triple interleaving needs another pin |
| Scope timing | TIM2 TRGO, ADC DMA2 S0 C0 | TIM6 is not a regular ADC trigger |
| Logic 0..7 | PE7..PE14, GPIOE IDR | Half-word reads, then `(sample >> 7) & 0xff` |
| Logic DMA | TIM1 update, DMA2 S5 C6 | Bus latency affects sampling instant; rate must be measured |

DMA2 can read AHB1 GPIO; DMA1 cannot. GPIO has no sample FIFO, so bus contention
can cause jitter or missed samples without an overrun indication.

ADC /4 gives 21 MHz; /2 exceeds the 36 MHz limit. The minimum 15 conversion cycles
give a calculated 1.4 MS/s ceiling. Source settling may require slower sampling.

## Memory and throughput

| Region | Base | Size | Use |
| --- | --- | --- | --- |
| SRAM1 | 0x20000000 | 112 KiB | DMA buffers and shared state |
| SRAM2 | 0x2001C000 | 16 KiB | DMA buffers and shared state |
| CCM | 0x10000000 | 64 KiB | CPU-only data; inaccessible to DMA |

DMA buffers share 128 KiB with globals, stack and heap. CCM is CPU-only.

Two ADC channels at 1 MS/s in 16-bit containers produce 4 MB/s. USB Full Speed is
limited to 1.5 MB/s before overhead, so high-rate acquisition needs finite captures.

## Software boundaries

`App/control` parses commands in the foreground. CDC receives one 64-byte packet
at a time and defers rearming until consumption. TX storage remains owned by USB
until completion. Reset/deconfiguration clears session data; the AWG keeps running.
The LED uses a nonblocking tick check. FreeRTOS is deferred until integration.

The CLI and PySide6 application call the same instrument model over a framed serial
transport. Serial requests run on one Qt worker thread so timeouts cannot block the
interface. The [protocol](../../protocol/README.md) defines commands and errors.
Acquisition views and transfers are pending.

## References

- [RM0090: reference manual](https://www.st.com/resource/en/reference_manual/rm0090-stm32f407-advanced-armbased-32bit-mcus-stmicroelectronics.pdf): bus topology, DMA request tables, ADC/DAC and timers.
- [DS8626: STM32F407 datasheet](https://www.st.com/resource/en/datasheet/stm32f407vg.pdf): pin mappings and electrical limits.
- [UM1472: board manual](https://www.st.com/resource/en/user_manual/um1472-discovery-kit-with-stm32f407vg-mcu-stmicroelectronics.pdf): board connections and headers.
- [MB997 E-01 schematic](https://www.st.com/resource/en/schematic_pack/mb997-f407vgt6-e01_schematic.pdf): audio, motion sensor and USB wiring.
- [AN4031: DMA](https://www.st.com/resource/en/application_note/an4031-using-the-stm32f2-stm32f4-and-stm32f7-series-dma-controller-stmicroelectronics.pdf): arbitration and transfer latency.
- [AN4566: DAC performance](https://www.st.com/resource/en/application_note/an4566-how-to-extend-the-dac-performance-on-stm32-mcus-stmicroelectronics.pdf): update-rate limits and high-speed output stages.
