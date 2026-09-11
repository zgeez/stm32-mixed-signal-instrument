#ifndef AWG_H
#define AWG_H

#include "awg_waveform.h"

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

/* Foreground only, after CubeMX init. Owns DAC1 and TIM6. */
awg_result_t awg_configure(awg_waveform_t waveform, uint32_t frequency_hz);
awg_result_t awg_start(void);
/* Stops output; the pin is not held at zero volts. */
awg_result_t awg_stop(void);
awg_status_t awg_get_status(void);

#endif
