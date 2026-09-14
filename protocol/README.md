# Instrument protocol

Version 1 uses native USB CDC on CN5. Frames are COBS encoded and terminated by
`00`. All multibyte fields are little-endian. Shared [vectors](vectors.txt) are
checked by both C and Python tests.

| Decoded offset | Field |
| --- | --- |
| 0 | Version, u8; currently 1 |
| 1 | Command, u8 |
| 2 | Request sequence, u16 |
| 4 | Payload length, u8; maximum 57 |
| 5 | Payload |

Maximum wire length is 64 bytes including delimiter. Replies echo the sequence,
set command bit 7, and prepend a status byte to the payload. There is no application
CRC. USB handles link integrity; the parser validates framing and payload lengths.

| ID | Command | Request | Successful reply after status |
| --- | --- | --- | --- |
| 1 | HELLO | Empty | ASCII `STM32-MSI` |
| 2 | GET_CAPABILITIES | Empty | Channels u8, waveform mask u8, min Hz u32, max Hz u32, table length u8 |
| 3 | AWG_CONFIG | Waveform u8, frequency Hz u32 | Empty |
| 4 | AWG_START | Empty | Empty |
| 5 | AWG_STOP | Empty | Empty |
| 6 | GET_STATUS | Empty | State u8, waveform u8, requested Hz u32, calculated mHz u32, underruns u32, DMA errors u32 |
| 7 | AWG_CONFIG_EXT | Channel u8, waveform u8, frequency mHz u32, amplitude permille u16, offset permille u16, phase 0.1° u16 | Empty |
| 8 | AWG_STATUS_EXT | Channel u8 | State u8, channel u8, waveform u8, requested mHz u32, actual mHz u32, amplitude u16, offset u16, phase u16, underruns u32, DMA errors u32, refill misses u32, arbitrary length u16 |
| 9 | AWG_UPLOAD | Channel u8, offset u16, count u8, 1..14 DAC codes u16 | Empty |
| 10 | AWG_COMMIT | Channel u8, total samples u16 | Empty |
| 11 | SCOPE_CONFIG | Rate u32, count u16, trigger channel u8, edge u8, level u16, pre-trigger permille u16 | Empty |
| 12 | SCOPE_ARM | Empty | Empty |
| 13 | SCOPE_STOP | Empty | Empty |
| 14 | SCOPE_STATUS | Empty | State u8, rate u32, count u16, trigger index u16, capture ID u32, trigger misses u32, overruns u32, DMA errors u32, window origin u16 |
| 15 | SCOPE_READ | Capture ID u32, offset u16, count u8 | Capture ID u32, offset u16, count u8, packed sample pairs u32 |
| 16 | LOGIC_CONFIG | Rate u32, count u16, mode u8, channel u8, mask u8, value u8, pre-trigger permille u16 | Empty |
| 17 | LOGIC_ARM | Empty | Empty |
| 18 | LOGIC_STOP | Empty | Empty |
| 19 | LOGIC_STATUS | Empty | State u8, requested rate u32, actual rate u32, count u16, trigger index u16, capture ID u32, trigger misses u32, overruns u32, DMA errors u32, window origin u16 |
| 20 | LOGIC_READ | Capture ID u32, offset u16, count u8 | Capture ID u32, offset u16, count u8, channel bytes |
| 21 | DEVICE_STATUS | Empty | Owner u8, conflicts u32, AWG state u8, underruns u32, DMA errors u32, refill misses u32, scope state u8, capture ID u32, trigger misses u32, overruns u32, DMA errors u32, logic state u8, capture ID u32, trigger misses u32, overruns u32, DMA errors u32 |
| 22 | RTOS_STATUS | Empty | Task count u8, stack headroom u32 per task, heap free u32, heap low water u32 |
| 23 | PROBE_CONFIG | Frequency Hz u32, duty permille u16 | Empty |
| 24 | PROBE_STATUS | Empty | Enabled u8, requested Hz u32, actual Hz u32, duty permille u16, prescaler u16, reload u16 |
| 25 | MIXED_ARM | Trigger source u8 | Empty |
| 26 | MIXED_STOP | Empty | Empty |
| 27 | MIXED_STATUS | Empty | State u8, trigger source u8, capture ID u32, restarts u32, scope capture ID u32, logic capture ID u32 |

