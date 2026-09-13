#include "probe_divider.h"
#include <stddef.h>

bool probe_divider(uint32_t frequency_hz, uint16_t duty_permille, probe_divider_t *out)
{
    if (out == NULL || frequency_hz < PROBE_MIN_HZ || frequency_hz > PROBE_MAX_HZ ||
        duty_permille == 0U || duty_permille >= 1000U) {
        return false;
    }
    uint32_t ticks = (PROBE_CLOCK_HZ + frequency_hz / 2U) / frequency_hz;
    if (ticks < 2U) {
        ticks = 2U;
    }
    /* Use the smallest prescaler that brings the period inside 16 bits, so the reload
       stays as large as possible and the duty keeps its resolution. */
    uint32_t prescaler = (ticks + 65535U) / 65536U;
    if (prescaler > 65536U) {
        return false;
    }
    uint32_t period = ticks / prescaler;
    if (period < 2U) {
        period = 2U;
    }
    if (period > 65536U) {
        period = 65536U;
    }
    uint32_t compare = ((uint32_t)duty_permille * period + 500U) / 1000U;
    if (compare == 0U) {
        compare = 1U;
    }
    if (compare >= period) {
        compare = period - 1U;
    }
    out->prescaler = (uint16_t)(prescaler - 1U);
    out->reload = (uint16_t)(period - 1U);
    out->compare = (uint16_t)compare;
    out->actual_hz =
        (uint32_t)(((uint64_t)PROBE_CLOCK_HZ + (uint64_t)prescaler * period / 2U) /
                   ((uint64_t)prescaler * period));
    return true;
}
