# Architecture

## Firmware configuration

STM32F407VGT6, generated with STM32CubeMX 6.18.1 and STM32CubeF4 1.28.3.
CubeMX owns pins, clocks and initialization. Application modules will live outside
`Core/`; integration remains in generated USER CODE regions.

| Resource | Configuration |
| --- | --- |
| Clock | 8 MHz HSE; PLL M=8, N=336, P=2, Q=7 |
| Buses | HCLK 168 MHz; APB1 42 MHz; APB2 84 MHz |
| TIM6 | 84 MHz timer clock; PSC=0, ARR=839; update TRGO |
| DAC1 | PA4, TIM6 trigger, output buffer enabled |
| DMA | DMA1 Stream 5 Channel 7; circular, half-word, memory-to-peripheral |
| Board control | PD4 low holds audio codec in reset; PE3 high deselects motion sensor; PC0 high disables USB host power switch |
| Debug | PA13/PA14 SWD; SysTick HAL timebase |
| Heartbeat | Green LD4 on PD12; toggles every 500 ms through the HAL tick |

The configured timer update rate is 100 kHz. TIM6 and DAC DMA remain stopped until
application code starts them. A 100-sample LUT would produce a calculated 1 kHz
fundamental; output quality and frequency accuracy remain unmeasured.

## Planned acquisition resources

| Function | Candidate | Constraint |
| --- | --- | --- |
| Analog CH1/CH2 | PC4/PC5, ADC1/2 IN14/15 | No ADC3 mapping; triple interleaving needs another pin |
| DAC CH2 | PA5 | Shares the motion sensor's SPI clock connection |
| Scope timing | TIM2 TRGO, ADC DMA2 S0 C0 | TIM6 is not a regular ADC trigger |
| Logic 0..7 | PE7..PE14, GPIOE IDR | Half-word reads, then `(sample >> 7) & 0xff` |
| Logic DMA | TIM1 update, DMA2 S5 C6 | Bus latency affects sampling instant; rate must be measured |
| USB | Native OTG_FS, CN5 | Separate from ST-LINK on CN1 |

PA4 shares an audio connection. Codec reset prevents audio operation but does not
remove electrical loading. Pin availability and optional audio routing must match
the actual MB997 board revision.

DMA2 can reach AHB1 GPIO through its peripheral port; DMA1 cannot. Timer requests
pace peripheral-to-memory reads from GPIO IDR. GPIO has no sample FIFO, so bus
contention can introduce jitter or missed samples without an ADC-style overrun flag.

With PCLK2=84 MHz, ADC /4 gives 21 MHz; /2 exceeds the 36 MHz ADC limit. At the
minimum 15 conversion cycles, the calculated ceiling is 1.4 MS/s per ADC. Input
settling may require longer sampling. Datasheet conversion rates are not analog
bandwidth or measured instrument specifications.

## Memory and throughput

| Region | Base | Size | Use |
| --- | --- | --- | --- |
| SRAM1 | 0x20000000 | 112 KiB | DMA buffers and shared state |
| SRAM2 | 0x2001C000 | 16 KiB | DMA buffers and shared state |
| CCM | 0x10000000 | 64 KiB | CPU-only data; inaccessible to DMA |

The DMA buffer budget is within 128 KiB, after globals, stacks, queues and heap.
Buffers require aligned storage and exclusive ownership through DMA and USB
completion. There is no M7-style data-cache maintenance requirement on this MCU.

Two ADC channels at 1 MS/s in 16-bit containers generate 4 MB/s. USB Full Speed's
12 Mbit/s line rate is only 1.5 MB/s before overhead. High-rate operation therefore
uses finite SRAM captures followed by transfer. Continuous mode must stay below
measured sustained USB throughput. Buffering cannot fix a sustained rate mismatch.

## Software boundaries

Timers determine sampling and output timing. DMA interrupts acknowledge events and
publish completed buffers; foreground code handles control and processing.
FreeRTOS will coordinate ownership and queues when concurrency requires it.

Desktop dependencies follow UI -> instrument model -> protocol -> transport.
The UI consumes captures and status; it does not parse USB bytes. Only the package
entry point exists at present.

## References

- [RM0090: reference manual](https://www.st.com/resource/en/reference_manual/rm0090-stm32f407-advanced-armbased-32bit-mcus-stmicroelectronics.pdf): bus topology, DMA request tables, ADC/DAC and timers.
- [DS8626: STM32F407 datasheet](https://www.st.com/resource/en/datasheet/stm32f407vg.pdf): pin mappings and electrical limits.
- [UM1472: board manual](https://www.st.com/resource/en/user_manual/um1472-discovery-kit-with-stm32f407vg-mcu-stmicroelectronics.pdf): board connections and headers.
- [MB997 E-01 schematic](https://www.st.com/resource/en/schematic_pack/mb997-f407vgt6-e01_schematic.pdf): audio, motion sensor and USB wiring.
- [AN4031: DMA](https://www.st.com/resource/en/application_note/an4031-using-the-stm32f2-stm32f4-and-stm32f7-series-dma-controller-stmicroelectronics.pdf): arbitration and transfer latency.
