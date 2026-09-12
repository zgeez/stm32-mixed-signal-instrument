#include "logic_trigger.h"
#include <stddef.h>

uint8_t logic_channels(uint16_t port)
{
    return (uint8_t)(port >> LOGIC_CHANNEL_SHIFT);
}

void logic_extract(const uint16_t *port_samples, uint16_t length, uint8_t *out)
{
    if (port_samples == NULL || out == NULL) {
        return;
    }
    for (uint16_t i = 0U; i < length; ++i) {
        out[i] = logic_channels(port_samples[i]);
    }
}

bool logic_find_trigger(const uint16_t *port_samples, uint16_t length,
                        const logic_trigger_t *trigger, uint16_t first, uint16_t last,
                        uint16_t *index)
{
    if (port_samples == NULL || trigger == NULL || index == NULL || first == 0U ||
        first >= length || last >= length || first > last ||
        trigger->mode == LOGIC_TRIGGER_FREE || trigger->mode > LOGIC_TRIGGER_PATTERN ||
        (trigger->mode != LOGIC_TRIGGER_PATTERN && trigger->channel >= LOGIC_CHANNEL_COUNT) ||
        (trigger->mode == LOGIC_TRIGGER_PATTERN && trigger->mask == 0U)) {
        return false;
    }
    uint8_t previous = logic_channels(port_samples[first - 1U]);
    for (uint16_t i = first; i <= last; ++i) {
        uint8_t current = logic_channels(port_samples[i]);
        bool matched;
        if (trigger->mode == LOGIC_TRIGGER_PATTERN) {
            /* Entering the pattern, so a capture already inside it keeps waiting. */
            matched = (current & trigger->mask) == (trigger->value & trigger->mask) &&
                      (previous & trigger->mask) != (trigger->value & trigger->mask);
        } else {
            uint8_t bit = (uint8_t)(1U << trigger->channel);
            matched = trigger->mode == LOGIC_TRIGGER_RISING
                          ? (previous & bit) == 0U && (current & bit) != 0U
                          : (previous & bit) != 0U && (current & bit) == 0U;
        }
        if (matched) {
            *index = i;
            return true;
        }
        previous = current;
    }
    return false;
}
