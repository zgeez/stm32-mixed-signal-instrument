# Validation Report

| | |
| --- | --- |
| Item under test | STM32F407G-DISC1 mixed-signal instrument, firmware and desktop application |
| MCU / SDK | STM32F407VGT6, STM32CubeMX 6.18.1, STM32CubeF4 1.28.3, Arm GNU 14.3.1 |
| Interfaces | ST-LINK SWD for programming, native USB CDC for control |
| Period | 2026-09-10 to 2026-09-14 |
| Coverage | Milestones 1-10 |

Loopback checks share the sampler's clock, so they verify function, not calibration.
Debug firmware unless a record states otherwise.

## 1. Summary

| ID | Area | Verdict |
| --- | --- | --- |
| V-01 | Host test suites and builds | Pass |
| V-02 | Boot, enumeration and GUI | Pass |
| V-03 | Acquisition ownership | Pass |
| V-04 | Scope acquisition | Pass |
| V-05 | Logic acquisition | Pass |
| V-06 | Trigger behaviour | Pass |
| V-07 | Concurrent AWG and acquisition | Pass |
| V-08 | Status latency | Pass |
| V-09 | Protocol robustness | Pass |
| V-10 | Reconnect and physical handling | Pass |
| V-11 | Analog output accuracy | Pass, uncalibrated |
| V-12 | Digital output and arbitrary patterns | Pass |
| V-13 | Serial protocol decoding | Pass, see L-3 |
| V-14 | Logic timing resolution | Pass |
| V-15 | Logic frequency and jitter | Pass |
| V-16 | AWG refill deadline and fault recovery | Pass |
| V-17 | AWG refill latency | Pass |
| V-18 | USB backpressure | Pass |
| V-19 | Mixed capture coordination | Pass |
| V-20 | Mixed capture timeline | Pass |
| V-21 | Analog-to-digital skew and jitter | Pass |
| V-22 | Capture window integrity | Pass after fixes |
| V-23 | Task stack and heap headroom | Pass |
| V-24 | Early bring-up | Pass |
| V-25 | Packaging and clean install | Pass |
| V-26 | Firmware installation and verification | Pass |
| V-27 | Version compatibility and upgrade | Pass |
| V-28 | Sample loss | Pass |

Open defects are listed in section 4, uncharacterized areas in section 5.

## 2. Configuration under test

| Milestone | Python tests | C suites | Debug RAM / flash | Release RAM / flash |
| --- | --- | --- | --- | --- |
| 5 | 95 | 5 | 36,208 / 53,116 | 36,200 / 29,332 |
| 6 | 137 | 6 | 56,896 / 55,972 | 56,888 / 31,016 |
| 7 | 164 | 8 | 75,960 / 75,448 | 75,952 / 41,512 |
| 8 | 185 | 9 | 75,984 / 77,144 | 75,976 / 42,312 |

Sizes in bytes. From milestone 7 the image includes a 16 KiB RTOS heap, the TIM3 reference
output and 1 KiB of cached arbitrary DAC codes.

## 3. Test records

### V-01 Host test suites and builds

**Method.** Python suite, native C suites, Ruff, Debug and Release firmware builds. The C
suites are also run a second time instrumented, once under AddressSanitizer and
UndefinedBehaviorSanitizer and once under gcov.

**Result.** 206 Python tests, Ruff and both firmware builds pass. The suites span DDS and
refill maths, protocol framing, USB backpressure, acquisition ownership, measurements,
UART/SPI/I2C decoding, mixed-capture alignment, flashing and GUI behaviour. All nine C suites
pass under MinGW and under MSVC, and CI builds them with GCC on Ubuntu.

The application's own firmware sources compile at `-Wall -Wextra -Werror` with no warnings.
The vendor code underneath is left at the generated settings deliberately: CubeMX rewrites
`Core/` and `Drivers/` wholesale and FreeRTOS is vendored unchanged, so treating a warning
there as an error would make the next regeneration a broken build.

| Instrumented pass | Result |
| --- | --- |
| ASan and UBSan, all nine suites | No finding. Verified non-vacuous: an injected heap overflow and an injected signed overflow are both caught and fatal. |
| gcov, application sources only | 92.8% of lines, 100% of functions, 80.5% of branches |

