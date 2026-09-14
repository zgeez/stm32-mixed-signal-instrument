#ifndef MIXED_H
#define MIXED_H

#include "logic.h"
#include "scope.h"

/* Mixed capture runs the analog and digital streams from one timer event so their
 * samples can be placed on a single timeline.
 *
 * TIM1's trigger output is set to fire when it is enabled, and TIM2 follows it through
 * ITR0, so starting TIM1 releases both. That gives a shared origin; it does not make the
 * two streams sample at the same instants. The ADC holds its input for three cycles
 * after its trigger, while a GPIO read happens whenever the DMA wins the bus. The
 * residual skew is measured on the board, not assumed away.
 *
 * Only one stream may hold the trigger. The other is placed by index against the shared
 * origin, since a second independent search would break the alignment it is meant to
 * establish.
 */

typedef enum {
    MIXED_IDLE,
    MIXED_ARMED,
    MIXED_COMPLETE,
    MIXED_FAULT
} mixed_state_t;

typedef enum {
    MIXED_TRIGGER_SCOPE,
    MIXED_TRIGGER_LOGIC
} mixed_trigger_t;

typedef enum {
    MIXED_OK,
    MIXED_INVALID,
    MIXED_BUSY,
    MIXED_HW_ERROR
} mixed_result_t;

typedef struct {
    mixed_state_t state;
    mixed_trigger_t trigger;
    uint32_t capture_id;
    uint32_t restarts;
    uint32_t scope_capture_id;
    uint32_t logic_capture_id;
} mixed_status_t;

mixed_result_t mixed_arm(mixed_trigger_t trigger);
mixed_result_t mixed_stop(void);
mixed_status_t mixed_get_status(void);
void mixed_process(void);

#endif
