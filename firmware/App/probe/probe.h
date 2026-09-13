#ifndef PROBE_H
#define PROBE_H

#include "probe_divider.h"

/* A square-wave reference on PC6, driven by TIM3. Its purpose is to check the
   instrument against a known signal: the DAC cannot produce an edge faster than its
   2.5 us update period, which is far too slow to reach the logic analyzer's limit. */

typedef enum {
    PROBE_OK,
    PROBE_INVALID,
    PROBE_BUSY,
    PROBE_HW_ERROR
} probe_result_t;

typedef struct {
    bool enabled;
    uint32_t requested_hz;
    uint32_t actual_hz;
    uint16_t duty_permille;
    uint16_t prescaler;
    uint16_t reload;
} probe_status_t;

probe_result_t probe_configure(uint32_t frequency_hz, uint16_t duty_permille);
probe_result_t probe_disable(void);
probe_status_t probe_get_status(void);

#endif
