#ifndef APP_TASKS_H
#define APP_TASKS_H

#include <stdbool.h>
#include <stdint.h>

/* Ownership of the instrument, one task per deadline:
 *
 * | Task    | Priority     | Owns                              | Woken by            |
 * | ------- | ------------ | --------------------------------- | ------------------- |
 * | awg     | High         | DAC1/2, TIM6, DMA1 S5/S6, buffers | DAC DMA half/full   |
 * | acquire | AboveNormal  | ADC+TIM2+DMA2 S0, TIM1+DMA2 S5    | capture DMA / error |
 * | control | Normal       | USB CDC, parser, reply buffer     | CDC rx / tx done    |
 * | status  | Low          | LD4                               | periodic            |
 *
 * The AWG is highest because its refill deadline is the shortest at 1.28 ms; missing it
 * stops TIM6 and corrupts the output, while a late capture or reply only costs latency.
 */

typedef enum {
    TASK_AWG,
    TASK_ACQUIRE,
    TASK_CONTROL,
    TASK_STATUS,
    TASK_COUNT
} app_task_t;

void tasks_create(void);

/* Wakeups. Safe from an ISR and before the scheduler starts, when they do nothing. */
void tasks_notify_awg(void);
void tasks_notify_acquire(void);
void tasks_notify_control(void);

/* Smallest free stack ever observed, in bytes; 0 before the task exists. */
uint32_t tasks_stack_headroom(app_task_t task);
uint32_t tasks_heap_free(void);
uint32_t tasks_heap_low_water(void);

#endif
