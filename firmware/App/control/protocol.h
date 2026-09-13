#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <stdbool.h>
#include <stdint.h>

#define PROTOCOL_VERSION 1U
#define PROTOCOL_PAYLOAD_MAX 57U
#define PROTOCOL_FRAME_MAX 64U

enum {
    CMD_HELLO = 1,
    CMD_CAPABILITIES,
    CMD_AWG_CONFIG,
    CMD_AWG_START,
    CMD_AWG_STOP,
    CMD_STATUS,
    CMD_AWG_CONFIG_EXT,
    CMD_AWG_STATUS_EXT,
    CMD_AWG_UPLOAD,
    CMD_AWG_COMMIT,
    CMD_SCOPE_CONFIG,
    CMD_SCOPE_ARM,
    CMD_SCOPE_STOP,
    CMD_SCOPE_STATUS,
    CMD_SCOPE_READ,
    CMD_LOGIC_CONFIG,
    CMD_LOGIC_ARM,
    CMD_LOGIC_STOP,
    CMD_LOGIC_STATUS,
    CMD_LOGIC_READ,
    CMD_DEVICE_STATUS,
    CMD_RTOS_STATUS,
    CMD_PROBE_CONFIG,
    CMD_PROBE_STATUS
};
enum {
    REPLY_OK,
    REPLY_INVALID,
    REPLY_BUSY,
    REPLY_HARDWARE,
    REPLY_VERSION,
    REPLY_COMMAND
};

typedef struct {
    uint8_t version;
    uint8_t command;
    uint16_t sequence;
    uint8_t length;
    uint8_t payload[PROTOCOL_PAYLOAD_MAX];
} protocol_frame_t;

typedef struct {
    uint8_t bytes[PROTOCOL_FRAME_MAX - 1U];
    uint8_t length;
    bool discard;
} protocol_parser_t;

bool protocol_feed(protocol_parser_t *parser, uint8_t byte, protocol_frame_t *frame);
uint8_t protocol_encode(const protocol_frame_t *frame, uint8_t out[PROTOCOL_FRAME_MAX]);

#endif