Coverage is quoted for the ten application sources the host suites compile. The six that
touch hardware directly are not unit tested at all and are excluded rather than counted as
misses, so the figure describes how well the testable code is tested, not how much of the
firmware is. Python coverage is 89% of 2,580 statements. CI fails either below 85%.

Building the C suites needs the toolchain's own directory on PATH; invoking the compiler by
absolute path alone leaves it unable to load the libraries it depends on. `testing.md`
carries the command for each toolchain.

**Verdict.** Pass.

### V-02 Boot, enumeration and GUI

**Method.** Cold boot, CDC enumeration, connect, poll, exercise every display mode.

**Result.** Four RTOS tasks started. Enumeration, connection, polling and all three display
modes passed. Re-checked after the interface was rebuilt around a single workspace: driving
the application's own widgets against the board, a 10 kHz square on PA5 read Vpp 2.933 V on
the analog view, the reference output was accepted, and a combined capture completed without
any other view having been run first.
LD4 off when idle, slow blink when active.

**Verdict.** Pass.

### V-03 Acquisition ownership

**Method.** Conflicting Arm requests, then repeated handovers between scope and logic.

**Result.** A conflicting Arm returns busy and increments the refusal count. 20 alternating
handovers passed.

**Verdict.** Pass.

### V-04 Scope acquisition

**Method.** Captures at each supported rate and depth over CDC.

**Result.** 100, 500 and 1000 kS/s; up to 2048 pairs; 512 pairs transferred in about 40 ms.

**Verdict.** Pass.

### V-05 Logic acquisition

**Method.** Captures at each supported rate and depth over CDC.

**Result.** Up to 4096 samples at actual 1, 2, 4.941 and 9.882 MS/s; 1024 samples transferred
in about 10 ms.

**Verdict.** Pass.

### V-06 Trigger behaviour

**Method.** Absent edges, held patterns and unreachable patterns on both instruments.

**Result.** Missing edges rearm and count separately from DMA faults. Held patterns do not
retrigger. Unreachable patterns produce no capture.

**Verdict.** Pass.

### V-07 Concurrent AWG and acquisition

**Method.** Both DAC channels at 20 kHz while capturing continuously.

**Result.** With scope, 435 captures in 20 s, zero errors. With logic, 115 captures of 4096
samples at 9.88 MS/s in 10 s, zero overruns.

**Verdict.** Pass.

### V-08 Status latency

**Method.** Status requests under AWG and capture load.

**Result.** Median 1.16 ms, p99 2.32 ms, maximum 2.38 ms.

Superseded. This predates the milestone 7 move of USB handling into a task, which introduced
D-4 and put a fixed 20 ms floor under every request. With that fixed the median is 0.22 ms;
see [characterization](characterization.md).

**Verdict.** Pass.

### V-09 Protocol robustness

**Method.** Malformed and partial frames, invalid commands, stale capture IDs, bytewise
delivery.

**Result.** All handled correctly, with no lockups or corrupted state.

**Verdict.** Pass.

### V-10 Reconnect and physical handling

**Method.** Ten disconnect and reconnect cycles; cable unplugged and replugged during
operation.

**Result.** All cycles passed. AWG output continued across reconnects and capture transfer
recovered. Unplugging mid-transfer surfaces a write error, and reconnecting resumes normally.

**Verdict.** Pass.

### V-11 Analog output accuracy

**Method.** DAC loopback to ADC, PA4 to PC4 and PA5 to PC5, VDDA entered as 3.300 V.
Recorded 2026-09-12.

**Result.** PA4 sine at 10 kHz, 75% FS: 10,000.372 Hz, Vpp 2.489 V against 2.475 V expected,
mean 1.657 V. PA5 triangle at 20 kHz, 60% FS: 20,001.423 Hz, Vpp 1.980 V.

**Verdict.** Pass. Absolute accuracy is not established; see L-1.

### V-12 Digital output and arbitrary patterns

**Method.** AWG driving logic inputs; arbitrary tables of 32 to 256 entries.

