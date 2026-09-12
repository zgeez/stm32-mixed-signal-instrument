#ifndef LOGIC_H
#define LOGIC_H

#include "logic_trigger.h"
#include <stdbool.h>
#include <stdint.h>

#define LOGIC_MAX_SAMPLES 4096U
#define LOGIC_READ_MAX 48U

typedef enum {
    LOGIC_IDLE,
    LOGIC_ARMED,
    LOGIC_COMPLETE,
    LOGIC_FAULT
} logic_state_t;

typedef enum {
    LOGIC_OK,
    LOGIC_INVALID,
    LOGIC_BUSY,
    LOGIC_HW_ERROR
} logic_result_t;

typedef struct {
    uint32_t sample_rate;
    uint16_t sample_count;
    logic_trigger_t trigger;
    uint16_t pretrigger_permille;
} logic_config_t;

typedef struct {
    logic_state_t state;
    logic_config_t config;
    uint32_t actual_rate;
    uint16_t trigger_index;
    uint32_t capture_id;
    uint32_t trigger_misses;
    uint32_t overruns;
    uint32_t dma_errors;
} logic_status_t;

uint32_t logic_actual_rate(uint32_t requested_rate);
logic_result_t logic_configure(const logic_config_t *config);
logic_result_t logic_arm(void);
logic_result_t logic_stop(void);
logic_status_t logic_get_status(void);
bool logic_read(uint32_t capture_id, uint16_t offset, uint8_t count, uint8_t *samples);
void logic_process(void);

#endif
