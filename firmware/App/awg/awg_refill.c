#include "awg_refill.h"

#include <stddef.h>

#define BIT(index) (1U << (index))

void awg_refill_reset(awg_refill_t *refill, uint8_t active_channels)
{
    *refill = (awg_refill_t){.active_channels = active_channels};
}

awg_refill_event_t awg_refill_complete(awg_refill_t *refill, uint8_t channel, uint8_t half)
{
    if (refill == NULL || channel >= 2U || half >= 2U ||
        (refill->active_channels & BIT(channel)) == 0U) {
        return AWG_REFILL_WAITING;
    }
    /* This stream is now reading the opposite half, even if its peer IRQ is pending. */
    if (((refill->pending | refill->refilling) & BIT(half ^ 1U)) != 0U) {
        return AWG_REFILL_MISSED;
    }
    refill->completed[half] |= BIT(channel);
    if (refill->completed[half] != refill->active_channels) {
        return AWG_REFILL_WAITING;
    }
    refill->completed[half] = 0U;
    uint8_t half_bit = BIT(half);
    if (((refill->pending | refill->refilling) & half_bit) != 0U) {
        return AWG_REFILL_MISSED;
    }
    refill->pending |= half_bit;
    return AWG_REFILL_READY;
}

bool awg_refill_take(awg_refill_t *refill, uint8_t *half)
{
    if (refill == NULL || half == NULL || refill->pending == 0U) {
        return false;
    }
    *half = (refill->pending & BIT(0U)) != 0U ? 0U : 1U;
    refill->pending &= (uint8_t)~BIT(*half);
    refill->refilling |= BIT(*half);
    return true;
}

void awg_refill_finish(awg_refill_t *refill, uint8_t half)
{
    if (refill != NULL && half < 2U) {
        refill->refilling &= (uint8_t)~BIT(half);
    }
}
