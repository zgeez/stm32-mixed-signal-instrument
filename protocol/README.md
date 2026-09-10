# Instrument protocol

Status: design draft; no wire encoding is implemented.

The firmware and desktop share a versioned binary contract over native USB CDC.
CDC is a byte stream: reads may split or combine application messages.

Initial commands: `HELLO`, `GET_CAPABILITIES`, `AWG_CONFIG`, `AWG_START`, `AWG_STOP`.
Later extensions cover scope/logic configuration, arming, status and capture data.

Requirements:

- Explicit version negotiation and little-endian encoding.
- Bounded frame/payload lengths, request correlation and defined error replies.
- Rejection of malformed frames and recovery after timeout or reconnect.
- Chunked captures with sample format, count, timing and trigger metadata.
- Explicit buffer ownership, backpressure and dropped-data reporting.
- Shared C/Python conformance vectors before the first protocol release.

Field widths, command identifiers and framing remain open. An application CRC is
deferred unless end-to-end integrity requirements justify it beyond USB link checks.
