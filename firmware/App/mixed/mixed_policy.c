#include "mixed_policy.h"

mixed_action_t mixed_next_action(scope_state_t scope, logic_state_t logic)
{
    if (scope == SCOPE_FAULT || logic == LOGIC_FAULT) {
        return MIXED_ACTION_FAULT;
    }
    /* A synchronised stream that misses its trigger goes idle instead of restarting
       itself, because restarting one timer alone would destroy the shared origin.
       Seeing either one idle means both have to be armed again together. */
    if (scope == SCOPE_IDLE || logic == LOGIC_IDLE) {
        return MIXED_ACTION_RESTART;
    }
    if (scope == SCOPE_COMPLETE && logic == LOGIC_COMPLETE) {
        return MIXED_ACTION_COMPLETE;
    }
    /* One finished and the other is still armed: the capture is not yet a pair. */
    return MIXED_ACTION_WAIT;
}
