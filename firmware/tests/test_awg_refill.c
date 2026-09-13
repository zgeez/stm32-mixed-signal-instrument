#include "awg_refill.h"

#include <stdio.h>

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            fprintf(stderr, "Check failed at line %d: %s\n", __LINE__, #condition); \
            return 1; \
        } \
    } while (0)

int main(void)
{
    awg_refill_t refill;
    uint8_t half;
    awg_refill_reset(&refill, 0x03U);
    CHECK(awg_refill_complete(&refill, 0U, 0U) == AWG_REFILL_WAITING);
    CHECK(awg_refill_complete(&refill, 1U, 0U) == AWG_REFILL_READY);
    CHECK(awg_refill_take(&refill, &half) && half == 0U);
    CHECK(awg_refill_complete(&refill, 1U, 0U) == AWG_REFILL_WAITING);
    CHECK(awg_refill_complete(&refill, 0U, 0U) == AWG_REFILL_MISSED);
    awg_refill_finish(&refill, 0U);

    CHECK(awg_refill_complete(&refill, 0U, 1U) == AWG_REFILL_WAITING);
    CHECK(awg_refill_complete(&refill, 1U, 1U) == AWG_REFILL_READY);
    CHECK(awg_refill_take(&refill, &half) && half == 1U);
    awg_refill_finish(&refill, half);
    CHECK(!awg_refill_take(&refill, &half));

    for (uint8_t first = 0U; first < 2U; ++first) {
        awg_refill_reset(&refill, 3U);
        CHECK(awg_refill_complete(&refill, first, 0U) == AWG_REFILL_WAITING);
        CHECK(awg_refill_complete(&refill, first ^ 1U, 0U) == AWG_REFILL_READY);
        CHECK(awg_refill_complete(&refill, first, 1U) == AWG_REFILL_MISSED);
        CHECK(awg_refill_take(&refill, &half));
        CHECK(awg_refill_complete(&refill, first, 1U) == AWG_REFILL_MISSED);
        awg_refill_finish(&refill, half);
        CHECK(awg_refill_complete(&refill, first, 1U) == AWG_REFILL_WAITING);
        CHECK(awg_refill_complete(&refill, first ^ 1U, 1U) == AWG_REFILL_READY);
        CHECK(awg_refill_complete(&refill, first, 0U) == AWG_REFILL_MISSED);
    }

    awg_refill_reset(&refill, 0x01U);
    CHECK(awg_refill_complete(&refill, 0U, 0U) == AWG_REFILL_READY);
    CHECK(awg_refill_complete(&refill, 1U, 0U) == AWG_REFILL_WAITING);
    puts("Dual-channel ownership and missed-refill detection passed.");
    return 0;
}
