#ifndef SCOPE_TRIGGER_H
#define SCOPE_TRIGGER_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    SCOPE_TRIGGER_FREE,
    SCOPE_TRIGGER_RISING,
    SCOPE_TRIGGER_FALLING
} scope_trigger_edge_t;

bool scope_find_trigger(const uint32_t *samples, uint16_t length, uint8_t channel,
                        scope_trigger_edge_t edge, uint16_t level, uint16_t first,
                        uint16_t last, uint16_t *index);

#endif
