#include "logic_trigger.h"

#include <stdio.h>

#define CHECK(x) \
    do { \
        if (!(x)) { \
            fprintf(stderr, "Failed line %d: %s\n", __LINE__, #x); \
            return 1; \
        } \
    } while (0)

/* Channel n sits at bit n of the port halfword shifted down by LOGIC_CHANNEL_SHIFT. */
static uint16_t port(uint8_t channels)
{
    return (uint16_t)((uint16_t)channels << LOGIC_CHANNEL_SHIFT);
}

int main(void)
{
    CHECK(logic_channels(port(0xa5U)) == 0xa5U);
    /* Bits below PE7 belong to other peripherals and must not leak into a channel. */
    CHECK(logic_channels((uint16_t)(port(0x3cU) | 0x7fU)) == 0x3cU);

    uint16_t samples[] = {port(0x00U), port(0x01U), port(0x03U), port(0x02U),
                          port(0x06U), port(0x04U), port(0x00U)};
    const uint16_t length = 7U;
    uint16_t index = 0U;

    logic_trigger_t rising = {.mode = LOGIC_TRIGGER_RISING, .channel = 0U};
    CHECK(logic_find_trigger(samples, length, &rising, 1U, 6U, &index));
    CHECK(index == 1U);

    logic_trigger_t falling = {.mode = LOGIC_TRIGGER_FALLING, .channel = 0U};
    CHECK(logic_find_trigger(samples, length, &falling, 1U, 6U, &index));
    CHECK(index == 3U);

    logic_trigger_t channel_two = {.mode = LOGIC_TRIGGER_RISING, .channel = 2U};
    CHECK(logic_find_trigger(samples, length, &channel_two, 1U, 6U, &index));
    CHECK(index == 4U);

    logic_trigger_t unused = {.mode = LOGIC_TRIGGER_RISING, .channel = 7U};
    CHECK(!logic_find_trigger(samples, length, &unused, 1U, 6U, &index));

    /* A pattern matches on entry, so an already-matching sample does not retrigger. */
    logic_trigger_t pattern = {.mode = LOGIC_TRIGGER_PATTERN, .mask = 0x03U, .value = 0x02U};
    CHECK(logic_find_trigger(samples, length, &pattern, 1U, 6U, &index));
    CHECK(index == 3U);
    logic_trigger_t held = {.mode = LOGIC_TRIGGER_PATTERN, .mask = 0x03U, .value = 0x03U};
    CHECK(logic_find_trigger(samples, length, &held, 3U, 6U, &index) == false);

    /* Masked bits are ignored, so only channel 1 decides this match. */
    logic_trigger_t masked = {.mode = LOGIC_TRIGGER_PATTERN, .mask = 0x02U, .value = 0x02U};
    CHECK(logic_find_trigger(samples, length, &masked, 1U, 6U, &index));
    CHECK(index == 2U);

    logic_trigger_t free_run = {.mode = LOGIC_TRIGGER_FREE};
    CHECK(!logic_find_trigger(samples, length, &free_run, 1U, 6U, &index));
    logic_trigger_t empty_mask = {.mode = LOGIC_TRIGGER_PATTERN, .mask = 0U};
    CHECK(!logic_find_trigger(samples, length, &empty_mask, 1U, 6U, &index));
    logic_trigger_t bad_channel = {.mode = LOGIC_TRIGGER_RISING, .channel = LOGIC_CHANNEL_COUNT};
    CHECK(!logic_find_trigger(samples, length, &bad_channel, 1U, 6U, &index));
    CHECK(!logic_find_trigger(samples, length, &rising, 0U, 6U, &index));
    CHECK(!logic_find_trigger(samples, length, &rising, 1U, length, &index));
    CHECK(!logic_find_trigger(samples, length, &rising, 4U, 2U, &index));
    CHECK(!logic_find_trigger(NULL, length, &rising, 1U, 6U, &index));

    /* The window bounds the search even when a later edge exists. */
    CHECK(!logic_find_trigger(samples, length, &channel_two, 1U, 3U, &index));

    uint8_t extracted[7];
    logic_extract(samples, length, extracted);
    CHECK(extracted[0] == 0x00U && extracted[2] == 0x03U && extracted[6] == 0x00U);

    puts("Logic edge, pattern and extraction checks passed.");
    return 0;
}
