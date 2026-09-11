#include "protocol.h"

#include <string.h>

bool protocol_feed(protocol_parser_t *parser, uint8_t byte, protocol_frame_t *frame)
{
    if (byte != 0U) {
        if (parser->length < sizeof parser->bytes && !parser->discard) {
            parser->bytes[parser->length++] = byte;
        } else {
            parser->discard = true;
        }
        return false;
    }
    uint8_t size = parser->length;
    bool discard = parser->discard;
    parser->length = 0U;
    parser->discard = false;
    if (discard || size == 0U) {
        return false;
    }
    uint8_t raw[5U + PROTOCOL_PAYLOAD_MAX];
    uint32_t read = 0U, used = 0U;
    while (read < size) {
        uint32_t count = parser->bytes[read++];
        if (count == 0U || count - 1U > size - read || used + count - 1U > sizeof raw) {
            return false;
        }
        for (uint8_t i = 1U; i < count; ++i) {
            raw[used++] = parser->bytes[read++];
        }
        if (count != 255U && read < size) {
            if (used == sizeof raw) {
                return false;
            }
            raw[used++] = 0U;
        }
    }
    if (used < 5U || raw[4] > PROTOCOL_PAYLOAD_MAX || used != 5U + raw[4]) {
        return false;
    }
    frame->version = raw[0];
    frame->command = raw[1];
    frame->sequence = (uint16_t)(raw[2] | (uint16_t)raw[3] << 8);
    frame->length = raw[4];
    memcpy(frame->payload, raw + 5, frame->length);
    return true;
}

uint8_t protocol_encode(const protocol_frame_t *frame, uint8_t out[PROTOCOL_FRAME_MAX])
{
    if (frame->length > PROTOCOL_PAYLOAD_MAX) {
        return 0U;
    }
    uint8_t raw[5U + PROTOCOL_PAYLOAD_MAX] = {frame->version, frame->command,
                                              (uint8_t)frame->sequence,
                                              (uint8_t)(frame->sequence >> 8), frame->length};
    memcpy(raw + 5, frame->payload, frame->length);
    uint8_t used = 1U, code_at = 0U, code = 1U;
    for (uint8_t i = 0U; i < 5U + frame->length; ++i) {
        if (raw[i] == 0U) {
            out[code_at] = code;
            code_at = used++;
            code = 1U;
        } else {
            out[used++] = raw[i];
            ++code;
        }
    }
    out[code_at] = code;
    out[used++] = 0U;
    return used;
}
