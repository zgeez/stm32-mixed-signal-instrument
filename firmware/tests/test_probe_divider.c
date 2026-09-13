#include "probe_divider.h"

#include <stdio.h>

#define CHECK(x) \
    do { \
        if (!(x)) { \
            fprintf(stderr, "Failed line %d: %s\n", __LINE__, #x); \
            return 1; \
        } \
    } while (0)

static uint32_t ticks(const probe_divider_t *d)
{
    return ((uint32_t)d->prescaler + 1U) * ((uint32_t)d->reload + 1U);
}

int main(void)
{
    probe_divider_t d;

    /* Frequencies that divide the 84 MHz clock exactly must land exactly. */
    CHECK(probe_divider(1000000U, 500U, &d));
    CHECK(ticks(&d) == 84U && d.actual_hz == 1000000U && d.prescaler == 0U);
    CHECK(d.compare == 42U);

    CHECK(probe_divider(10000000U, 500U, &d));
    CHECK(ticks(&d) == 8U && d.actual_hz == 10500000U);

    /* The fastest the timer can toggle is half the clock. */
    CHECK(probe_divider(PROBE_MAX_HZ, 500U, &d));
    CHECK(d.prescaler == 0U && d.reload == 1U && d.actual_hz == PROBE_MAX_HZ);
    CHECK(!probe_divider(PROBE_MAX_HZ + 1U, 500U, &d));

    /* Low frequencies need the prescaler, and the reload should stay wide so the duty
       keeps its resolution. */
    /* 84,000,000 ticks has no exact 16-bit by 16-bit split, so allow a little slack
       in the product while the reported frequency still rounds to the request. */
    CHECK(probe_divider(1U, 500U, &d));
    CHECK(d.actual_hz == 1U);
    CHECK(ticks(&d) > 83990000U && ticks(&d) < 84010000U);
    CHECK(d.reload > 30000U);
    CHECK(!probe_divider(0U, 500U, &d));

    CHECK(probe_divider(1000U, 500U, &d));
    CHECK(d.actual_hz == 1000U);
    CHECK(probe_divider(1282U, 500U, &d));
    CHECK(d.actual_hz == 1282U);

    /* Duty maps onto the compare register and always leaves a real edge. */
    CHECK(probe_divider(1000000U, 100U, &d));
    CHECK(d.compare == 8U);
    CHECK(probe_divider(1000000U, 900U, &d));
    CHECK(d.compare == 76U);
    CHECK(!probe_divider(1000000U, 0U, &d));
    CHECK(!probe_divider(1000000U, 1000U, &d));

    /* At the top the period is only two ticks, so the pin must still toggle. */
    CHECK(probe_divider(PROBE_MAX_HZ, 1U, &d));
    CHECK(d.compare >= 1U && d.compare < (uint32_t)d.reload + 1U);
    CHECK(probe_divider(PROBE_MAX_HZ, 999U, &d));
    CHECK(d.compare >= 1U && d.compare < (uint32_t)d.reload + 1U);

    CHECK(!probe_divider(1000000U, 500U, NULL));

    /* Below a megahertz the period is long enough to land within a tenth of a percent. */
    const uint32_t sweep[] = {10U, 100U, 1000U, 10000U, 100000U, 1000000U};
    for (unsigned i = 0; i < sizeof sweep / sizeof sweep[0]; ++i) {
        CHECK(probe_divider(sweep[i], 500U, &d));
        uint32_t error = d.actual_hz > sweep[i] ? d.actual_hz - sweep[i] : sweep[i] - d.actual_hz;
        CHECK((uint64_t)error * 1000U <= sweep[i]);
    }

    /* Higher up the period is only a handful of ticks, so the reachable set is sparse
       and the caller has to read the actual value back. 84 MHz over 17 ticks is the
       same 4,941,176 the logic analyzer reports when asked for 5 MS/s. */
    CHECK(probe_divider(5000000U, 500U, &d));
    CHECK(ticks(&d) == 17U && d.actual_hz == 4941176U);

    puts("Probe divider arithmetic, limits and duty mapping passed.");
    return 0;
}
