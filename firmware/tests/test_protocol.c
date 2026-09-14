#include "protocol.h"
#include "commands.h"
#include "awg.h"
#include "scope.h"
#include "logic.h"
#include "ownership.h"
#include "mixed.h"
#include "probe.h"
#include "tasks.h"

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
static uint8_t last_channel;
static awg_config_t last_config;
static uint16_t last_offset;
static uint8_t last_count;
static scope_config_t last_scope_config;
static uint32_t scope_samples[12];
static logic_config_t last_logic_config;
static uint8_t logic_samples[LOGIC_READ_MAX];

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
awg_result_t awg_configure_channel(uint8_t channel, const awg_config_t *config)
{
    ++calls;
    last_channel = channel;
    last_config = *config;
    return result;
}
awg_result_t awg_upload_arbitrary(uint8_t channel, uint16_t offset, const uint16_t *samples,
                                  uint8_t count)
{
    ++calls;
    last_channel = channel;
    last_offset = offset;
    last_count = count;
    last_config.amplitude_permille = samples[0];
    return result;
}
awg_result_t awg_commit_arbitrary(uint8_t channel, uint16_t length)
{
    ++calls;
    last_channel = channel;
    last_offset = length;
    return result;
}
awg_status_t awg_get_status(void)
{
    return (awg_status_t){AWG_RUNNING, AWG_TRIANGLE, 100, 100000, 0, 0};
}
bool awg_get_channel_status(uint8_t channel, awg_channel_status_t *out)
{
    if (channel >= AWG_CHANNEL_COUNT) {
        return false;
    }
    *out = (awg_channel_status_t){.state = AWG_READY,
                                  .channel = channel,
                                  .config = {.waveform = AWG_SAWTOOTH,
                                             .frequency_millihz = 123456U,
                                             .amplitude_permille = 600U,
                                             .offset_permille = 500U,
                                             .phase_decidegrees = 900U},
                                  .actual_millihz = 123455U,
                                  .underruns = 1U,
                                  .dma_errors = 2U,
                                  .refill_misses = 3U,
                                  .arbitrary_length = 17U};
    return true;
}
scope_result_t scope_configure(const scope_config_t *config)
{
    last_scope_config = *config;
    ++calls;
    return (scope_result_t)result;
}
scope_result_t scope_arm(void) { ++calls; return (scope_result_t)result; }
scope_result_t scope_stop(void) { ++calls; return (scope_result_t)result; }
scope_status_t scope_get_status(void)
{
    return (scope_status_t){.state = SCOPE_COMPLETE,
                            .config = {.sample_rate = 500000U, .sample_count = 512U},
                            .trigger_index = 128U,
                            .window_origin = 40U,
                            .capture_id = 9U,
                            .trigger_misses = 4U,
                            .overruns = 2U,
                            .dma_errors = 1U};
}
bool scope_read(uint32_t capture_id, uint16_t offset, uint8_t count, uint32_t *samples)
{
    if (capture_id != 9U || offset + count > 512U) return false;
    for (uint8_t i = 0; i < count; ++i) samples[i] = scope_samples[i];
    return true;
}
void scope_process(void) {}
logic_result_t logic_configure(const logic_config_t *config)
{
    last_logic_config = *config;
    ++calls;
    return (logic_result_t)result;
}
logic_result_t logic_arm(void) { ++calls; return (logic_result_t)result; }
logic_result_t logic_stop(void) { ++calls; return (logic_result_t)result; }
logic_status_t logic_get_status(void)
{
    return (logic_status_t){.state = LOGIC_COMPLETE,
                            .config = {.sample_rate = 5000000U, .sample_count = 1024U},
                            .actual_rate = 4941176U,
                            .trigger_index = 256U,
                            .window_origin = 60U,
                            .capture_id = 7U,
                            .trigger_misses = 5U,
                            .overruns = 3U,
                            .dma_errors = 2U};
}
bool logic_read(uint32_t capture_id, uint16_t offset, uint8_t count, uint8_t *samples)
{
    if (capture_id != 7U || offset + count > 1024U) return false;
    for (uint8_t i = 0; i < count; ++i) samples[i] = logic_samples[i];
    return true;
}
void logic_process(void) {}
static mixed_status_t mixed_state;
mixed_result_t mixed_arm(mixed_trigger_t trigger)
{
    ++calls;
    mixed_state.trigger = trigger;
    mixed_state.state = MIXED_ARMED;
    return (mixed_result_t)result;
}
mixed_result_t mixed_stop(void)
{
    ++calls;
    mixed_state.state = MIXED_IDLE;
    return (mixed_result_t)result;
}
mixed_status_t mixed_get_status(void) { return mixed_state; }
void mixed_process(void) {}
uint32_t tasks_stack_headroom(app_task_t task)
{
    return 100U + (uint32_t)task;
}
uint32_t tasks_heap_free(void) { return 4096U; }
static probe_status_t probe_state;
probe_result_t probe_configure(uint32_t frequency_hz, uint16_t duty_permille)
{
    probe_divider_t divider;
    if (!probe_divider(frequency_hz, duty_permille, &divider)) {
        return PROBE_INVALID;
    }
    probe_state = (probe_status_t){.enabled = true,
                                   .requested_hz = frequency_hz,
                                   .actual_hz = divider.actual_hz,
                                   .duty_permille = duty_permille,
                                   .prescaler = divider.prescaler,
                                   .reload = divider.reload};
    return PROBE_OK;
}
probe_result_t probe_disable(void)
{
    probe_state.enabled = false;
    return PROBE_OK;
}
probe_status_t probe_get_status(void) { return probe_state; }
uint32_t tasks_heap_low_water(void) { return 2048U; }

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
    /* Two hex digits per byte, plus a terminator: a full 57-byte payload needs 115
       and a full 64-byte frame needs 129. */
    char payload[PROTOCOL_PAYLOAD_MAX * 2 + 1], wire[PROTOCOL_FRAME_MAX * 2 + 1];
    while (fscanf(file, "%u %u %u %114s %128s", &version, &command, &sequence, payload, wire) == 5) {
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
    CHECK(vectors == 8);
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

    frame.command = CMD_CAPABILITIES;
    command_execute(&frame, &reply);
    CHECK(reply.length == 12U && reply.payload[1] == 2U && reply.payload[2] == 63U);

    frame.command = CMD_AWG_CONFIG_EXT;
    frame.length = 12U;
    const uint8_t extended[] = {1, 3, 0x40, 0xe2, 1, 0, 0x58, 2, 0xf4, 1, 0x84, 3};
    memcpy(frame.payload, extended, sizeof extended);
    result = AWG_OK;
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_OK && last_channel == 1U);
    CHECK(last_config.waveform == AWG_SAWTOOTH && last_config.frequency_millihz == 123456U);
    CHECK(last_config.amplitude_permille == 600U && last_config.offset_permille == 500U);
    CHECK(last_config.phase_decidegrees == 900U);

    frame.command = CMD_AWG_STATUS_EXT;
    frame.length = 1U;
    frame.payload[0] = 1U;
    command_execute(&frame, &reply);
    CHECK(reply.length == 32U && reply.payload[1] == AWG_READY && reply.payload[2] == 1U);
    CHECK(reply.payload[3] == AWG_SAWTOOTH && reply.payload[26] == 3U);

    frame.command = CMD_AWG_UPLOAD;
    frame.length = 8U;
    const uint8_t upload[] = {0, 0, 0, 2, 0, 0, 0xff, 0x0f};
    memcpy(frame.payload, upload, sizeof upload);
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_OK && last_channel == 0U && last_offset == 0U);
    CHECK(last_count == 2U && last_config.amplitude_permille == 0U);

    frame.command = CMD_AWG_COMMIT;
    frame.length = 3U;
    frame.payload[0] = 0U;
    frame.payload[1] = 2U;
    frame.payload[2] = 0U;
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_OK && last_offset == 2U);

    frame.command = CMD_AWG_UPLOAD;
    frame.length = 7U;
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_INVALID);

    frame.command = CMD_SCOPE_CONFIG;
    frame.length = 12U;
    const uint8_t scope_config[] = {0x20, 0xa1, 0x07, 0x00, 0x00, 0x02,
                                    1, 2, 0x00, 0x08, 0xfa, 0x00};
    memcpy(frame.payload, scope_config, sizeof scope_config);
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_OK && last_scope_config.sample_rate == 500000U);
    CHECK(last_scope_config.sample_count == 512U && last_scope_config.trigger_channel == 1U);
    CHECK(last_scope_config.trigger_edge == SCOPE_TRIGGER_FALLING);
    CHECK(last_scope_config.trigger_level == 2048U && last_scope_config.pretrigger_permille == 250U);

    frame.command = CMD_SCOPE_STATUS;
    frame.length = 0U;
    command_execute(&frame, &reply);
    CHECK(reply.length == 28U && reply.payload[1] == SCOPE_COMPLETE);
    CHECK(reply.payload[26] == 40U); /* window origin */
    CHECK(reply.payload[10] == 9U && reply.payload[14] == 4U && reply.payload[18] == 2U);

    scope_samples[0] = 100U | (200U << 16);
    scope_samples[1] = 300U | (400U << 16);
    frame.command = CMD_SCOPE_READ;
    frame.length = 7U;
    const uint8_t read_request[] = {9, 0, 0, 0, 0, 0, 2};
    memcpy(frame.payload, read_request, sizeof read_request);
    command_execute(&frame, &reply);
    CHECK(reply.length == 16U && reply.payload[0] == REPLY_OK);
    CHECK(reply.payload[8] == 100U && reply.payload[10] == 200U);
    frame.command = CMD_LOGIC_CONFIG;
    frame.length = 12U;
    const uint8_t logic_config[] = {0x40, 0x4b, 0x4c, 0x00, 0x00, 0x04,
                                    3, 2, 0x0f, 0x0a, 0xfa, 0x00};
    memcpy(frame.payload, logic_config, sizeof logic_config);
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_OK && last_logic_config.sample_rate == 5000000U);
    CHECK(last_logic_config.sample_count == 1024U);
    CHECK(last_logic_config.trigger.mode == LOGIC_TRIGGER_PATTERN);
    CHECK(last_logic_config.trigger.channel == 2U && last_logic_config.trigger.mask == 0x0fU);
    CHECK(last_logic_config.trigger.value == 0x0aU);
    CHECK(last_logic_config.pretrigger_permille == 250U);

    frame.command = CMD_LOGIC_STATUS;
    frame.length = 0U;
    command_execute(&frame, &reply);
    CHECK(reply.length == 32U && reply.payload[1] == LOGIC_COMPLETE);
    CHECK(reply.payload[30] == 60U); /* window origin */
    CHECK(reply.payload[2] == 0x40U && reply.payload[14] == 7U && reply.payload[22] == 3U);

    logic_samples[0] = 0xa5U;
    logic_samples[1] = 0x5aU;
    frame.command = CMD_LOGIC_READ;
    frame.length = 7U;
    const uint8_t logic_request[] = {7, 0, 0, 0, 0, 0, 2};
    memcpy(frame.payload, logic_request, sizeof logic_request);
    command_execute(&frame, &reply);
    CHECK(reply.length == 10U && reply.payload[0] == REPLY_OK);
    CHECK(reply.payload[8] == 0xa5U && reply.payload[9] == 0x5aU);

    frame.payload[6] = LOGIC_READ_MAX + 1U;
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_INVALID);

    ownership_claim(&acquisition_ownership, ACQUISITION_LOGIC);
    frame.command = CMD_DEVICE_STATUS;
    frame.length = 0U;
    command_execute(&frame, &reply);
    CHECK(reply.length == 53U && reply.payload[0] == REPLY_OK);
    CHECK(reply.payload[1] == ACQUISITION_LOGIC);
    CHECK(reply.payload[6] == AWG_READY && reply.payload[15] == 3U);
    CHECK(reply.payload[19] == SCOPE_COMPLETE && reply.payload[20] == 9U);
    CHECK(reply.payload[36] == LOGIC_COMPLETE && reply.payload[37] == 7U);
    CHECK(!ownership_claim(&acquisition_ownership, ACQUISITION_SCOPE));
    command_execute(&frame, &reply);
    CHECK(reply.payload[2] == 1U); /* The rejected claim is visible to the host. */
    ownership_release(&acquisition_ownership, ACQUISITION_LOGIC);

    frame.command = CMD_RTOS_STATUS;
    command_execute(&frame, &reply);
    CHECK(reply.length == 10U + 4U * TASK_COUNT && reply.payload[0] == REPLY_OK);
    CHECK(reply.payload[1] == TASK_COUNT && reply.payload[2] == 100U);
    CHECK(reply.payload[2U + 4U * TASK_COUNT] == 0U);

    frame.command = CMD_MIXED_STATUS + 1U;
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_COMMAND);

    frame.command = CMD_PROBE_CONFIG;
    frame.length = 6U;
    const uint8_t probe_request[] = {0x40, 0x42, 0x0f, 0x00, 0xf4, 0x01};
    memcpy(frame.payload, probe_request, sizeof probe_request);
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_OK);

    frame.command = CMD_PROBE_STATUS;
    frame.length = 0U;
    command_execute(&frame, &reply);
    CHECK(reply.length == 16U && reply.payload[1] == 1U);
    CHECK(reply.payload[2] == 0x40U && reply.payload[3] == 0x42U); /* 1,000,000 Hz */
    CHECK(reply.payload[6] == 0x40U && reply.payload[7] == 0x42U); /* reached exactly */

    frame.command = CMD_PROBE_CONFIG;
    frame.length = 6U;
    memset(frame.payload, 0, 6U);
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_OK); /* zero frequency disables */
    frame.command = CMD_PROBE_STATUS;
    frame.length = 0U;
    command_execute(&frame, &reply);
    CHECK(reply.payload[1] == 0U);

    frame.command = CMD_PROBE_CONFIG;
    frame.length = 6U;
    const uint8_t too_fast[] = {0x00, 0x00, 0x00, 0x80, 0xf4, 0x01};
    memcpy(frame.payload, too_fast, sizeof too_fast);
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_INVALID);

    frame.command = CMD_MIXED_ARM;
    frame.length = 1U;
    frame.payload[0] = 1U;
    result = AWG_OK;
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_OK);

    frame.command = CMD_MIXED_STATUS;
    frame.length = 0U;
    command_execute(&frame, &reply);
    CHECK(reply.length == 19U);
    CHECK(reply.payload[2] == MIXED_TRIGGER_LOGIC);

    frame.command = CMD_MIXED_ARM;
    frame.length = 2U;
    command_execute(&frame, &reply);
    CHECK(reply.payload[0] == REPLY_INVALID);

    puts("Protocol vectors, bounds, malformed frames and command validation passed.");
    return 0;
}
