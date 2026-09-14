#include "mixed.h"

#include "FreeRTOS.h"
#include "mixed_policy.h"
#include "ownership.h"
#include "task.h"

static mixed_status_t status;

static bool claim_hardware(void)
{
    taskENTER_CRITICAL();
    bool granted = ownership_claim(&acquisition_ownership, ACQUISITION_MIXED);
    taskEXIT_CRITICAL();
    return granted;
}

static void release_hardware(void)
{
    taskENTER_CRITICAL();
    ownership_release(&acquisition_ownership, ACQUISITION_MIXED);
    taskEXIT_CRITICAL();
}

/* Arm both streams, then release them together. Order matters: the follower has to be
   waiting before the trigger timer starts, or it misses the event that defines zero. */
static bool arm_both(void)
{
    if (scope_arm_synchronised() != SCOPE_OK) {
        return false;
    }
    if (logic_arm_synchronised() != LOGIC_OK) {
        (void)scope_stop();
        return false;
    }
    return logic_release_trigger() == LOGIC_OK;
}

mixed_result_t mixed_arm(mixed_trigger_t trigger)
{
    if (trigger > MIXED_TRIGGER_LOGIC) {
        return MIXED_INVALID;
    }
    if (status.state == MIXED_ARMED) {
        return MIXED_BUSY;
    }
    /* Only the nominated stream may search for an edge. If the follower searched too it
       would pick its own window and the shared origin would mean nothing, so a follower
       that is not free-running is rejected rather than quietly misaligned. */
    if (trigger == MIXED_TRIGGER_SCOPE &&
        logic_get_status().config.trigger.mode != LOGIC_TRIGGER_FREE) {
        return MIXED_INVALID;
    }
    if (trigger == MIXED_TRIGGER_LOGIC &&
        scope_get_status().config.trigger_edge != SCOPE_TRIGGER_FREE) {
        return MIXED_INVALID;
    }
    if (!claim_hardware()) {
        return MIXED_BUSY;
    }
    status.trigger = trigger;
    if (!arm_both()) {
        (void)scope_stop();
        (void)logic_stop();
        scope_follow_trigger(false);
        release_hardware();
        status.state = MIXED_FAULT;
        return MIXED_HW_ERROR;
    }
    status.state = MIXED_ARMED;
    return MIXED_OK;
}

mixed_result_t mixed_stop(void)
{
    if (status.state != MIXED_IDLE) {
        (void)scope_stop();
        (void)logic_stop();
        scope_follow_trigger(false);
    }
    release_hardware();
    status.state = MIXED_IDLE;
    return MIXED_OK;
}

void mixed_process(void)
{
    if (status.state != MIXED_ARMED) {
        return;
    }
    scope_status_t scope = scope_get_status();
    logic_status_t logic = logic_get_status();

    switch (mixed_next_action(scope.state, logic.state)) {
    case MIXED_ACTION_FAULT:
        (void)scope_stop();
        (void)logic_stop();
        scope_follow_trigger(false);
        release_hardware();
        status.state = MIXED_FAULT;
        break;
    case MIXED_ACTION_RESTART:
        (void)scope_stop();
        (void)logic_stop();
        ++status.restarts;
        if (!arm_both()) {
            scope_follow_trigger(false);
            release_hardware();
            status.state = MIXED_FAULT;
        }
        break;
    case MIXED_ACTION_COMPLETE:
        status.scope_capture_id = scope.capture_id;
        status.logic_capture_id = logic.capture_id;
        ++status.capture_id;
        status.state = MIXED_COMPLETE;
        break;
    case MIXED_ACTION_WAIT:
        break;
    }
}

mixed_status_t mixed_get_status(void)
{
    return status;
}
