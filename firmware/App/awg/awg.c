#include "awg.h"

#include "awg_refill.h"
#include "tasks.h"

#include "dac.h"
#include "tim.h"

#include <string.h>

#define CHANNEL_BIT(channel) (1U << (channel))

_Alignas(4) static uint16_t dma_samples[AWG_CHANNEL_COUNT][AWG_DMA_SAMPLE_COUNT];
_Alignas(4) static uint16_t arbitrary[AWG_CHANNEL_COUNT][AWG_ARBITRARY_MAX_SAMPLES];
static awg_generator_t generators[AWG_CHANNEL_COUNT];
static awg_config_t configs[AWG_CHANNEL_COUNT];
static uint16_t arbitrary_uploaded[AWG_CHANNEL_COUNT];
static uint16_t arbitrary_length[AWG_CHANNEL_COUNT];
static uint8_t configured_mask;
static volatile uint8_t active_mask;
static awg_refill_t refill;
static volatile awg_state_t state;
static volatile uint32_t underruns;
static volatile uint32_t dma_errors;
static volatile uint32_t refill_misses;
/* Debugger-readable timing, reset on Start. Cycles include task scheduling and rendering. */
static volatile uint32_t refill_max_cycles;
static volatile uint32_t refill_count;
static uint32_t refill_started[2];

static uint32_t dac_channel(uint8_t channel)
{
    return channel == 0U ? DAC_CHANNEL_1 : DAC_CHANNEL_2;
}

static DMA_HandleTypeDef *dma_handle(uint8_t channel)
{
    return channel == 0U ? hdac.DMA_Handle1 : hdac.DMA_Handle2;
}

awg_result_t awg_configure(awg_waveform_t waveform, uint32_t frequency_hz)
{
    if (frequency_hz < AWG_MIN_MILLIHZ / 1000U ||
        frequency_hz > AWG_MAX_MILLIHZ / 1000U) {
        return AWG_INVALID;
    }
    awg_config_t config = {.waveform = waveform,
                           .frequency_millihz = frequency_hz * 1000U,
                           .amplitude_permille = 750U,
                           .offset_permille = 500U,
                           .phase_decidegrees = 0U};
    return awg_configure_channel(0U, &config);
}

awg_result_t awg_configure_channel(uint8_t channel, const awg_config_t *config)
{
    if (state == AWG_RUNNING) {
        return AWG_BUSY;
    }
    if (state == AWG_FAULT) {
        return AWG_HW_ERROR;
    }
    uint16_t length = channel < AWG_CHANNEL_COUNT ? arbitrary_length[channel] : 0U;
    if (channel >= AWG_CHANNEL_COUNT || !awg_config_valid(config, length)) {
        return AWG_INVALID;
    }
    const uint16_t *table = config->waveform == AWG_ARBITRARY ? arbitrary[channel] : NULL;
    if (!awg_generator_init(&generators[channel], config, table, length)) {
        return AWG_INVALID;
    }
    configs[channel] = *config;
    configured_mask |= CHANNEL_BIT(channel);
    state = AWG_READY;
    return AWG_OK;
}

awg_result_t awg_upload_arbitrary(uint8_t channel, uint16_t offset, const uint16_t *samples,
                                  uint8_t count)
{
    if (state == AWG_RUNNING) {
        return AWG_BUSY;
    }
    if (channel >= AWG_CHANNEL_COUNT || samples == NULL || count == 0U ||
        (offset != 0U && offset != arbitrary_uploaded[channel]) ||
        offset + count > AWG_ARBITRARY_MAX_SAMPLES) {
        return AWG_INVALID;
    }
    if (offset == 0U) {
        arbitrary_uploaded[channel] = 0U;
        arbitrary_length[channel] = 0U;
    }
    for (uint8_t i = 0U; i < count; ++i) {
        if (samples[i] > AWG_DAC_MAX_CODE) {
            return AWG_INVALID;
        }
    }
    memcpy(&arbitrary[channel][offset], samples, count * sizeof(*samples));
    arbitrary_uploaded[channel] = (uint16_t)(offset + count);
    return AWG_OK;
}

awg_result_t awg_commit_arbitrary(uint8_t channel, uint16_t length)
{
    if (state == AWG_RUNNING) {
        return AWG_BUSY;
    }
    if (channel >= AWG_CHANNEL_COUNT || length < 2U ||
        length != arbitrary_uploaded[channel]) {
        return AWG_INVALID;
    }
    arbitrary_length[channel] = length;
    return AWG_OK;
}

