#ifndef AWG_REFILL_H
#define AWG_REFILL_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    AWG_REFILL_WAITING,
    AWG_REFILL_READY,
    AWG_REFILL_MISSED
} awg_refill_event_t;

typedef struct {
    volatile uint8_t active_channels;
    volatile uint8_t completed[2];
    volatile uint8_t pending;
    volatile uint8_t refilling;
} awg_refill_t;

void awg_refill_reset(awg_refill_t *refill, uint8_t active_channels);
awg_refill_event_t awg_refill_complete(awg_refill_t *refill, uint8_t channel, uint8_t half);
bool awg_refill_take(awg_refill_t *refill, uint8_t *half);
void awg_refill_finish(awg_refill_t *refill, uint8_t half);

#endif
