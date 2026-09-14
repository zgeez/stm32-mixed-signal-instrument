#include "awg_waveform.h"

#include <math.h>
#include <stddef.h>

#define PHASE_SCALE 4294967296ULL

static int16_t sine_table[256];
static bool sine_table_ready;

static uint32_t scale_permille(uint16_t value)
{
    uint32_t scaled = (4096U * value + 500U) / 1000U;
    return scaled > AWG_DAC_MAX_CODE ? AWG_DAC_MAX_CODE : scaled;
}

static void prepare_sine_table(void)
{
    if (sine_table_ready) {
        return;
    }
    for (uint32_t i = 0; i < 256U; ++i) {
        sine_table[i] =
            (int16_t)lroundf(32767.0f * sinf(6.283185307179586f * (float)i / 256.0f));
    }
    sine_table_ready = true;
}

bool awg_config_valid(const awg_config_t *config, uint16_t arbitrary_length)
{
    /* No lower bound on the waveform: every enumerator is non-negative, so the type is
       unsigned and nothing below AWG_SINE can be represented in it. */
    if (config == NULL || config->waveform >= AWG_WAVEFORM_COUNT ||
        config->frequency_millihz < AWG_MIN_MILLIHZ ||
        config->frequency_millihz > AWG_MAX_MILLIHZ || config->amplitude_permille > 1000U ||
        config->offset_permille > 1000U || config->phase_decidegrees >= 3600U) {
        return false;
    }
    if (config->waveform == AWG_ARBITRARY &&
        (arbitrary_length < 2U || arbitrary_length > AWG_ARBITRARY_MAX_SAMPLES)) {
        return false;
    }
    uint32_t span = scale_permille(config->amplitude_permille);
    uint32_t center = scale_permille(config->offset_permille);
    uint32_t lower = (span + 1U) / 2U;
    return center >= lower && center + span - lower <= AWG_DAC_MAX_CODE;
}

bool awg_generator_init(awg_generator_t *generator, const awg_config_t *config,
                        const uint16_t *arbitrary, uint16_t arbitrary_length)
{
    if (generator == NULL || !awg_config_valid(config, arbitrary_length) ||
        (config->waveform == AWG_ARBITRARY && arbitrary == NULL)) {
        return false;
    }
    prepare_sine_table();
    generator->config = *config;
    generator->phase = (uint32_t)(((uint64_t)config->phase_decidegrees * PHASE_SCALE + 1800U) /
                                  3600U);
    generator->phase_increment =
        (uint32_t)(((uint64_t)config->frequency_millihz * PHASE_SCALE +
                    (uint64_t)AWG_SAMPLE_RATE_HZ * 500U) /
                   ((uint64_t)AWG_SAMPLE_RATE_HZ * 1000U));
    generator->span = (uint16_t)scale_permille(config->amplitude_permille);
    uint16_t center = (uint16_t)scale_permille(config->offset_permille);
    generator->low = (uint16_t)(center - (generator->span + 1U) / 2U);
    generator->arbitrary = arbitrary;
    generator->arbitrary_length = arbitrary_length;
    if (config->waveform == AWG_ARBITRARY) {
        /* Scale once while stopped; the DMA refill only needs phase lookup. */
        for (uint16_t i = 0U; i < arbitrary_length; ++i) {
            uint32_t normalized = ((uint32_t)arbitrary[i] * UINT16_MAX + 2047U) /
                                  AWG_DAC_MAX_CODE;
            generator->arbitrary_codes[i] = (uint16_t)(generator->low +
                (normalized * generator->span + 32767U) / UINT16_MAX);
        }
    }
    return generator->phase_increment != 0U;
}

uint32_t awg_actual_millihz(const awg_generator_t *generator)
{
    if (generator == NULL) {
        return 0U;
    }
    return (uint32_t)(((uint64_t)generator->phase_increment * AWG_SAMPLE_RATE_HZ * 1000U +
                       PHASE_SCALE / 2U) /
                      PHASE_SCALE);
}

static uint16_t normalized_sample(const awg_generator_t *generator)
{
    uint16_t phase = (uint16_t)(generator->phase >> 16U);
    switch (generator->config.waveform) {
    case AWG_SINE:
        return (uint16_t)((int32_t)sine_table[generator->phase >> 24U] + 32768);
    case AWG_TRIANGLE:
        return phase < 32768U ? (uint16_t)(phase * 2U)
                              : (uint16_t)((65535U - phase) * 2U);
    case AWG_SQUARE:
        return (generator->phase & 0x80000000U) == 0U ? UINT16_MAX : 0U;
    case AWG_SAWTOOTH:
        return phase;
    case AWG_DC:
        return 32768U;
    case AWG_ARBITRARY: {
        uint16_t index =
            (uint16_t)(((uint64_t)generator->phase * generator->arbitrary_length) >> 32U);
        return (uint16_t)(((uint32_t)generator->arbitrary[index] * UINT16_MAX + 2047U) /
                          AWG_DAC_MAX_CODE);
    }
    default:
        return 0U;
    }
}

uint16_t awg_generator_next(awg_generator_t *generator)
{
    uint32_t code = generator->low +
                    ((uint32_t)normalized_sample(generator) * generator->span + 32767U) /
                        UINT16_MAX;
    generator->phase += generator->phase_increment;
    return (uint16_t)code;
}

void awg_generator_render(awg_generator_t *generator, uint16_t *samples, uint16_t count)
{
    if (generator == NULL || samples == NULL) {
        return;
    }
    if (generator->config.waveform == AWG_ARBITRARY) {
        uint32_t phase = generator->phase;
        for (uint16_t i = 0U; i < count; ++i) {
            uint16_t index = (uint16_t)(((uint64_t)phase * generator->arbitrary_length) >> 32U);
            samples[i] = generator->arbitrary_codes[index];
            phase += generator->phase_increment;
        }
        generator->phase = phase;
        return;
    }
    for (uint16_t i = 0; i < count; ++i) {
        samples[i] = awg_generator_next(generator);
    }
}