**Result.** D0 square at 10 kHz: 10.000 kHz, duty 50.1%, minimum high/low 50/49 us. D1 square
at 5 kHz: 5.000 kHz, duty 52.3%, minimum high/low 105/95 us. Pattern pin agreement 99.2 to
100%; identical channels agreed on every sample.

**Verdict.** Pass.

### V-13 Serial protocol decoding

**Method.** AWG-generated UART, SPI and I2C waveforms decoded on the host.

**Result.** UART at 20 kbaud: eight byte values decoded at 1, 2 and 4.94 MS/s, and a wrong
baud rate produced framing errors. SPI mode 0: three word sequences decoded, and a wrong
phase did not reproduce them. I2C: three read and write transfers decoded through address,
data, ACK and Stop. UART framing-error recovery is covered by host regression tests.

**Verdict.** Pass. See L-3.

### V-14 Logic timing resolution

**Method.** TIM3 PC6 to PE7, sharing the sampler's clock. Narrowest pulse whose measured high
and low durations stayed within one sample interval of nominal.

| Actual rate | Sample interval | Narrowest resolved pulse |
| --- | --- | --- |
| 1 MS/s | 1000 ns | 1000 ns |
| 2 MS/s | 500 ns | 500 ns |
| 4.941 MS/s | 202.4 ns | 250 ns |
| 9.882 MS/s | 101.2 ns | 101.2 ns |

**Result.** Across six captures per condition, with 200 kHz to 2 MHz sources sampled at least
twice per half-period, maximum reported jitter was 0.94 sample intervals.

**Verdict.** Pass. See L-2.

### V-15 Logic frequency and jitter

**Method.** 20 kHz square, eight 4096-sample captures per rate.

| Rate | Measured frequency | Max jitter (samples) | Max period error (samples) |
| --- | --- | --- | --- |
| 1 MS/s | 20.0000 kHz | 0.00 | 0.00 |
| 2 MS/s | 20.0000 kHz | 0.00 | 0.00 |
| 4.941 MS/s | 19.9997 kHz | 0.94 | 0.01 |
| 9.882 MS/s | 19.9997 kHz | 0.88 | 0.12 |

**Result.** Repeats under AWG and USB load at 1 and 9.88 MS/s showed unchanged jitter and
zero errors.

**Verdict.** Pass. See L-2.

### V-16 AWG refill deadline and fault recovery

**Method.** Dual arbitrary playback, injected faults and forced DMA errors. Recorded
2026-09-13; the dual-arbitrary regression also passed on 2026-09-12.

**Result.** 90 starts across 2, 17 and 256 entries at 1, 1000 and 20000 Hz, 3 s silent and
10 s of USB load, no added errors. Re-run after D-4 was fixed: the same 10 s now carries
20,471 paired status polls rather than 251, so refills survive 81 times the host traffic the
original run applied, still with no errors. Host tests cover both buffer halves, callback
orders and unfinished work; an injected ownership fault latched, and Stop then Start
recovered. A logic DMA read from inaccessible CCM raised a hardware error, released
ownership, and the next capture completed. Software-seeded FIFO and direct-mode error codes
incremented overruns and recovered.

Re-tested under maximum contention on the Release build with `scripts/check_contention.py`:
both channels playing 256-entry arbitrary tables at 20 kHz while a mixed capture drove the
ADC pair and the GPIO sampler, host polling throughout. 180 s, 2,598 captures, 25,615 polls.
The AWG never left the running state, no capture stalled, and not one counter moved. No
refill missed its 1.28 ms deadline, which extends the deadline evidence from the original
20 s Debug loads to a longer Release run under heavier load.

The FIFO and direct-mode DMA error flags did not fire. Keeping every stream busy at once is
the only lever available, because the DAC updates at a fixed 400 kS/s whatever waveform is
requested, so this bounds rather than closes L-4.

**Verdict.** Pass. See L-4 and L-5.

### V-17 AWG refill latency

**Method.** DWT cycle counters, dual 256-entry arbitrary tables at 20 kHz, about 20 s per
load. Counters reset on Start and were read after stopping output.

| Concurrent load | Transfers | Refills | Max callback-to-finish |
| --- | --- | --- | --- |
| Scope, 2048 pairs at 1 MS/s | 6 | 16,625 | 107,868 cycles / 642.07 us |
| Logic, 4096 samples at 9.88 MS/s | 11 | 15,843 | 106,766 cycles / 635.51 us |