Commands 1 through 6 retain their original layout. Extended commands address channels
0 and 1. Waveforms: 0 sine, 1 triangle, 2 square, 3 sawtooth, 4 DC, 5 arbitrary.
Capability mask bits match these values.
States: 0 unconfigured, 1 ready, 2 running, 3 fault.
Status: 0 success, 1 invalid payload, 2 busy, 3 hardware fault, 4 unsupported version,
5 unknown command. Version errors are returned using version 1 framing.

Amplitude is peak-to-peak and offset is the waveform center, both in thousandths of
DAC full scale. Their combination must remain within codes 0..4095. Arbitrary uploads
contain 2..256 codes in consecutive chunks beginning at offset zero; COMMIT makes the
completed table available to configuration. Configuration and upload require a stopped
AWG. START and STOP affect all configured outputs. Disconnect leaves generation active.
Malformed frames are discarded through the delimiter; incomplete frames expire
after 500 ms without parser progress. USB reset/deconfiguration clears buffered
session data. RX is rearmed only after consumption, and replies retain their buffers
until transfer completion. A stalled host therefore applies endpoint backpressure.

The client permits one outstanding request. Opening sends a delimiter to clear any
partial frame. On timeout or transport failure it closes the connection; command
execution may already have occurred, so reconnect and query status before retrying.
Sequence numbers correlate responses; they do not provide duplicate suppression.

Scope rates are 100, 500 and 1000 kS/s. Captures contain 64..2048 simultaneous
sample pairs from PC4 and PC5. Edge values are 0 free-run, 1 rising and 2 falling;
trigger level is a 12-bit ADC code. Each read returns at most 12 pairs, with CH1 in
bits 0..15 and CH2 in bits 16..31. Scope states are 0 idle, 1 armed, 2 complete and
3 fault.

Logic requested rates are 1, 2, 5 and 10 MS/s. The sampling timer divides 168 MHz by
an integer, so 5 and 10 MS/s are not reachable exactly; LOGIC_STATUS reports both the
requested rate and the rate actually programmed. Captures contain 64..4096 samples of
channels D0..D7 on PE7..PE14, one byte per sample with D0 in bit 0. Trigger modes are
0 free-run, 1 rising, 2 falling and 3 pattern. Edge modes use the channel field;
pattern mode compares `(sample & mask) == (value & mask)` and fires on entry, so mask
must select at least one channel. Each read returns at most 48 samples. Logic states
match the scope's: 0 idle, 1 armed, 2 complete and 3 fault. Acquisition ownership is described below.

DEVICE_STATUS combines subsystem state and counters in one reply. Configuration
remains available through the individual status commands.

Scope and logic share exclusive acquisition ownership. Arm claims it; Stop or fault
releases it; Complete retains it for reading/rearming. Conflicting Arm requests return
busy (2) and increment conflicts. Owner values: 0 none, 1 scope, 2 logic.

RTOS_STATUS gives minimum free stack bytes in task order (awg, acquire, control,
status), followed by current and minimum free heap bytes.

PROBE_CONFIG controls TIM3 PWM on PC6: zero Hz disables it; otherwise request 1 Hz
to 42 MHz and duty 1..999 permille. Integer dividers limit achievable frequency;
PROBE_STATUS reports the programmed rate and registers. Compare values are clamped
to keep the output toggling.

MIXED_ARM starts both captures from one timer event so their samples share an origin.
Trigger source is 0 for the scope and 1 for the logic analyzer; the other stream must be
configured free-running, and the command is refused with status 1 otherwise, because a
second trigger search would choose its own window and break the alignment. Mixed capture
claims the acquisition hardware as a single owner, so a standalone arm is refused while
it holds it, and the reverse.

**Window origin** is how many samples elapsed between the shared start and the first
sample of the returned window. With the rate, that is enough to place every sample:
`time(i) = (window_origin + i) / rate`. Both streams measure it from the same instant,
so a common timeline follows without resampling either one. Mixed states are 0 idle,
1 armed, 2 complete and 3 fault, matching the scope and the analyzer.

A shared origin is not a shared sampling instant. The ADC holds its input for three
cycles after its trigger while a GPIO read happens whenever DMA wins the bus, so a skew
remains between the two paths; it is measured on the board rather than corrected for.
