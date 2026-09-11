# Instrument protocol

Version 1 uses native USB CDC on CN5. Frames are COBS encoded and terminated by
`00`. All multibyte fields are little-endian. Shared [vectors](vectors.txt) are
checked by both C and Python tests.

| Decoded offset | Field |
| --- | --- |
| 0 | Version, u8; currently 1 |
| 1 | Command, u8 |
| 2 | Request sequence, u16 |
| 4 | Payload length, u8; maximum 32 |
| 5 | Payload |

Maximum wire length is 39 bytes including delimiter. Replies echo the sequence,
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
Acquisition transfer formats are deferred.
