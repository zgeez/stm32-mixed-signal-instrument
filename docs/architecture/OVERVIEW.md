# Architecture

## Firmware configuration

STM32F407VGT6, generated with STM32CubeMX 6.18.1 and STM32CubeF4 1.28.3.
CubeMX owns pins, clocks and initialization. Application modules live in `App/`,
outside `Core/`; integration remains in generated USER CODE regions.

| Resource | Configuration |
| --- | --- |
| Clock | 8 MHz HSE; PLL M=8, N=336, P=2, Q=7 |
| Buses | HCLK 168 MHz; APB1 42 MHz; APB2 84 MHz |
| TIM6 | 84 MHz timer clock; PSC=0, ARR=839; update TRGO |
| DAC1 | PA4, TIM6 trigger, output buffer enabled |
| DMA | DMA1 Stream 5 Channel 7; circular, half-word, memory-to-peripheral |
| Board control | PD4 low holds audio codec in reset; PE3 high deselects motion sensor; PC0 high disables USB host power switch |
| Debug | PA13/PA14 SWD; SysTick HAL timebase |
| Heartbeat | Green LD4 on PD12; nonblocking 500 ms tick check |
| USB device | OTG_FS CDC, CN5; PA9 VBUS, PA11 DM, PA12 DP; 48 MHz PLLQ, IRQ priority 6 |

## AWG

Boot starts a 1 kHz sine. Sine, triangle and 50% square use 100-sample tables
at integer frequency settings from 1 to 1000 Hz:

`f_out = 84 MHz / ((PSC + 1) * (ARR + 1) * 100)`

Timer rounding contributes less than 0.1% error across this range. Codes 512..3584
give an ideal average near VREF+/2 and peak-to-peak voltage of 0.75 VREF+.
Analog accuracy is unmeasured; PA4's audio connection can load the output.

`App/awg` owns TIM6, DAC1 and the 200-byte DMA table in main SRAM. Configuration
requires a stopped generator. DMA repeats the table without refill interrupts.
Errors stop TIM6 and latch FAULT; stop releases DMA before recovery. Counters persist
until reset. Stop disables the DAC; it does not hold PA4 at zero volts. Debug builds
freeze TIM6 while the core is halted.

## Planned acquisition resources

| Function | Candidate | Constraint |
| --- | --- | --- |
| Analog CH1/CH2 | PC4/PC5, ADC1/2 IN14/15 | No ADC3 mapping; triple interleaving needs another pin |
| DAC CH2 | PA5 | Shares the motion sensor's SPI clock connection |
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

The desktop CLI calls an instrument model over a framed serial transport.
The [protocol](../../protocol/README.md) defines commands and errors. GUI and
acquisition transfers are pending.

## References

- [RM0090: reference manual](https://www.st.com/resource/en/reference_manual/rm0090-stm32f407-advanced-armbased-32bit-mcus-stmicroelectronics.pdf): bus topology, DMA request tables, ADC/DAC and timers.
- [DS8626: STM32F407 datasheet](https://www.st.com/resource/en/datasheet/stm32f407vg.pdf): pin mappings and electrical limits.
- [UM1472: board manual](https://www.st.com/resource/en/user_manual/um1472-discovery-kit-with-stm32f407vg-mcu-stmicroelectronics.pdf): board connections and headers.
- [MB997 E-01 schematic](https://www.st.com/resource/en/schematic_pack/mb997-f407vgt6-e01_schematic.pdf): audio, motion sensor and USB wiring.
- [AN4031: DMA](https://www.st.com/resource/en/application_note/an4031-using-the-stm32f2-stm32f4-and-stm32f7-series-dma-controller-stmicroelectronics.pdf): arbitration and transfer latency.
