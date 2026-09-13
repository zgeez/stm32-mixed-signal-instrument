#ifndef PROBE_DIVIDER_H
#define PROBE_DIVIDER_H

#include <stdbool.h>
#include <stdint.h>

/* TIM3 sits on APB1, whose timer clock is twice the 42 MHz bus clock. */
#define PROBE_CLOCK_HZ 84000000U
#define PROBE_MIN_HZ 1U
#define PROBE_MAX_HZ (PROBE_CLOCK_HZ / 2U)

typedef struct {
    uint16_t prescaler;
    uint16_t reload;
    uint16_t compare;
    uint32_t actual_hz;
} probe_divider_t;

/* Split a requested frequency across the 16-bit prescaler and reload registers.
   Duty is thousandths; the compare value is clamped so the pin always toggles. */
bool probe_divider(uint32_t frequency_hz, uint16_t duty_permille, probe_divider_t *out);

#endif
