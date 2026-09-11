#include "protocol.h"
#include "commands.h"
#include "awg.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) \
    do { \
        if (!(x)) { \
            fprintf(stderr, "Failed line %d: %s\n", __LINE__, #x); \
            return 1; \
        } \
    } while (0)

static unsigned calls;
static awg_result_t result;

awg_result_t awg_configure(awg_waveform_t shape, uint32_t hz)
{
    (void)shape;
    (void)hz;
    ++calls;
    return result;
}
awg_result_t awg_start(void)
{
    ++calls;
    return result;
}
awg_result_t awg_stop(void)
{
    ++calls;
    return result;
}
awg_status_t awg_get_status(void)
{
    return (awg_status_t){AWG_RUNNING, AWG_TRIANGLE, 100, 100000, 0, 0};
}

static unsigned unhex(const char *text, uint8_t *out)
{
    unsigned n = 0;
    if (*text == '-') {
        return 0;
    }
    while (*text) {
        char pair[3] = {text[0], text[1], 0};
        out[n++] = (uint8_t)strtoul(pair, NULL, 16);
        text += 2;
    }
    return n;
}

int main(int argc, char **argv)
{
    CHECK(argc == 2);
    FILE *file = fopen(argv[1], "r");
    CHECK(file != NULL);
    unsigned version, command, sequence, vectors = 0;
    char payload[65], wire[79];
    while (fscanf(file, "%u %u %u %64s %78s", &version, &command, &sequence, payload, wire) == 5) {
        protocol_frame_t frame = {.version = (uint8_t)version,
                                  .command = (uint8_t)command,
                                  .sequence = (uint16_t)sequence};
        protocol_frame_t decoded = {0};
        frame.length = (uint8_t)unhex(payload, frame.payload);
        uint8_t expected[PROTOCOL_FRAME_MAX], encoded[PROTOCOL_FRAME_MAX];
        unsigned size = unhex(wire, expected);
        CHECK(protocol_encode(&frame, encoded) == size);
        CHECK(memcmp(expected, encoded, size) == 0);
        protocol_parser_t parser = {0};
        for (unsigned i = 0; i < size; ++i) {
            CHECK(protocol_feed(&parser, expected[i], &decoded) == (i == size - 1U));
        }
        CHECK(decoded.command == frame.command && decoded.version == frame.version);
        CHECK(decoded.sequence == frame.sequence && decoded.length == frame.length);
        CHECK(memcmp(decoded.payload, frame.payload, frame.length) == 0);
        ++vectors;
    }
    fclose(file);
    CHECK(vectors == 5);
    protocol_parser_t parser = {0};
    protocol_frame_t frame = {.version = 1, .command = CMD_STATUS, .sequence = 7}, decoded;
    for (unsigned i = 0; i < 200; ++i) {
        CHECK(!protocol_feed(&parser, 255, &decoded));
    }
    CHECK(!protocol_feed(&parser, 0, &decoded));
    uint8_t wire_bytes[PROTOCOL_FRAME_MAX];
    for (unsigned length = 0; length <= PROTOCOL_PAYLOAD_MAX; ++length) {
        frame.length = (uint8_t)length;
        for (unsigned pattern = 0; pattern < 256; ++pattern) {
            memset(frame.payload, (int)pattern, length);
            unsigned size = protocol_encode(&frame, wire_bytes);
            for (unsigned i = 0; i < size; ++i) {
                CHECK(protocol_feed(&parser, wire_bytes[i], &decoded) == (i == size - 1U));
            }
            CHECK(decoded.length == length && memcmp(frame.payload, decoded.payload, length) == 0);
        }
    }
    frame.length = PROTOCOL_PAYLOAD_MAX + 1U;
    CHECK(protocol_encode(&frame, wire_bytes) == 0);
    const uint8_t malformed[] = {255, 1, 0, 2, 1, 0, 1, 1, 1, 1, 2, 32, 0};
    for (unsigned i = 0; i < sizeof malformed; ++i) {
        CHECK(!protocol_feed(&parser, malformed[i], &decoded));
    }
    protocol_frame_t reply;
    frame = (protocol_frame_t){.version = 2, .command = CMD_AWG_STOP, .sequence = 9};
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_VERSION && calls == 0 && reply.sequence == 9);
    frame.version = 1;
    frame.command = 127;
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_COMMAND && calls == 0);
    frame.command = CMD_AWG_CONFIG;
    frame.length = 4;
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_INVALID && calls == 0);
    frame.length = 5;
    frame.payload[0] = 3;
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_INVALID && calls == 0);
    frame.payload[0] = 0;
    frame.payload[1] = 100;
    result = AWG_BUSY;
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_BUSY && calls == 1);
    frame.command = CMD_STATUS;
    frame.length = 0;
    command_execute(&frame, &reply);
    CHECK(reply.length == 19 && reply.payload[0] == 0 && reply.payload[1] == AWG_RUNNING);
    puts("Protocol vectors, bounds, malformed frames and command validation passed.");
    return 0;
}
