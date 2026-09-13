#include "ownership.h"

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
    ownership_t state = {0};
    CHECK(ownership_current(&state) == ACQUISITION_NONE);
    CHECK(ownership_conflicts(&state) == 0U);

    CHECK(ownership_claim(&state, ACQUISITION_SCOPE));
    CHECK(ownership_current(&state) == ACQUISITION_SCOPE);

    /* Re-arming the holder must succeed; a trigger miss rearms without releasing. */
    CHECK(ownership_claim(&state, ACQUISITION_SCOPE));
    CHECK(ownership_conflicts(&state) == 0U);

    /* The loser is rejected and counted rather than allowed to interfere. */
    CHECK(!ownership_claim(&state, ACQUISITION_LOGIC));
    CHECK(ownership_current(&state) == ACQUISITION_SCOPE);
    CHECK(ownership_conflicts(&state) == 1U);
    CHECK(!ownership_claim(&state, ACQUISITION_LOGIC));
    CHECK(ownership_conflicts(&state) == 2U);

    /* Only the holder may release. */
    CHECK(!ownership_release(&state, ACQUISITION_LOGIC));
    CHECK(ownership_current(&state) == ACQUISITION_SCOPE);
    CHECK(ownership_release(&state, ACQUISITION_SCOPE));
    CHECK(ownership_current(&state) == ACQUISITION_NONE);
    CHECK(!ownership_release(&state, ACQUISITION_SCOPE));

    /* Releasing hands the hardware to the subsystem that was locked out. */
    CHECK(ownership_claim(&state, ACQUISITION_LOGIC));
    CHECK(ownership_current(&state) == ACQUISITION_LOGIC);
    CHECK(!ownership_claim(&state, ACQUISITION_SCOPE));
    CHECK(ownership_release(&state, ACQUISITION_LOGIC));
    CHECK(ownership_claim(&state, ACQUISITION_SCOPE));

    /* Conflicts accumulate across handovers so a stress run can be audited. */
    CHECK(ownership_conflicts(&state) == 3U);

    CHECK(!ownership_claim(&state, ACQUISITION_NONE));
    CHECK(!ownership_release(&state, ACQUISITION_NONE));
    CHECK(!ownership_claim(NULL, ACQUISITION_SCOPE));
    CHECK(!ownership_release(NULL, ACQUISITION_SCOPE));
    CHECK(ownership_current(NULL) == ACQUISITION_NONE);
    CHECK(ownership_conflicts(NULL) == 0U);
    CHECK(ownership_current(&state) == ACQUISITION_SCOPE);

    puts("Acquisition ownership, conflict counting and handover passed.");
    return 0;
}
