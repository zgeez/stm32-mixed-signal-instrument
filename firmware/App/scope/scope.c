#include "scope.h"

#include "adc.h"
#include "tim.h"
#include <string.h>

#define SCOPE_RAW_SAMPLES (2U * SCOPE_MAX_SAMPLES)
#define TIM2_CLOCK_HZ 84000000U

static uint32_t raw_samples[SCOPE_RAW_SAMPLES];
static uint32_t capture_samples[SCOPE_MAX_SAMPLES];
static scope_status_t status = {
    .state = SCOPE_IDLE,
    .config = {.sample_rate = 100000U,
               .sample_count = 512U,
               .trigger_channel = 0U,
               .trigger_edge = SCOPE_TRIGGER_FREE,
               .trigger_level = 2048U,
               .pretrigger_permille = 500U}};
static volatile bool dma_complete;
static volatile bool dma_failed;
static volatile bool adc_overrun;

static bool valid_rate(uint32_t rate)
{
    return rate == 100000U || rate == 500000U || rate == 1000000U;
}

static void stop_hardware(void)
{
    HAL_TIM_Base_Stop(&htim2);
    HAL_ADCEx_MultiModeStop_DMA(&hadc1);
    HAL_ADC_Stop(&hadc2);
}

static bool start_hardware(void)
{
    uint32_t raw_count = (uint32_t)status.config.sample_count * 2U;
    __HAL_TIM_SET_AUTORELOAD(&htim2, TIM2_CLOCK_HZ / status.config.sample_rate - 1U);
    __HAL_TIM_SET_COUNTER(&htim2, 0U);
    dma_complete = false;
    dma_failed = false;
    adc_overrun = false;
    if (HAL_ADC_Start(&hadc2) != HAL_OK) {
        return false;
    }
    if (HAL_ADCEx_MultiModeStart_DMA(&hadc1, raw_samples, raw_count) != HAL_OK) {
        HAL_ADC_Stop(&hadc2);
        return false;
    }
    if (HAL_TIM_Base_Start(&htim2) != HAL_OK) {
        HAL_ADCEx_MultiModeStop_DMA(&hadc1);
        HAL_ADC_Stop(&hadc2);
        return false;
    }
    return true;
}

scope_result_t scope_configure(const scope_config_t *config)
{
    if (config == NULL || status.state == SCOPE_ARMED || !valid_rate(config->sample_rate) ||
        config->sample_count < 64U || config->sample_count > SCOPE_MAX_SAMPLES ||
        config->trigger_channel > 1U || config->trigger_edge > SCOPE_TRIGGER_FALLING ||
        config->trigger_level > 4095U || config->pretrigger_permille > 900U) {
        return status.state == SCOPE_ARMED ? SCOPE_BUSY : SCOPE_INVALID;
    }
    status.config = *config;
    status.trigger_index =
        (uint16_t)((uint32_t)config->sample_count * config->pretrigger_permille / 1000U);
    status.state = SCOPE_IDLE;
    return SCOPE_OK;
}

scope_result_t scope_arm(void)
{
    if (status.state == SCOPE_ARMED) {
        return SCOPE_BUSY;
    }
    if (!start_hardware()) {
        ++status.dma_errors;
        status.state = SCOPE_FAULT;
        return SCOPE_HW_ERROR;
    }
    status.state = SCOPE_ARMED;
    return SCOPE_OK;
}

scope_result_t scope_stop(void)
{
    if (status.state == SCOPE_ARMED) {
        stop_hardware();
    }
    status.state = SCOPE_IDLE;
    return SCOPE_OK;
}

scope_status_t scope_get_status(void)
{
    return status;
}

bool scope_read(uint32_t capture_id, uint16_t offset, uint8_t count, uint32_t *samples)
{
    if (status.state != SCOPE_COMPLETE || capture_id != status.capture_id || count == 0U ||
        samples == NULL || (uint32_t)offset + count > status.config.sample_count) {
        return false;
    }
    memcpy(samples, capture_samples + offset, (size_t)count * sizeof *samples);
    return true;
}

void scope_process(void)
{
    if (status.state != SCOPE_ARMED) {
        return;
    }
    if (dma_failed || adc_overrun) {
        stop_hardware();
        status.overruns += adc_overrun;
        status.dma_errors += dma_failed;
        status.state = SCOPE_FAULT;
        return;
    }
    if (!dma_complete) {
        return;
    }
    stop_hardware();

    uint16_t count = status.config.sample_count;
    uint16_t pre = (uint16_t)((uint32_t)count * status.config.pretrigger_permille / 1000U);
    uint16_t trigger = pre;
    bool found = status.config.trigger_edge == SCOPE_TRIGGER_FREE;
    if (!found) {
        uint16_t first = pre == 0U ? 1U : pre;
        uint16_t last = (uint16_t)(2U * count - (count - pre));
        found = scope_find_trigger(raw_samples, (uint16_t)(2U * count),
                                   status.config.trigger_channel, status.config.trigger_edge,
                                   status.config.trigger_level, first, last, &trigger);
    }
    if (!found) {
        ++status.trigger_misses;
        if (!start_hardware()) {
            ++status.dma_errors;
            status.state = SCOPE_FAULT;
        }
        return;
    }
    memcpy(capture_samples, raw_samples + trigger - pre, (size_t)count * sizeof *capture_samples);
    status.trigger_index = pre;
    ++status.capture_id;
    status.state = SCOPE_COMPLETE;
}

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1) {
        HAL_TIM_Base_Stop(&htim2);
        dma_complete = true;
    }
}

void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1) {
        if ((hadc->ErrorCode & HAL_ADC_ERROR_OVR) != 0U) {
            adc_overrun = true;
        }
        if ((hadc->ErrorCode & HAL_ADC_ERROR_DMA) != 0U) {
            dma_failed = true;
        }
    }
}
