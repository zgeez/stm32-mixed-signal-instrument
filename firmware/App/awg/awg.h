#ifndef AWG_H
#define AWG_H

#include "awg_waveform.h"

#include <stdbool.h>

typedef enum {
    AWG_UNCONFIGURED,
    AWG_READY,
    AWG_RUNNING,
    AWG_FAULT
} awg_state_t;

typedef enum {
    AWG_OK,
    AWG_INVALID,
    AWG_BUSY,
    AWG_HW_ERROR
} awg_result_t;

typedef struct {
    awg_state_t state;
    awg_waveform_t waveform;
    uint32_t requested_hz;
    uint32_t actual_millihz;
    uint32_t underruns;
    uint32_t dma_errors;
} awg_status_t;

typedef struct {
    awg_state_t state;
    uint8_t channel;
    awg_config_t config;
    uint32_t actual_millihz;
    uint32_t underruns;
    uint32_t dma_errors;
    uint32_t refill_misses;
    uint16_t arbitrary_length;
} awg_channel_status_t;

awg_result_t awg_configure(awg_waveform_t waveform, uint32_t frequency_hz);
awg_result_t awg_configure_channel(uint8_t channel, const awg_config_t *config);
awg_result_t awg_upload_arbitrary(uint8_t channel, uint16_t offset, const uint16_t *samples,
                                  uint8_t count);
awg_result_t awg_commit_arbitrary(uint8_t channel, uint16_t length);
awg_result_t awg_start(void);
awg_result_t awg_stop(void);
void awg_process(void);
awg_status_t awg_get_status(void);
bool awg_get_channel_status(uint8_t channel, awg_channel_status_t *out);

#endif