**Result.** Zero errors. The largest observed latency leaves 637.93 us against the 1.28 ms
interval. Debugger-readable `refill_max_cycles` and `refill_count` reset on Start; cycles
divided by 168 gives microseconds.

**Verdict.** Pass. The measurement excludes IRQ entry and earlier HAL work, so it is not a
worst-case bound; see L-6.

### V-18 USB backpressure

**Method.** Stop reading the CDC endpoint while the AWG runs, then drain it.

**Result.** Writes blocked after 206 requests. TX stayed blocked for 60 s while AWG refills
continued. Draining 12,360 bytes restored requests without reconnecting or adding errors.

**Verdict.** Pass.

### V-19 Mixed capture coordination

**Method.** Arm mixed capture, attempt conflicting operations, then Stop. Release firmware,
2026-09-13.

**Result.** Mixed capture completes, holds acquisition as a single owner, and releases it on
Stop. A standalone Arm is refused while mixed holds the hardware, and a follower configured
to trigger is rejected. Both windows transfer whole and each reports its window origin. Zero
overruns and zero DMA errors.

Three desktop defects were found here after the board checks passed, all fixed with
regression tests that fail without the fix. The board checks missed them because they drive
the protocol directly in a tight loop and never exercise the application's polling path.

Confirmed in the application afterwards with one signal on both paths, PA5 to PC4 and PE7,
a 10 kHz sine at full scale. Analog 1.000 MS/s covering -286.89 to +224.11 us in 512
samples, digital 9.882 MS/s covering -207.24 to +207.14 us in 4096 samples, overlap
414.38 us, both spans matching their sample counts exactly and the restart count static.
The digital trigger edge at zero falls on the sine's rising slope, as one source driving
both paths should.

The status poll never reported mixed state at all. The unified device snapshot carries no
mixed fields, and mixed status was emitted only as a side effect of running a command, which
is precisely what stops happening between arming a capture and it completing. The one
emission that did report completion arrived while the arm command still held the busy flag,
which the read gate excludes, so the application never learned the capture was ready. The
poll now asks for mixed status separately while mixed owns the hardware, and for one poll
afterwards so a stop or fault is still delivered.

The same poll also fed stream state to the oscilloscope and logic panels unconditionally,
and each panel acts on a completed stream by reading it and then stopping it. During a mixed
capture that stopped a stream the coordinator was still using, so the device restarted the
pair and the samples were drawn in those two tabs while the mixed view stayed empty.
Observed in the application as a restart count climbing past 9,500 with no mixed capture
displayed. Those panels now display stream state without acting on it while mixed owns the
hardware.

Last, a failed mixed read left the panel's transfer flag set, so one failure blocked every
later read until the application reconnected. The flag is now cleared on error.

**Verdict.** Pass.

### V-20 Mixed capture timeline

**Method.** Scope at 1 MS/s and logic at 9.882 MS/s released from one event; edge spacing
compared against the known reference period.

**Result.** Scope covered 1.00 to 512.00 us, logic 0.10 to 414.48 us, overlap 413.48 us, and
the origin sat at 207.34 us. Edge spacing was exact to 0.002 samples across the window,
standalone and mixed, at every rate.

**Verdict.** Pass.

### V-21 Analog-to-digital skew and jitter

**Method.** PC6 reference wired to PC4 and PE7, so one edge reaches both paths. 210 mixed
captures with analog at 1 MS/s and digital at 9.882 MS/s, over seven reference frequencies
and three independent passes. Frequencies whose period is a whole number of analog samples
were excluded, because there the sampling phase locks and averaging gains nothing.

| Quantity | Measured |
| --- | --- |
| Mean skew | -119.7 ns |
| Median | -130.7 ns |
| Spread (sigma) | 293.7 ns |
| Range | -650.6 to +372.1 ns |
| Pass-to-pass variation | 82.2 ns |

**Result.** The reference edge is much faster than an analog sample interval, so both
straddling samples sit at the rails and interpolation returns their midpoint. Each
measurement is therefore wrong by up to half an interval, but unbiasedly, with a predicted
spread of one interval over the square root of twelve, 288.7 ns. The measured 293.7 ns
matches, so no jitter is resolvable above the quantisation floor; any present is bounded near
50 ns.