static bool stop_dma(void)
{
    bool ok = true;
    for (uint8_t channel = 0U; channel < AWG_CHANNEL_COUNT; ++channel) {
        if ((active_mask & CHANNEL_BIT(channel)) != 0U) {
            (void)HAL_DAC_Stop_DMA(&hdac, dac_channel(channel));
            ok = ok && (dma_handle(channel)->Instance->CR & DMA_SxCR_EN) == 0U;
        }
    }
    return ok;
}

awg_result_t awg_stop(void)
{
    (void)HAL_TIM_Base_Stop(&htim6);
    bool stopped = stop_dma();
    active_mask = 0U;
    awg_refill_reset(&refill, 0U);
    __HAL_DAC_CLEAR_FLAG(&hdac, DAC_FLAG_DMAUDR1 | DAC_FLAG_DMAUDR2);
    state = stopped ? (configured_mask != 0U ? AWG_READY : AWG_UNCONFIGURED) : AWG_FAULT;
    return stopped ? AWG_OK : AWG_HW_ERROR;
}

awg_result_t awg_start(void)
{
    if (state == AWG_RUNNING) {
        return AWG_BUSY;
    }
    if (state != AWG_READY || configured_mask == 0U) {
        return state == AWG_FAULT ? AWG_HW_ERROR : AWG_INVALID;
    }
    (void)HAL_TIM_Base_Stop(&htim6);
    CLEAR_BIT(hdac.Instance->CR, DAC_CR_TEN1 | DAC_CR_TEN2);
    __HAL_TIM_SET_COUNTER(&htim6, 0U);
    htim6.Instance->EGR = TIM_EGR_UG;
    __HAL_TIM_CLEAR_FLAG(&htim6, TIM_FLAG_UPDATE);
    active_mask = configured_mask;
    for (uint8_t channel = 0U; channel < AWG_CHANNEL_COUNT; ++channel) {
        if ((active_mask & CHANNEL_BIT(channel)) == 0U) {
            continue;
        }
        const uint16_t *table = configs[channel].waveform == AWG_ARBITRARY
                                    ? arbitrary[channel]
                                    : NULL;
        if (!awg_generator_init(&generators[channel], &configs[channel], table,
                                arbitrary_length[channel])) {
            (void)stop_dma();
            state = AWG_FAULT;
            active_mask = 0U;
            return AWG_HW_ERROR;
        }
        uint16_t first = awg_generator_next(&generators[channel]);
        awg_generator_render(&generators[channel], dma_samples[channel], AWG_DMA_SAMPLE_COUNT);
        if (HAL_DAC_SetValue(&hdac, dac_channel(channel), DAC_ALIGN_12B_R, first) != HAL_OK ||
            HAL_DAC_Start_DMA(&hdac, dac_channel(channel),
                              (const uint32_t *)dma_samples[channel], AWG_DMA_SAMPLE_COUNT,
                              DAC_ALIGN_12B_R) != HAL_OK) {
            (void)stop_dma();
            active_mask = 0U;
            state = AWG_FAULT;
            return AWG_HW_ERROR;
        }
    }
    if ((active_mask & CHANNEL_BIT(0U)) != 0U) {
        SET_BIT(hdac.Instance->CR, DAC_CR_TEN1);
    }
    if ((active_mask & CHANNEL_BIT(1U)) != 0U) {
        SET_BIT(hdac.Instance->CR, DAC_CR_TEN2);
    }
#ifdef DEBUG
    __HAL_DBGMCU_FREEZE_TIM6();
#endif
    awg_refill_reset(&refill, active_mask);
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    refill_max_cycles = 0U;
    refill_count = 0U;
    __DMB();
    state = AWG_RUNNING;
    if (HAL_TIM_Base_Start(&htim6) != HAL_OK) {
        (void)awg_stop();
        state = AWG_FAULT;
        return AWG_HW_ERROR;
    }
    return AWG_OK;
}

