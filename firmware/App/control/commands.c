#include "commands.h"

#include "awg.h"
#include <string.h>

static void put_u32(uint8_t *out, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) {
        out[i] = (uint8_t)(value >> (8U * i));
    }
}

static uint32_t get_u32(const uint8_t *in)
{
    return (uint32_t)in[0] | (uint32_t)in[1] << 8 | (uint32_t)in[2] << 16 | (uint32_t)in[3] << 24;
}

void command_execute(const protocol_frame_t *request, protocol_frame_t *reply)
{
    *reply = (protocol_frame_t){.version = PROTOCOL_VERSION,
                                .command = request->command | 0x80U,
                                .sequence = request->sequence,
                                .length = 1U};
    if (request->version != PROTOCOL_VERSION) {
        reply->payload[0] = REPLY_VERSION;
        return;
    }
    if (request->command < CMD_HELLO || request->command > CMD_STATUS) {
        reply->payload[0] = REPLY_COMMAND;
        return;
    }
    if (request->length != (request->command == CMD_AWG_CONFIG ? 5U : 0U)) {
        reply->payload[0] = REPLY_INVALID;
        return;
    }
    awg_result_t result = AWG_OK;
    switch (request->command) {
    case CMD_HELLO:
        memcpy(reply->payload + 1, "STM32-MSI", 9);
        reply->length = 10U;
        break;
    case CMD_CAPABILITIES:
        reply->payload[1] = 1U; /* DAC channels */
        reply->payload[2] = 7U; /* Sine, triangle, square */
        put_u32(reply->payload + 3, AWG_MIN_HZ);
        put_u32(reply->payload + 7, AWG_MAX_HZ);
        reply->payload[11] = AWG_SAMPLE_COUNT;
        reply->length = 12U;
        break;
    case CMD_AWG_CONFIG: {
        uint32_t frequency_hz = get_u32(request->payload + 1);
        if (request->payload[0] > AWG_SQUARE || frequency_hz < AWG_MIN_HZ ||
            frequency_hz > AWG_MAX_HZ) {
            result = AWG_INVALID;
        } else {
            result = awg_configure((awg_waveform_t)request->payload[0], frequency_hz);
        }
        break;
    }
    case CMD_AWG_START:
        result = awg_start();
        break;
    case CMD_AWG_STOP:
        result = awg_stop();
        break;
    case CMD_STATUS: {
        awg_status_t status = awg_get_status();
        reply->payload[1] = (uint8_t)status.state;
        reply->payload[2] = (uint8_t)status.waveform;
        put_u32(reply->payload + 3, status.requested_hz);
        put_u32(reply->payload + 7, status.actual_millihz);
        put_u32(reply->payload + 11, status.underruns);
        put_u32(reply->payload + 15, status.dma_errors);
        reply->length = 19U;
        break;
    }
    }
    switch (result) {
    case AWG_OK:
        reply->payload[0] = REPLY_OK;
        break;
    case AWG_INVALID:
        reply->payload[0] = REPLY_INVALID;
        break;
    case AWG_BUSY:
        reply->payload[0] = REPLY_BUSY;
        break;
    case AWG_HW_ERROR:
        reply->payload[0] = REPLY_HARDWARE;
        break;
    }
}
