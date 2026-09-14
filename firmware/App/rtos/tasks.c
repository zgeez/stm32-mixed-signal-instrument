#include "tasks.h"

#include "FreeRTOS.h"
#include "awg.h"
#include "cmsis_os2.h"
#include "logic.h"
#include "mixed.h"
#include "main.h"
#include "scope.h"
#include "task.h"
#include "usb_control.h"

#define FLAG_WAKE 0x01U

/* The control task must still expire a partial frame after 500 ms of silence, so it
 * wakes on this period even when the host sends nothing. */
#define CONTROL_IDLE_MS 10U
#define STATUS_PERIOD_MS 50U

static osThreadId_t threads[TASK_COUNT];

static void notify(app_task_t task)
{
    if (threads[task] != NULL) {
        osThreadFlagsSet(threads[task], FLAG_WAKE);
    }
}

void tasks_notify_awg(void)
{
    notify(TASK_AWG);
}

void tasks_notify_acquire(void)
{
    notify(TASK_ACQUIRE);
}

void tasks_notify_control(void)
{
    notify(TASK_CONTROL);
}

static void awg_thread(void *argument)
{
    (void)argument;
    for (;;) {
        osThreadFlagsWait(FLAG_WAKE, osFlagsWaitAny, osWaitForever);
        awg_process();
    }
}

static void acquire_thread(void *argument)
{
    (void)argument;
    for (;;) {
        osThreadFlagsWait(FLAG_WAKE, osFlagsWaitAny, osWaitForever);
        /* Ownership keeps these from being armed together, so one wakeup can serve
         * both without either stealing the other's bus time. */
        scope_process();
        logic_process();
        mixed_process();
    }
}

static void control_thread(void *argument)
{
    (void)argument;
    for (;;) {
        osThreadFlagsWait(FLAG_WAKE, osFlagsWaitAny, CONTROL_IDLE_MS);
        /* One byte per call, so drain the packet before blocking again. */
        while (usb_control_poll()) {
        }
    }
}

static void status_thread(void *argument)
{
    (void)argument;
    uint32_t led_tick = osKernelGetTickCount();
    for (;;) {
        osDelay(STATUS_PERIOD_MS);
        awg_status_t awg = awg_get_status();
        scope_status_t scope = scope_get_status();
        logic_status_t logic = logic_get_status();
        bool fault = awg.state == AWG_FAULT || scope.state == SCOPE_FAULT ||
                     logic.state == LOGIC_FAULT;
        bool active = awg.state == AWG_RUNNING || scope.state == SCOPE_ARMED ||
                      scope.state == SCOPE_COMPLETE || logic.state == LOGIC_ARMED ||
                      logic.state == LOGIC_COMPLETE;
        uint32_t now = osKernelGetTickCount();
        uint32_t interval = fault ? 100U : 500U;
        if (fault || active) {
            if ((uint32_t)(now - led_tick) >= interval) {
                led_tick = now;
                HAL_GPIO_TogglePin(LD4_GPIO_Port, LD4_Pin);
            }
        } else {
            led_tick = now;
            HAL_GPIO_WritePin(LD4_GPIO_Port, LD4_Pin, GPIO_PIN_RESET);
        }
    }
}

void tasks_create(void)
{
    static const osThreadAttr_t awg_attr = {
        .name = "awg", .stack_size = 2048U, .priority = osPriorityHigh};
    static const osThreadAttr_t acquire_attr = {
        .name = "acquire", .stack_size = 2048U, .priority = osPriorityAboveNormal};
    static const osThreadAttr_t control_attr = {
        .name = "control", .stack_size = 3072U, .priority = osPriorityNormal};
    /* Measured on the board: this task used 384 of 512 bytes under load, because it
     * copies three status structs by value every tick. 128 bytes of margin is too
     * little to absorb interrupt nesting, so give it room. */
    static const osThreadAttr_t status_attr = {
        .name = "status", .stack_size = 1024U, .priority = osPriorityLow};

    threads[TASK_AWG] = osThreadNew(awg_thread, NULL, &awg_attr);
    threads[TASK_ACQUIRE] = osThreadNew(acquire_thread, NULL, &acquire_attr);
    threads[TASK_CONTROL] = osThreadNew(control_thread, NULL, &control_attr);
    threads[TASK_STATUS] = osThreadNew(status_thread, NULL, &status_attr);
    for (unsigned i = 0; i < TASK_COUNT; ++i) {
        if (threads[i] == NULL) {
            Error_Handler();
        }
    }
}

uint32_t tasks_stack_headroom(app_task_t task)
{
    if (task >= TASK_COUNT || threads[task] == NULL) {
        return 0U;
    }
    return (uint32_t)uxTaskGetStackHighWaterMark(threads[task]) * sizeof(StackType_t);
}

uint32_t tasks_heap_free(void)
{
    return (uint32_t)xPortGetFreeHeapSize();
}

uint32_t tasks_heap_low_water(void)
{
    return (uint32_t)xPortGetMinimumEverFreeHeapSize();
}

/* A blown stack or a failed allocation must stop the instrument rather than let DMA
 * keep running against memory that is no longer what the task thinks it is. */
void vApplicationStackOverflowHook(TaskHandle_t task, char *name)
{
    (void)task;
    (void)name;
    Error_Handler();
}

void vApplicationMallocFailedHook(void)
{
    Error_Handler();
}
