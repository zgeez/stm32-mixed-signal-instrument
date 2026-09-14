#ifndef MIXED_POLICY_H
#define MIXED_POLICY_H

#include "logic.h"
#include "scope.h"

/* What a mixed capture should do next, given where its two streams have got to.
   Kept free of HAL and RTOS calls so the decision can be tested on the host. */

typedef enum {
    MIXED_ACTION_WAIT,
    MIXED_ACTION_RESTART,
    MIXED_ACTION_COMPLETE,
    MIXED_ACTION_FAULT
} mixed_action_t;

mixed_action_t mixed_next_action(scope_state_t scope, logic_state_t logic);

#endif