The -119.7 ns offset is the ADC sample and hold: three cycles at PCLK2/4 = 21 MHz is
142.9 ns. An analog code represents its input at the end of that aperture, while a digital
sample is the pin state at its trigger instant, so the analog edge is reconstructed early by
about that much. The two paths therefore share a timeline to within one ADC aperture.

For reference, the excluded case: 50 kHz against 1 MS/s is exactly 20 samples and read -460
and -552 ns in two runs, against roughly -150 ns for every incommensurate frequency.

**Verdict.** Pass. See L-7.

### V-22 Capture window integrity

**Method.** Known square reference captured across rate changes, trigger modes and pretrigger
settings, with run lengths compared against the reference period.

**Result.** Three defects were found here, all since fixed. The third is D-1.

Lowering the scope sample rate left the first conversion invalid: 8/8 captures going 1 MS/s
to 500 kS/s, 0/8 the other way, 0/8 for a re-arm or a sample-count change, and 0 in 1000 runs
with the rate held. A free-running window begins at that conversion, so it landed at window
sample zero, while a triggered window starts past it and was never affected. Forcing a timer
update before the ADC starts fixed it, leaving 0 anomalies in 2480 runs.

Host-side alignment ignored that no sample is taken at the release instant. Each stream's
first sample arrives on its timer's first update, one whole sample period after release. The
two rates differ, so omitting this pulled the streams apart by one digital period minus one
analog period, 899 ns between 1 MS/s and 9.882 MS/s. Measured on hardware, the analog edge
sat 1050 ns from the shared instant before the correction and 152 ns after it, at both
1 MS/s and 100 kS/s.

The remaining case, a mixed follower at 500 kS/s whose first sample was invalid 10/10 with
zero restarts, was traced afterwards to the ADC DMA running in circular mode: it keeps
writing once the transfer completes, so it could overwrite the start of the buffer before
the task stopped it, and that is the window's first sample. Switching the stream to normal
mode through the .ioc removed it. Re-measured with one AWG square on both paths, PA5 to PC4
and PE7: no truncated run in 1,260 runs across 60 captures, standalone and mixed, at every
rate and with the rate alternated before each capture.

**Verdict.** Pass.

### V-23 Task stack and heap headroom

**Method.** Minimum free stack and heap low-water mark read after sustained load.

**Result.** Minimum free stack: awg 1808, acquire 1864, control 2276, status 664 bytes. Heap
free and low water 5752 bytes.

**Verdict.** Pass.

### V-24 Early bring-up

**Method.** Recorded 2026-09-10 and 2026-09-11.

**Result.** Flash, clock and debug verification; 202 matching DAC register samples; ten AWG
restart cycles; dual DDS at 20 kHz; 300 USB status requests under load; scope trigger
positions; and forced DAC underrun and ADC overrun recovery all passed. Identical 5 kHz
loopback channels showed zero-sample lag and 0.999997 correlation. Live scope completed five
64-pair captures in 0.56 s with working Stop and scrolling.

**Verdict.** Pass.

### V-25 Packaging and clean install

**Method.** `scripts/build_release.py` builds a wheel, an sdist and a single Windows
executable carrying its own interpreter and the firmware image, and stages the image beside
them. The wheel was then installed into an empty virtual environment that shared nothing with
the development one.

**Result.** Wheel 66 KiB, sdist 77 KiB, and one 63.2 MiB executable carrying its own icon,
the firmware image and the interpreter. It reached a visible window 1.7 s after launch. The
bundle unpacks `firmware.elf` at 94,052 bytes and `resources/icon.ico` at 18,778 bytes, both
where the application looks for them, and the icon resolves at all seven sizes from 16 to
256 pixels. The fresh environment resolved numpy 2.5.3, pyqtgraph 0.14.0, pyserial 3.5 and
PySide6 6.11.2 from the declared ranges, created both console entry points, and the CLI
returned device status from the board.

One file rather than a folder and a zip, so what is downloaded is what runs. The startup cost
of unpacking on every launch is the price, and it was measured rather than assumed.

