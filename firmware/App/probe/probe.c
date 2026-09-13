#include "probe.h"

#include "tim.h"

static probe_status_t status;

probe_result_t probe_configure(uint32_t frequency_hz, uint16_t duty_permille)
{
    probe_divider_t divider;
    if (!probe_divider(frequency_hz, duty_permille, &divider)) {
        return PROBE_INVALID;
    }
    (void)HAL_TIM_PWM_Stop(&htim3, TIM_CHANNEL_1);
    __HAL_TIM_SET_PRESCALER(&htim3, divider.prescaler);
    __HAL_TIM_SET_AUTORELOAD(&htim3, divider.reload);
    __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_1, divider.compare);
    __HAL_TIM_SET_COUNTER(&htim3, 0U);
    /* The prescaler is only latched on an update event. */
    htim3.Instance->EGR = TIM_EGR_UG;
    if (HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_1) != HAL_OK) {
        return PROBE_HW_ERROR;
    }
    status = (probe_status_t){.enabled = true,
                              .requested_hz = frequency_hz,
                              .actual_hz = divider.actual_hz,
                              .duty_permille = duty_permille,
                              .prescaler = divider.prescaler,
                              .reload = divider.reload};
    return PROBE_OK;
}

probe_result_t probe_disable(void)
{
    (void)HAL_TIM_PWM_Stop(&htim3, TIM_CHANNEL_1);
    status.enabled = false;
    return PROBE_OK;
}

probe_status_t probe_get_status(void)
{
    return status;
}
