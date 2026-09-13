/* FreeRTOS configuration for the mixed-signal instrument.
 *
 * FreeRTOS is vendored from STM32Cube FW_F4 V1.28.3 rather than configured through
 * CubeMX, because the X-CUBE-FREERTOS pack is not installed. CubeMX therefore owns the
 * peripherals and the TIM7 HAL timebase; this file owns the kernel.
 *
 * The CMSIS-RTOS v2 wrapper fixes several of these values. freertos_os2.h fails the
 * build with an explicit #error if any of them is wrong, so do not "simplify" them:
 * configMAX_PRIORITIES must be exactly 56, configUSE_16_BIT_TICKS must be 0, and
 * configUSE_PORT_OPTIMISED_TASK_SELECTION must be 0.
 */
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

#include <stdint.h>
extern uint32_t SystemCoreClock;

/* The CMSIS-RTOS v2 wrapper includes this to reach NVIC_SetPriority and SysTick. */
#define CMSIS_device_header "stm32f4xx.h"

#define configUSE_PREEMPTION                     1
#define configUSE_PORT_OPTIMISED_TASK_SELECTION  0
#define configUSE_TICKLESS_IDLE                  0
#define configCPU_CLOCK_HZ                       (SystemCoreClock)
#define configTICK_RATE_HZ                       ((TickType_t)1000)
#define configMAX_PRIORITIES                     56
#define configMINIMAL_STACK_SIZE                 ((uint16_t)128)
#define configTOTAL_HEAP_SIZE                    ((size_t)16384)
#define configMAX_TASK_NAME_LEN                  16
#define configUSE_16_BIT_TICKS                   0
#define configIDLE_SHOULD_YIELD                  1
#define configUSE_TASK_NOTIFICATIONS             1
#define configUSE_MUTEXES                        1
#define configUSE_RECURSIVE_MUTEXES              1
#define configUSE_COUNTING_SEMAPHORES            1
#define configQUEUE_REGISTRY_SIZE                8
#define configUSE_APPLICATION_TASK_TAG           0
#define configSUPPORT_STATIC_ALLOCATION          0
#define configSUPPORT_DYNAMIC_ALLOCATION         1

/* Acquisition and refill deadlines are measured in these, so keep them available. */
#define configUSE_TRACE_FACILITY                 1
#define configUSE_STATS_FORMATTING_FUNCTIONS     0
#define configGENERATE_RUN_TIME_STATS            0

/* A missed stack or heap bound must fault loudly rather than corrupt a DMA buffer. */
#define configCHECK_FOR_STACK_OVERFLOW           2
#define configUSE_MALLOC_FAILED_HOOK             1
#define configUSE_IDLE_HOOK                      0
#define configUSE_TICK_HOOK                      0
#define configUSE_DAEMON_TASK_STARTUP_HOOK       0

#define configUSE_TIMERS                         1
#define configTIMER_TASK_PRIORITY                (configMAX_PRIORITIES - 1)
#define configTIMER_QUEUE_LENGTH                 8
#define configTIMER_TASK_STACK_DEPTH             256

#define configUSE_CO_ROUTINES                    0
#define configMAX_CO_ROUTINE_PRIORITIES          2

#define INCLUDE_vTaskPrioritySet                 1
#define INCLUDE_uxTaskPriorityGet                1
#define INCLUDE_vTaskDelete                      1
#define INCLUDE_vTaskCleanUpResources            0
#define INCLUDE_vTaskSuspend                     1
#define INCLUDE_vTaskDelayUntil                  1
#define INCLUDE_vTaskDelay                       1
#define INCLUDE_xTaskGetSchedulerState           1
#define INCLUDE_xTaskGetCurrentTaskHandle        1
#define INCLUDE_uxTaskGetStackHighWaterMark      1
#define INCLUDE_xTaskGetIdleTaskHandle           1
#define INCLUDE_eTaskGetState                    1
#define INCLUDE_xTimerPendFunctionCall           1
#define INCLUDE_xTaskAbortDelay                  1
#define INCLUDE_xQueueGetMutexHolder             1
#define INCLUDE_xSemaphoreGetMutexHolder         1
#define INCLUDE_xTaskGetHandle                   1

#ifdef __NVIC_PRIO_BITS
#define configPRIO_BITS __NVIC_PRIO_BITS
#else
#define configPRIO_BITS 4
#endif

/* Cortex-M numbers priorities the other way round: smaller is more urgent. An ISR may
 * only call a FromISR API if its priority is numerically >= MAX_SYSCALL. Every
 * peripheral interrupt here sits at 5 or 6, and the TIM7 tick at 5, so all of them
 * qualify. Moving any of them above 5 would silently break the kernel. */
#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY       15
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY  5
#define configKERNEL_INTERRUPT_PRIORITY \
    (configLIBRARY_LOWEST_INTERRUPT_PRIORITY << (8 - configPRIO_BITS))
#define configMAX_SYSCALL_INTERRUPT_PRIORITY \
    (configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY << (8 - configPRIO_BITS))

#define configASSERT(x)              \
    if ((x) == 0) {                  \
        taskDISABLE_INTERRUPTS();    \
        for (;;) {                   \
        }                            \
    }

/* CubeMX no longer emits SVC_Handler or PendSV_Handler, so the port may claim those
 * names. It still emits SysTick_Handler, and deleting that would mean editing outside a
 * user-code region, so the generated one calls xPortSysTickHandler and cmsis_os2.c is
 * told to stand down rather than define a second SysTick_Handler of its own. */
#define vPortSVCHandler    SVC_Handler
#define xPortPendSVHandler PendSV_Handler
#define USE_CUSTOM_SYSTICK_HANDLER_IMPLEMENTATION 1

#endif /* FREERTOS_CONFIG_H */
