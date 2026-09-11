#include "commands.h"

#include "awg.h"
#include <string.h>

static void put_u32(uint8_t *out, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) {
        out[i] = (uint8_t)(value >> (8U * i));
    }
}

static void put_u16(uint8_t *out, uint16_t value)
{
    out[0] = (uint8_t)value;
    out[1] = (uint8_t)(value >> 8U);
}

static uint32_t get_u32(const uint8_t *in)
{
    return (uint32_t)in[0] | (uint32_t)in[1] << 8 | (uint32_t)in[2] << 16 | (uint32_t)in[3] << 24;
}

static uint16_t get_u16(const uint8_t *in)
{
    return (uint16_t)((uint16_t)in[0] | (uint16_t)in[1] << 8U);
}

static bool valid_length(const protocol_frame_t *request)
{
    switch (request->command) {
    case CMD_AWG_CONFIG:
        return request->length == 5U;
    case CMD_AWG_CONFIG_EXT:
        return request->length == 12U;
    case CMD_AWG_STATUS_EXT:
        return request->length == 1U;
    case CMD_AWG_UPLOAD:
        return request->length >= 6U && request->payload[3] >= 1U &&
               request->payload[3] <= 14U &&
               request->length == (uint8_t)(4U + 2U * request->payload[3]);
    case CMD_AWG_COMMIT:
        return request->length == 3U;
    default:
        return request->length == 0U;
    }
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
    if (request->command < CMD_HELLO || request->command > CMD_AWG_COMMIT) {
        reply->payload[0] = REPLY_COMMAND;
        return;
    }
    if (!valid_length(request)) {
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
        reply->payload[1] = AWG_CHANNEL_COUNT;
        reply->payload[2] = (1U << AWG_WAVEFORM_COUNT) - 1U;
        put_u32(reply->payload + 3, AWG_MIN_MILLIHZ / 1000U);
        put_u32(reply->payload + 7, AWG_MAX_MILLIHZ / 1000U);
        reply->payload[11] = 100U; /* Legacy table length. */
        reply->length = 12U;
        break;
    case CMD_AWG_CONFIG: {
        uint32_t frequency_hz = get_u32(request->payload + 1);
        if (request->payload[0] > AWG_SQUARE || frequency_hz < AWG_MIN_MILLIHZ / 1000U ||
            frequency_hz > AWG_MAX_MILLIHZ / 1000U) {
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
    case CMD_AWG_CONFIG_EXT: {
        awg_config_t config = {.waveform = (awg_waveform_t)request->payload[1],
                               .frequency_millihz = get_u32(request->payload + 2),
                               .amplitude_permille = get_u16(request->payload + 6),
                               .offset_permille = get_u16(request->payload + 8),
                               .phase_decidegrees = get_u16(request->payload + 10)};
        result = awg_configure_channel(request->payload[0], &config);
        break;
    }
    case CMD_AWG_STATUS_EXT: {
        awg_channel_status_t status;
        if (!awg_get_channel_status(request->payload[0], &status)) {
            result = AWG_INVALID;
            break;
        }
        reply->payload[1] = (uint8_t)status.state;
        reply->payload[2] = status.channel;
        reply->payload[3] = (uint8_t)status.config.waveform;
        put_u32(reply->payload + 4, status.config.frequency_millihz);
        put_u32(reply->payload + 8, status.actual_millihz);
        put_u16(reply->payload + 12, status.config.amplitude_permille);
        put_u16(reply->payload + 14, status.config.offset_permille);
        put_u16(reply->payload + 16, status.config.phase_decidegrees);
        put_u32(reply->payload + 18, status.underruns);
        put_u32(reply->payload + 22, status.dma_errors);
        put_u32(reply->payload + 26, status.refill_misses);
        put_u16(reply->payload + 30, status.arbitrary_length);
        reply->length = 32U;
        break;
    }
    case CMD_AWG_UPLOAD: {
        uint16_t samples[14];
        uint8_t count = request->payload[3];
        for (uint8_t i = 0U; i < count; ++i) {
            samples[i] = get_u16(request->payload + 4U + 2U * i);
        }
        result = awg_upload_arbitrary(request->payload[0], get_u16(request->payload + 1),
                                      samples, count);
        break;
    }
    case CMD_AWG_COMMIT:
        result = awg_commit_arbitrary(request->payload[0], get_u16(request->payload + 1));
        break;
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
