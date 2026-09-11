#include "awg.h"

#include "dac.h"
#include "tim.h"

/* DMA1 cannot access CCM; this table stays in main SRAM. */
_Alignas(4) static uint16_t samples[AWG_SAMPLE_COUNT];
static uint16_t first_sample;
static awg_timing_t timing;
static volatile awg_status_t status;

awg_result_t awg_configure(awg_waveform_t waveform, uint32_t frequency_hz)
{
    if (status.state == AWG_RUNNING) {
        return AWG_BUSY;
    }
    if (status.state == AWG_FAULT) {
        return AWG_HW_ERROR;
    }
    uint32_t timer_hz = HAL_RCC_GetPCLK1Freq();
    if ((RCC->CFGR & RCC_CFGR_PPRE1) != 0U) {
        timer_hz *= 2U;
    }
    awg_timing_t next;
    if (!awg_calculate_timing(timer_hz, frequency_hz, &next) || !awg_build_lut(waveform, samples)) {
        return AWG_INVALID;
    }
    /* The first trigger outputs DHR; DMA then loads the following sample.
       Rotate the DMA ring so startup and every wrap preserve the sequence. */
    first_sample = samples[0];
    for (uint32_t i = 0; i < AWG_SAMPLE_COUNT - 1U; ++i) {
        samples[i] = samples[i + 1U];
    }
    samples[AWG_SAMPLE_COUNT - 1U] = first_sample;
    timing = next;
    status.waveform = waveform;
    status.requested_hz = frequency_hz;
    status.actual_millihz = next.actual_millihz;
    status.state = AWG_READY;
    return AWG_OK;
}

awg_result_t awg_stop(void)
{
    if (status.state == AWG_UNCONFIGURED) {
        return AWG_OK;
    }
    (void)HAL_TIM_Base_Stop(&htim6);
    (void)HAL_DAC_Stop_DMA(&hdac, DAC_CHANNEL_1);
    /* HAL_DAC_Stop_DMA discards HAL_DMA_Abort's result; verify release before reuse. */
    if ((hdac.DMA_Handle1->Instance->CR & DMA_SxCR_EN) != 0U) {
        status.state = AWG_FAULT;
        return AWG_HW_ERROR;
    }
    __HAL_DAC_CLEAR_FLAG(&hdac, DAC_FLAG_DMAUDR1);
    status.state = AWG_READY;
    return AWG_OK;
}

awg_result_t awg_start(void)
{
    if (status.state == AWG_RUNNING) {
        return AWG_BUSY;
    }
    if (status.state != AWG_READY) {
        return status.state == AWG_FAULT ? AWG_HW_ERROR : AWG_INVALID;
    }
    (void)HAL_TIM_Base_Stop(&htim6);
    /* Loading PSC/ARR creates an update event. Gate DAC triggering until it is over. */
    CLEAR_BIT(hdac.Instance->CR, DAC_CR_TEN1);
    __HAL_TIM_SET_PRESCALER(&htim6, timing.prescaler);
    __HAL_TIM_SET_AUTORELOAD(&htim6, timing.period);
    __HAL_TIM_SET_COUNTER(&htim6, 0U);
    htim6.Instance->EGR = TIM_EGR_UG;
    __HAL_TIM_CLEAR_FLAG(&htim6, TIM_FLAG_UPDATE);
    SET_BIT(hdac.Instance->CR, DAC_CR_TEN1);
    __HAL_DAC_CLEAR_FLAG(&hdac, DAC_FLAG_DMAUDR1);
    hdac.ErrorCode = HAL_DAC_ERROR_NONE;
    if (HAL_DAC_SetValue(&hdac, DAC_CHANNEL_1, DAC_ALIGN_12B_R, first_sample) != HAL_OK ||
        HAL_DAC_Start_DMA(&hdac, DAC_CHANNEL_1, (const uint32_t *)samples, AWG_SAMPLE_COUNT,
                          DAC_ALIGN_12B_R) != HAL_OK) {
        (void)awg_stop();
        status.state = AWG_FAULT;
        return AWG_HW_ERROR;
    }
    /* A static circular LUT needs no refill callbacks. Keep DMA error IRQs enabled. */
    __HAL_DMA_DISABLE_IT(hdac.DMA_Handle1, DMA_IT_HT | DMA_IT_TC);
#ifdef DEBUG
    __HAL_DBGMCU_FREEZE_TIM6();
#endif
    /* Let the DAC settle before the first trigger. */
    HAL_Delay(1);
    __DMB();
    status.state = AWG_RUNNING;
    if (HAL_TIM_Base_Start(&htim6) != HAL_OK) {
        (void)awg_stop();
        status.state = AWG_FAULT;
        return AWG_HW_ERROR;
    }
    return AWG_OK;
}

awg_status_t awg_get_status(void)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    awg_status_t snapshot = status;
    __set_PRIMASK(mask);
    return snapshot;
}

void HAL_DAC_DMAUnderrunCallbackCh1(DAC_HandleTypeDef *handle)
{
    if (handle == &hdac) {
        CLEAR_BIT(TIM6->CR1, TIM_CR1_CEN);
        ++status.underruns;
        status.state = AWG_FAULT;
    }
}

void HAL_DAC_ErrorCallbackCh1(DAC_HandleTypeDef *handle)
{
    if (handle == &hdac) {
        CLEAR_BIT(TIM6->CR1, TIM_CR1_CEN);
        ++status.dma_errors;
        status.state = AWG_FAULT;
    }
}