void awg_process(void)
{
    while (state == AWG_RUNNING) {
        uint32_t mask = __get_PRIMASK();
        __disable_irq();
        uint8_t half;
        if (!awg_refill_take(&refill, &half)) {
            __set_PRIMASK(mask);
            return;
        }
        __set_PRIMASK(mask);

        for (uint8_t channel = 0U; channel < AWG_CHANNEL_COUNT; ++channel) {
            if ((active_mask & CHANNEL_BIT(channel)) != 0U) {
                awg_generator_render(&generators[channel],
                                     &dma_samples[channel][half * AWG_DMA_HALF_SAMPLES],
                                     AWG_DMA_HALF_SAMPLES);
            }
        }

        mask = __get_PRIMASK();
        __disable_irq();
        __DMB();
        uint32_t elapsed = DWT->CYCCNT - refill_started[half];
        if (elapsed > refill_max_cycles) {
            refill_max_cycles = elapsed;
        }
        ++refill_count;
        awg_refill_finish(&refill, half);
        __set_PRIMASK(mask);
    }
}

static void dma_complete(uint8_t channel, uint8_t half)
{
    uint8_t bit = CHANNEL_BIT(channel);
    if (state != AWG_RUNNING || (active_mask & bit) == 0U) {
        return;
    }
    if (refill.completed[half] == 0U) {
        refill_started[half] = DWT->CYCCNT;
    }
    switch (awg_refill_complete(&refill, channel, half)) {
    case AWG_REFILL_READY:
        tasks_notify_awg();
        break;
    case AWG_REFILL_MISSED:
        ++refill_misses;
        CLEAR_BIT(TIM6->CR1, TIM_CR1_CEN);
        state = AWG_FAULT;
        break;
    case AWG_REFILL_WAITING:
        break;
    }
}

awg_status_t awg_get_status(void)
{
    awg_channel_status_t channel = {0};
    (void)awg_get_channel_status(0U, &channel);
    return (awg_status_t){.state = channel.state,
                          .waveform = channel.config.waveform,
                          .requested_hz = (channel.config.frequency_millihz + 500U) / 1000U,
                          .actual_millihz = channel.actual_millihz,
                          .underruns = channel.underruns,
                          .dma_errors = channel.dma_errors};
}

bool awg_get_channel_status(uint8_t channel, awg_channel_status_t *out)
{
    if (channel >= AWG_CHANNEL_COUNT || out == NULL) {
        return false;
    }
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    *out = (awg_channel_status_t){.state = state,
                                  .channel = channel,
                                  .config = configs[channel],
                                  .actual_millihz = awg_actual_millihz(&generators[channel]),
                                  .underruns = underruns,
                                  .dma_errors = dma_errors,
                                  .refill_misses = refill_misses,
                                  .arbitrary_length = arbitrary_length[channel]};
    __set_PRIMASK(mask);
    return true;
}

void HAL_DAC_ConvHalfCpltCallbackCh1(DAC_HandleTypeDef *handle)
{
    if (handle == &hdac) {
        dma_complete(0U, 0U);
    }
}

void HAL_DAC_ConvCpltCallbackCh1(DAC_HandleTypeDef *handle)
{
    if (handle == &hdac) {
        dma_complete(0U, 1U);
    }
}

void HAL_DACEx_ConvHalfCpltCallbackCh2(DAC_HandleTypeDef *handle)
{
    if (handle == &hdac) {
        dma_complete(1U, 0U);
    }
}

void HAL_DACEx_ConvCpltCallbackCh2(DAC_HandleTypeDef *handle)
{
    if (handle == &hdac) {
        dma_complete(1U, 1U);
    }
}

void HAL_DAC_DMAUnderrunCallbackCh1(DAC_HandleTypeDef *handle)
{
    if (handle == &hdac) {
        CLEAR_BIT(TIM6->CR1, TIM_CR1_CEN);
        ++underruns;
        state = AWG_FAULT;
    }
}

void HAL_DACEx_DMAUnderrunCallbackCh2(DAC_HandleTypeDef *handle)
{
    if (handle == &hdac) {
        CLEAR_BIT(TIM6->CR1, TIM_CR1_CEN);
        ++underruns;
        state = AWG_FAULT;
    }
}

void HAL_DAC_ErrorCallbackCh1(DAC_HandleTypeDef *handle)
{
    if (handle == &hdac) {
        CLEAR_BIT(TIM6->CR1, TIM_CR1_CEN);
        ++dma_errors;
        state = AWG_FAULT;
    }
}

void HAL_DACEx_ErrorCallbackCh2(DAC_HandleTypeDef *handle)
{
    if (handle == &hdac) {
        CLEAR_BIT(TIM6->CR1, TIM_CR1_CEN);
        ++dma_errors;
        state = AWG_FAULT;
    }
}
