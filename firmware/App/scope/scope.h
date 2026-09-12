#ifndef SCOPE_H
#define SCOPE_H

#include "scope_trigger.h"
#include <stdbool.h>
#include <stdint.h>

#define SCOPE_MAX_SAMPLES 2048U

typedef enum {
    SCOPE_IDLE,
    SCOPE_ARMED,
    SCOPE_COMPLETE,
    SCOPE_FAULT
} scope_state_t;

typedef enum {
    SCOPE_OK,
    SCOPE_INVALID,
    SCOPE_BUSY,
    SCOPE_HW_ERROR
} scope_result_t;

typedef struct {
    uint32_t sample_rate;
    uint16_t sample_count;
    uint8_t trigger_channel;
    scope_trigger_edge_t trigger_edge;
    uint16_t trigger_level;
    uint16_t pretrigger_permille;
} scope_config_t;

typedef struct {
    scope_state_t state;
    scope_config_t config;
    uint16_t trigger_index;
    uint32_t capture_id;
    uint32_t trigger_misses;
    uint32_t overruns;
    uint32_t dma_errors;
} scope_status_t;

scope_result_t scope_configure(const scope_config_t *config);
scope_result_t scope_arm(void);
scope_result_t scope_stop(void);
scope_status_t scope_get_status(void);
bool scope_read(uint32_t capture_id, uint16_t offset, uint8_t count, uint32_t *samples);
void scope_process(void);

#endif
