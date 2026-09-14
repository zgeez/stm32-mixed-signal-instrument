#include "mixed_policy.h"

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
    /* Both still filling: nothing to do. */
    CHECK(mixed_next_action(SCOPE_ARMED, LOGIC_ARMED) == MIXED_ACTION_WAIT);

    /* One finished first. The rates differ, so this is the normal case, and the pair is
       not a capture until both have landed. */
    CHECK(mixed_next_action(SCOPE_COMPLETE, LOGIC_ARMED) == MIXED_ACTION_WAIT);
    CHECK(mixed_next_action(SCOPE_ARMED, LOGIC_COMPLETE) == MIXED_ACTION_WAIT);

    CHECK(mixed_next_action(SCOPE_COMPLETE, LOGIC_COMPLETE) == MIXED_ACTION_COMPLETE);

    /* A missed trigger parks the stream idle rather than restarting it alone, so both
       have to go again together. */
    CHECK(mixed_next_action(SCOPE_IDLE, LOGIC_ARMED) == MIXED_ACTION_RESTART);
    CHECK(mixed_next_action(SCOPE_ARMED, LOGIC_IDLE) == MIXED_ACTION_RESTART);
    CHECK(mixed_next_action(SCOPE_IDLE, LOGIC_IDLE) == MIXED_ACTION_RESTART);

    /* A completed stream must not be thrown away because the other one rearmed. */
    CHECK(mixed_next_action(SCOPE_COMPLETE, LOGIC_IDLE) == MIXED_ACTION_RESTART);

    /* A fault outranks everything, including a stream that already completed. */
    CHECK(mixed_next_action(SCOPE_FAULT, LOGIC_ARMED) == MIXED_ACTION_FAULT);
    CHECK(mixed_next_action(SCOPE_ARMED, LOGIC_FAULT) == MIXED_ACTION_FAULT);
    CHECK(mixed_next_action(SCOPE_COMPLETE, LOGIC_FAULT) == MIXED_ACTION_FAULT);
    CHECK(mixed_next_action(SCOPE_FAULT, LOGIC_IDLE) == MIXED_ACTION_FAULT);
    CHECK(mixed_next_action(SCOPE_FAULT, LOGIC_FAULT) == MIXED_ACTION_FAULT);

    puts("Mixed capture policy passed.");
    return 0;
}