The first frozen build failed on launch: PyInstaller was pointed at `gui.py`, which runs it
as `__main__` with no package, so its relative imports raised ImportError. It now freezes a
launcher that imports the installed package instead.

A release is assembled by `.github/workflows/release.yml` on a `v*` tag: firmware, wheel and
sdist on Linux, the frozen application on Windows because PyInstaller freezes for the platform
it runs on, then one publish step. It refuses before building anything if the tag, the package
version and the firmware macros disagree, which was checked by running that step's script
against both a matching and a mismatched tag. Both split build invocations the jobs use were
run locally and produce the four assets the publish step expects.

**Verdict.** Pass.

### V-26 Firmware installation and verification

**Method.** `stm32_msi.flashing` locates STM32CubeProgrammer, writes and verifies the image,
then reconnects over the CDC port and asks the board what it is. Driven both from
`scripts/flash.py` and from the application's own Flash firmware button.

**Result.** From the command line, flash verified and the board answered `0.1.0 (a82d489)`,
matching the commit the image was built from. From the application, 7 of 7 checks passed on
hardware: it asked before overwriting, dropped the connection, wrote, verified, reported the
running version, reconnected, and showed no mismatch warning afterwards.

Failure is reported rather than assumed if the write is unverified, the port never answers,
or the version is older than expected. STM32CubeProgrammer is ST's tool and cannot be
redistributed, so the application locates an installed copy; when it finds none it says so
before asking anything else and offers to open ST's download page, rather than naming a
missing tool and leaving the user to search for it.

A verified download is not evidence that an image runs, which is why the two steps are one
command. An earlier version of this check looked for the verification line without passing
`-v`, so it silently reported failure on a good flash.

**Verdict.** Pass.

### V-27 Version compatibility and upgrade

**Method.** Flash the previous image, which predates the version command, connect with the
current application, then flash the current image and reconnect. Driven through the
application's own widgets.

**Result.** 9 of 9 checks passed.

| Firmware | Reported | Warning | Usable |
| --- | --- | --- | --- |
| Predates the version command | "unknown" | Shown, naming the expected version | Yes, a capture completed |
| Current | 0.1.0 (a82d489) | None | Yes |

Older firmware answers "unknown command" rather than failing the connection, so the session
continues and the reason stays on screen. Refusing would strand a student mid-measurement
over a difference that may not affect what they are doing; silence would leave them guessing
at a missing control.

The device previously reported only a name and a protocol number, neither of which changes
between builds. The build identity is injected by CMake from the working tree, which also
closes the gap recorded in the characterization report, where a measurement could not be
tied to the image that produced it.

**Verdict.** Pass.

### V-28 Sample loss

**Method.** TIM3's PC6 reference wired to PE7, 37,004 Hz, 30 captures of 4096 samples at each
rate. Edge positions are fitted against their ordinal number; the slope is samples per half
period. Steady loss makes the capture shorter than the reported rate implies and shows in the
slope. A single dropped sample shifts every later edge by one, which no straight line absorbs,
so it shows as a step in the residuals. `scripts/check_sample_loss.py`.

| Sample rate | Fitted / expected | Spread | Worst step | Steady loss bounded at |
| --- | --- | --- | --- | --- |
| 9.882 MS/s | 0.9999917 | 26 ppm | 0.152 | 1 in 119,903 |
| 4.941 MS/s | 0.9999883 | 6 ppm | 0.156 | 1 in 85,423 |
| 2 MS/s | 0.9999877 | 12 ppm | 0.464 | 1 in 81,250 |
| 1 MS/s | 0.9999887 | 6 ppm | 0.277 | 1 in 88,362 |

**Result.** No steady loss above the bound and no isolated drop at any rate. A dropped sample
is a step of exactly one, because loss is whole samples; the worst innocent step measured was
0.46.

Periodicity does not hide either failure. Only losing a whole period could pass unnoticed,
and the slope test bounds that directly.

The 8 to 12 ppm shortfall common to all four rates is not loss. It is the reference frequency
being reported as a whole hertz: 37000 Hz asks for 2270 ticks of an 84 MHz clock, which is
37004.4 Hz, reported as 37004, an 11.0 ppm understatement of the true spacing. Correcting for
it leaves every rate within its own scatter. The tabulated bounds are therefore conservative,
limited by that reporting granularity rather than by anything detected.

