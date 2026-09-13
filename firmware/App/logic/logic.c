#include "logic.h"

#include "FreeRTOS.h"
#include "ownership.h"
#include "task.h"
#include "tasks.h"
#include "main.h"
#include "tim.h"
#include <string.h>

#define LOGIC_RAW_SAMPLES (2U * LOGIC_MAX_SAMPLES)
#define TIM1_CLOCK_HZ 168000000U

extern DMA_HandleTypeDef hdma_tim1_up;

static uint16_t raw_samples[LOGIC_RAW_SAMPLES];
static uint8_t capture_samples[LOGIC_MAX_SAMPLES];
static logic_status_t status = {
    .state = LOGIC_IDLE,
    .config = {.sample_rate = 1000000U,
               .sample_count = 1024U,
               .trigger = {.mode = LOGIC_TRIGGER_FREE},
               .pretrigger_permille = 500U},
    .actual_rate = 1000000U};
static volatile bool dma_complete;
static volatile bool dma_failed;
static volatile bool dma_overrun;

static bool claim_hardware(void)
{
    taskENTER_CRITICAL();
    bool granted = ownership_claim(&acquisition_ownership, ACQUISITION_LOGIC);
    taskEXIT_CRITICAL();
    return granted;
}

static void release_hardware(void)
{
    taskENTER_CRITICAL();
    ownership_release(&acquisition_ownership, ACQUISITION_LOGIC);
    taskEXIT_CRITICAL();
}

static bool valid_rate(uint32_t rate)
{
    return rate == 1000000U || rate == 2000000U || rate == 5000000U || rate == 10000000U;
}

static uint32_t rate_divider(uint32_t rate)
{
    return (TIM1_CLOCK_HZ + rate / 2U) / rate;
}

uint32_t logic_actual_rate(uint32_t requested_rate)
{
    if (!valid_rate(requested_rate)) {
        return 0U;
    }
    return TIM1_CLOCK_HZ / rate_divider(requested_rate);
}

static void complete_callback(DMA_HandleTypeDef *hdma)
{
    (void)hdma;
    HAL_TIM_Base_Stop(&htim1);
    dma_complete = true;
    tasks_notify_acquire();
}

static void error_callback(DMA_HandleTypeDef *hdma)
{
    /* A FIFO or direct-mode error means the controller could not keep up with the
       timer; a transfer error means the transaction itself failed. */
    if ((hdma->ErrorCode & (HAL_DMA_ERROR_FE | HAL_DMA_ERROR_DME)) != 0U) {
        dma_overrun = true;
    }
    if ((hdma->ErrorCode & HAL_DMA_ERROR_TE) != 0U) {
        dma_failed = true;
    }
    tasks_notify_acquire();
}

static void stop_hardware(void)
{
    HAL_TIM_Base_Stop(&htim1);
    __HAL_TIM_DISABLE_DMA(&htim1, TIM_DMA_UPDATE);
    HAL_DMA_Abort(&hdma_tim1_up);
}

static bool start_hardware(void)
{
    uint32_t raw_count = (uint32_t)status.config.sample_count * 2U;
    __HAL_TIM_DISABLE_DMA(&htim1, TIM_DMA_UPDATE);
    __HAL_TIM_SET_AUTORELOAD(&htim1, rate_divider(status.config.sample_rate) - 1U);
    __HAL_TIM_SET_COUNTER(&htim1, 0U);
    dma_complete = false;
    dma_failed = false;
    dma_overrun = false;
    hdma_tim1_up.XferCpltCallback = complete_callback;
    hdma_tim1_up.XferErrorCallback = error_callback;
    if (HAL_DMA_Start_IT(&hdma_tim1_up, (uint32_t)&LOGIC_D0_GPIO_Port->IDR,
                         (uint32_t)raw_samples, raw_count) != HAL_OK) {
        return false;
    }
    /* HAL_DMA_Start_IT leaves the FIFO error interrupt masked. */
    __HAL_DMA_ENABLE_IT(&hdma_tim1_up, DMA_IT_FE);
    __HAL_TIM_ENABLE_DMA(&htim1, TIM_DMA_UPDATE);
    if (HAL_TIM_Base_Start(&htim1) != HAL_OK) {
        stop_hardware();
        return false;
    }
    return true;
}

logic_result_t logic_configure(const logic_config_t *config)
{
    if (config == NULL || status.state == LOGIC_ARMED || !valid_rate(config->sample_rate) ||
        config->sample_count < 64U || config->sample_count > LOGIC_MAX_SAMPLES ||
        config->trigger.mode > LOGIC_TRIGGER_PATTERN ||
        config->trigger.channel >= LOGIC_CHANNEL_COUNT ||
        (config->trigger.mode == LOGIC_TRIGGER_PATTERN && config->trigger.mask == 0U) ||
        config->pretrigger_permille > 900U) {
        return status.state == LOGIC_ARMED ? LOGIC_BUSY : LOGIC_INVALID;
    }
    status.config = *config;
    status.actual_rate = logic_actual_rate(config->sample_rate);
    status.trigger_index =
        (uint16_t)((uint32_t)config->sample_count * config->pretrigger_permille / 1000U);
    status.state = LOGIC_IDLE;
    return LOGIC_OK;
}

logic_result_t logic_arm(void)
{
    if (status.state == LOGIC_ARMED) {
        return LOGIC_BUSY;
    }
    if (!claim_hardware()) {
        return LOGIC_BUSY;
    }
    if (!start_hardware()) {
        release_hardware();
        ++status.dma_errors;
        status.state = LOGIC_FAULT;
        return LOGIC_HW_ERROR;
    }
    status.state = LOGIC_ARMED;
    return LOGIC_OK;
}

logic_result_t logic_stop(void)
{
    if (status.state == LOGIC_ARMED) {
        stop_hardware();
    }
    release_hardware();
    status.state = LOGIC_IDLE;
    return LOGIC_OK;
}

logic_status_t logic_get_status(void)
{
    return status;
}

bool logic_read(uint32_t capture_id, uint16_t offset, uint8_t count, uint8_t *samples)
{
    if (status.state != LOGIC_COMPLETE || capture_id != status.capture_id || count == 0U ||
        samples == NULL || (uint32_t)offset + count > status.config.sample_count) {
        return false;
    }
    memcpy(samples, capture_samples + offset, count);
    return true;
}

void logic_process(void)
{
    if (status.state != LOGIC_ARMED) {
        return;
    }
    if (dma_failed || dma_overrun) {
        stop_hardware();
        status.overruns += dma_overrun;
        status.dma_errors += dma_failed;
        status.state = LOGIC_FAULT;
        release_hardware();
        return;
    }
    if (!dma_complete) {
        return;
    }
    stop_hardware();

    uint16_t count = status.config.sample_count;
    uint16_t pre = (uint16_t)((uint32_t)count * status.config.pretrigger_permille / 1000U);
    uint16_t trigger = pre;
    bool found = status.config.trigger.mode == LOGIC_TRIGGER_FREE;
    if (!found) {
        uint16_t first = pre == 0U ? 1U : pre;
        found = logic_find_trigger(raw_samples, (uint16_t)(2U * count), &status.config.trigger,
                                   first, (uint16_t)(count + pre), &trigger);
    }
    if (!found) {
        ++status.trigger_misses;
        if (!start_hardware()) {
            ++status.dma_errors;
            status.state = LOGIC_FAULT;
            release_hardware();
        }
        return;
    }
    logic_extract(raw_samples + trigger - pre, count, capture_samples);
    status.trigger_index = pre;
    ++status.capture_id;
    status.state = LOGIC_COMPLETE;
}
