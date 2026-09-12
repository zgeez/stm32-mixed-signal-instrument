#ifndef LOGIC_TRIGGER_H
#define LOGIC_TRIGGER_H

#include <stdbool.h>
#include <stdint.h>

/* Channel 0 is PE7, so channel n is bit n of GPIOE->IDR shifted down by seven. */
#define LOGIC_CHANNEL_COUNT 8U
#define LOGIC_CHANNEL_SHIFT 7U

typedef enum {
    LOGIC_TRIGGER_FREE,
    LOGIC_TRIGGER_RISING,
    LOGIC_TRIGGER_FALLING,
    LOGIC_TRIGGER_PATTERN
} logic_trigger_mode_t;

typedef struct {
    logic_trigger_mode_t mode;
    uint8_t channel;
    uint8_t mask;
    uint8_t value;
} logic_trigger_t;

uint8_t logic_channels(uint16_t port);
void logic_extract(const uint16_t *port_samples, uint16_t length, uint8_t *out);
bool logic_find_trigger(const uint16_t *port_samples, uint16_t length,
                        const logic_trigger_t *trigger, uint16_t first, uint16_t last,
                        uint16_t *index);

#endif
