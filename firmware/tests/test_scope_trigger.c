#include "scope_trigger.h"

#include <stdio.h>

#define CHECK(x) \
    do { \
        if (!(x)) { \
            fprintf(stderr, "Failed line %d: %s\n", __LINE__, #x); \
            return 1; \
        } \
    } while (0)

int main(void)
{
    uint32_t samples[] = {
        1000U | (3000U << 16), 1500U | (2500U << 16), 2100U | (1900U << 16),
        2500U | (1000U << 16), 1800U | (2200U << 16)};
    uint16_t index = 0U;
    CHECK(scope_find_trigger(samples, 5U, 0U, SCOPE_TRIGGER_RISING, 2000U, 1U, 4U,
                             &index));
    CHECK(index == 2U);
    CHECK(scope_find_trigger(samples, 5U, 1U, SCOPE_TRIGGER_FALLING, 2000U, 1U, 4U,
                             &index));
    CHECK(index == 2U);
    CHECK(!scope_find_trigger(samples, 5U, 0U, SCOPE_TRIGGER_RISING, 4095U, 1U, 4U,
                              &index));
    CHECK(!scope_find_trigger(samples, 5U, 2U, SCOPE_TRIGGER_RISING, 2000U, 1U, 4U,
                              &index));
    puts("Scope edge detection passed.");
    return 0;
}
