#ifndef AWG_WAVEFORM_H
#define AWG_WAVEFORM_H

#include <stdbool.h>
#include <stdint.h>

#define AWG_SAMPLE_COUNT 100U
#define AWG_MIN_HZ 1U
#define AWG_MAX_HZ 1000U
#define AWG_LOW_CODE 512U
#define AWG_HIGH_CODE 3584U

typedef enum {
    AWG_SINE,
    AWG_TRIANGLE,
    AWG_SQUARE
} awg_waveform_t;

typedef struct {
    uint16_t prescaler;
    uint16_t period;
    uint32_t actual_millihz;
} awg_timing_t;

bool awg_build_lut(awg_waveform_t waveform, uint16_t samples[AWG_SAMPLE_COUNT]);
bool awg_calculate_timing(uint32_t timer_hz, uint32_t output_hz, awg_timing_t *timing);

#endif
