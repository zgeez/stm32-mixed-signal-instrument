#include "scope_trigger.h"
#include <stddef.h>

static uint16_t channel_value(uint32_t packed, uint8_t channel)
{
    return channel == 0U ? (uint16_t)packed : (uint16_t)(packed >> 16U);
}

bool scope_find_trigger(const uint32_t *samples, uint16_t length, uint8_t channel,
                        scope_trigger_edge_t edge, uint16_t level, uint16_t first,
                        uint16_t last, uint16_t *index)
{
    if (samples == NULL || index == NULL || channel > 1U || first == 0U || first >= length ||
        last >= length || first > last || edge == SCOPE_TRIGGER_FREE) {
        return false;
    }
    uint16_t previous = channel_value(samples[first - 1U], channel);
    for (uint16_t i = first; i <= last; ++i) {
        uint16_t current = channel_value(samples[i], channel);
        bool crossed = edge == SCOPE_TRIGGER_RISING ? previous < level && current >= level
                                                    : previous > level && current <= level;
        if (crossed) {
            *index = i;
            return true;
        }
        previous = current;
    }
    return false;
}
