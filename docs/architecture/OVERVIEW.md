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
| DMA | DAC1: DMA1 S5 C7; DAC2: DMA1 S6 C7; ADC pair: DMA2 S0 C0 |
| Board control | PD4 low holds audio codec in reset; PE3 high deselects motion sensor; PC0 high disables USB host power switch |
| Debug | PA13/PA14 SWD; SysTick HAL timebase |
| Status LED | Green LD4 on PD12; off when idle, slow blink while active, fast blink on fault |
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

## Oscilloscope

ADC1 and ADC2 sample PC4 and PC5 together from TIM2. DMA stores the combined ADC
data register as packed 32-bit pairs. A raw block twice the requested capture length
allows the foreground trigger search to keep the requested pre-trigger history. The
DMA completion callback stops TIM2 before the circular stream can overwrite the block.
Captures contain 64..2048 pairs and stop before USB transfer.

Free-run, rising and falling triggers are supported on either channel. Missing edges
rearm acquisition and have a separate counter from ADC overruns and DMA errors. The
desktop application reads completed captures in 12-pair packets, plots both channels
against the trigger time and calculates basic voltage and timing measurements. Live
view repeats this finite capture and transfer cycle, with refresh rate set by capture
length and USB transfer time. The plot appends each capture to a scrolling captured-time
axis while retaining a bounded history.

## Planned logic acquisition

| Function | Candidate | Constraint |
| --- | --- | --- |
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

DMA buffers share 128 KiB with globals, stack and heap. Scope capture storage uses
24 KiB at its maximum length. CCM is CPU-only.

Two ADC channels at 1 MS/s in 16-bit containers produce 4 MB/s. USB Full Speed is
limited to 1.5 MB/s before overhead, so high-rate acquisition needs finite captures.

## Software boundaries

`App/control` parses commands in the foreground. CDC receives one 64-byte packet
at a time and defers rearming until consumption. TX storage remains owned by USB
until completion. Reset/deconfiguration clears session data; the AWG keeps running.
The LED uses a nonblocking tick check. FreeRTOS is deferred until integration.

The CLI and PySide6 application call the same instrument model over a framed serial
transport. Serial requests and capture transfer run on one Qt worker thread so they
cannot block the interface. Scope display scaling stays in the UI: time/div sets a
ten-division window, volts/div sets an eight-division window, and manual pan or zoom
pauses live following. The [protocol](../../protocol/README.md) defines commands and
errors.

## References

- [RM0090: reference manual](https://www.st.com/resource/en/reference_manual/rm0090-stm32f407-advanced-armbased-32bit-mcus-stmicroelectronics.pdf): bus topology, DMA request tables, ADC/DAC and timers.
- [DS8626: STM32F407 datasheet](https://www.st.com/resource/en/datasheet/stm32f407vg.pdf): pin mappings and electrical limits.
- [UM1472: board manual](https://www.st.com/resource/en/user_manual/um1472-discovery-kit-with-stm32f407vg-mcu-stmicroelectronics.pdf): board connections and headers.
- [MB997 E-01 schematic](https://www.st.com/resource/en/schematic_pack/mb997-f407vgt6-e01_schematic.pdf): audio, motion sensor and USB wiring.
- [AN4031: DMA](https://www.st.com/resource/en/application_note/an4031-using-the-stm32f2-stm32f4-and-stm32f7-series-dma-controller-stmicroelectronics.pdf): arbitration and transfer latency.
- [AN4566: DAC performance](https://www.st.com/resource/en/application_note/an4566-how-to-extend-the-dac-performance-on-stm32-mcus-stmicroelectronics.pdf): update-rate limits and high-speed output stages.