Two earlier attempts failed for reasons worth keeping. Driving the pattern from the AWG could
not work: an isolated table entry leaves the DAC over about 4 us, which is 40 samples of
ambiguity at 9.882 MS/s where a drop moves an edge by one. The pattern itself played
correctly, with analog crossings on clean 5 us multiples, so the source was the limit, not the
sampler. Separately the step detector first flagged 0.53 samples at 2 MS/s as a drop; it takes
a maximum over every split point, and splits with two or three edges on one side are dominated
by their own scatter. Requiring five either side and setting the threshold at 0.75, between
that noise floor and the 1.0 a real drop gives, resolved it.

**Verdict.** Pass.

## 4. Defects

| ID | Description | Severity | Status |
| --- | --- | --- | --- |
| D-1 | Mixed follower's first analog sample invalid at 500 kS/s | Minor | Fixed |
| D-2 | Historical dual-arbitrary AWG freeze | Major | Closed, not reproduced |
| D-4 | Control task never woken by the CDC callbacks, 20 ms floor per request | Major | Fixed |

D-3 was withdrawn. It recorded a toolchain failure that turned out to be an invocation error
rather than a defect in anything under test. The numbering keeps its gap so that references
elsewhere stay valid.

**D-1.** Caused by the ADC DMA stream running in circular mode, which continues writing past
the end of the transfer and can overwrite the first sample of the window before the task
stops it. Fixed by setting the stream to normal mode in the .ioc, so the change survives
regeneration. Verified clean in V-22.

**D-2.** Closed as not reproduced, which is a different disposition from fixed: no root cause
was ever found.

Observed on a pre-RTOS build. Three hypotheses were tested and none held; a speculative fix
showed no measurable change and was reverted. The architecture has since changed underneath
it, through the move to FreeRTOS tasks, the CDC wake fix in D-4 and the ADC DMA mode change
in D-1, so the code it lived in may no longer exist. The hardest conditions available were
then tried on the current Release build: 180 s of maximum contention with both channels on
arbitrary tables, 2,598 captures, no stall and no counter movement.

Reopen on any recurrence. Absence across these runs bounds it; it does not explain it.

**D-4.** `tasks_notify_control()` was defined and declared but never called, so the control
task ran only on its 10 ms idle timeout and reception was not rearmed until it did. Every
request waited for that timer rather than the interrupt, giving 19.997 ms median and making a
capture transfer an exact multiple of it. The transmit-complete callback had the same gap.
Calling the notify from both, inside CubeMX user-code regions, took the median to 0.22 ms and
a 2048-sample transfer from 3419.7 ms to 39.79 ms. Found by the milestone 9 harness.

## 5. Limitations

| ID | Limitation |
| --- | --- |
| L-1 | Analog accuracy, distortion and bandwidth are uncharacterized. Loopback alone cannot isolate which path contributes an error. PA4's audio connection can load DAC1, and PA5 shares the deselected motion sensor's clock trace. |
| L-2 | Independent time-base accuracy is unmeasured: every rate divides one crystal, so a frequency error is invisible from inside. Asynchronous pulse limits are uncharacterized. One observed single-sample pulse is not a guaranteed minimum width, and GPIO reads land when DMA wins the bus rather than exactly at the timer edge, so a pulse can be missed without an error flag; the 10 MS/s setting is experimental. Sample loss itself is bounded in V-28. |
| L-3 | Decoder checks used AWG-generated patterns, not independent external devices. |
| L-4 | FIFO and direct-mode tests establish software handling, not hardware fault generation. |
| L-5 | Deadline shutdown is IRQ-driven and may occur after a stale sample reaches the DAC. |
| L-6 | Timing results cover the listed loads, not every waveform or scheduling condition. |
| L-7 | Skew is measured against the device's own reference output, which shares the sampler's clock. It bounds the two acquisition paths against each other, not against an independent time base. |
| L-8 | Debugger halts freeze TIM6. Backpressure snapshots briefly halted the CPU, and DAC sequencing used manual timer events, so neither proves uninterrupted analog timing. |
