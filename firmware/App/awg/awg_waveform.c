#include "awg_waveform.h"

#include <math.h>
#include <stddef.h>

bool awg_build_lut(awg_waveform_t waveform, uint16_t samples[AWG_SAMPLE_COUNT])
{
    if (samples == NULL || waveform < AWG_SINE || waveform > AWG_SQUARE) {
        return false;
    }
    for (uint32_t i = 0; i < AWG_SAMPLE_COUNT; ++i) {
        switch (waveform) {
        case AWG_SINE:
            samples[i] =
                (uint16_t)(2048.0f +
                           1536.0f * sinf(6.283185307179586f * (float)i / AWG_SAMPLE_COUNT) + 0.5f);
            break;
        case AWG_TRIANGLE: {
            uint32_t ramp = i < AWG_SAMPLE_COUNT / 2U ? i : AWG_SAMPLE_COUNT - i;
            samples[i] = (uint16_t)(AWG_LOW_CODE + (AWG_HIGH_CODE - AWG_LOW_CODE) * ramp /
                                                       (AWG_SAMPLE_COUNT / 2U));
            break;
        }
        case AWG_SQUARE:
            samples[i] = i < AWG_SAMPLE_COUNT / 2U ? AWG_HIGH_CODE : AWG_LOW_CODE;
            break;
        }
    }
    return true;
}

bool awg_calculate_timing(uint32_t timer_hz, uint32_t output_hz, awg_timing_t *timing)
{
    if (timing == NULL || output_hz < AWG_MIN_HZ || output_hz > AWG_MAX_HZ) {
        return false;
    }
    uint64_t sample_hz = (uint64_t)output_hz * AWG_SAMPLE_COUNT;
    if (timer_hz < sample_hz) {
        return false;
    }
    /* Smallest prescaler that lets the sample period fit the 16-bit counter. */
    uint64_t prescale = ((uint64_t)timer_hz + sample_hz * 65536U - 1U) / (sample_hz * 65536U);
    uint64_t divisor = sample_hz * prescale;
    uint64_t ticks = ((uint64_t)timer_hz + divisor / 2U) / divisor;
    if (prescale > 65536U || ticks == 0U || ticks > 65536U) {
        return false;
    }
    uint64_t cycle_ticks = prescale * ticks * AWG_SAMPLE_COUNT;
    timing->prescaler = (uint16_t)(prescale - 1U);
    timing->period = (uint16_t)(ticks - 1U);
    timing->actual_millihz =
        (uint32_t)(((uint64_t)timer_hz * 1000U + cycle_ticks / 2U) / cycle_ticks);
    return true;
}
