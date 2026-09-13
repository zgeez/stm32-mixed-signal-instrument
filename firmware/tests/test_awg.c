#include "awg_waveform.h"

#include <stdio.h>
#include <stdlib.h>

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            fprintf(stderr, "Check failed at line %d: %s\n", __LINE__, #condition); \
            return 1; \
        } \
    } while (0)

static awg_config_t config(awg_waveform_t waveform)
{
    return (awg_config_t){.waveform = waveform,
                          .frequency_millihz = 1000000U,
                          .amplitude_permille = 750U,
                          .offset_permille = 500U,
                          .phase_decidegrees = 0U};
}

static int test_frequency(void)
{
    awg_generator_t generator;
    awg_config_t settings = config(AWG_SINE);
    for (uint32_t millihz = AWG_MIN_MILLIHZ; millihz <= AWG_MAX_MILLIHZ;
         millihz += 997U) {
        settings.frequency_millihz = millihz;
        CHECK(awg_generator_init(&generator, &settings, NULL, 0U));
        CHECK(abs((int)awg_actual_millihz(&generator) - (int)millihz) <= 1);
    }
    settings.frequency_millihz = AWG_MAX_MILLIHZ;
    CHECK(awg_generator_init(&generator, &settings, NULL, 0U));
    CHECK(generator.phase_increment == 214748365U);
    return 0;
}

static int test_shapes(void)
{
    awg_generator_t generator;
    uint16_t samples[400];
    for (int shape = AWG_SINE; shape <= AWG_DC; ++shape) {
        awg_config_t settings = config((awg_waveform_t)shape);
        CHECK(awg_generator_init(&generator, &settings, NULL, 0U));
        awg_generator_render(&generator, samples, 400U);
        for (unsigned i = 0U; i < 400U; ++i) {
            CHECK(samples[i] >= 512U && samples[i] <= 3584U);
        }
        generator.phase = 0U;
        uint16_t start = awg_generator_next(&generator);
        generator.phase = 0x40000000U;
        uint16_t quarter = awg_generator_next(&generator);
        generator.phase = 0x80000000U;
        uint16_t half = awg_generator_next(&generator);
        generator.phase = 0xc0000000U;
        uint16_t three_quarters = awg_generator_next(&generator);
        if (shape == AWG_SINE) {
            CHECK(start == 2048U);
            CHECK(quarter >= 3583U);
            CHECK(half >= 2047U && half <= 2049U);
            CHECK(three_quarters <= 513U);
        } else if (shape == AWG_TRIANGLE) {
            CHECK(start == 512U);
            CHECK(half >= 3583U);
        } else if (shape == AWG_SQUARE) {
            CHECK(start == 3584U && quarter == 3584U);
            CHECK(half == 512U && three_quarters == 512U);
        } else if (shape == AWG_SAWTOOTH) {
            CHECK(start == 512U);
            CHECK(three_quarters > 2800U);
        } else {
            CHECK(start == 2048U && three_quarters == 2048U);
        }
    }
    return 0;
}

static int test_scaling_and_phase(void)
{
    awg_generator_t generator;
    awg_config_t settings = config(AWG_SQUARE);
    settings.amplitude_permille = 500U;
    settings.offset_permille = 250U;
    settings.phase_decidegrees = 1800U;
    CHECK(awg_generator_init(&generator, &settings, NULL, 0U));
    CHECK(awg_generator_next(&generator) == 0U);
    settings.phase_decidegrees = 0U;
    CHECK(awg_generator_init(&generator, &settings, NULL, 0U));
    CHECK(awg_generator_next(&generator) == 2048U);

    settings.amplitude_permille = 501U;
    CHECK(!awg_config_valid(&settings, 0U));
    settings.amplitude_permille = 1000U;
    settings.offset_permille = 500U;
    CHECK(awg_config_valid(&settings, 0U));
    settings.offset_permille = 499U;
    CHECK(!awg_config_valid(&settings, 0U));
    settings.offset_permille = 500U;
    settings.phase_decidegrees = 3600U;
    CHECK(!awg_config_valid(&settings, 0U));
    settings.phase_decidegrees = 0U;
    settings.waveform = (awg_waveform_t)-1;
    CHECK(!awg_config_valid(&settings, 0U));
    return 0;
}

static int test_arbitrary(void)
{
    const uint16_t table[] = {0U, 4095U, 2048U, 1024U};
    awg_config_t settings = config(AWG_ARBITRARY);
    settings.frequency_millihz = 250000U;
    settings.amplitude_permille = 1000U;
    awg_generator_t generator;
    CHECK(awg_generator_init(&generator, &settings, table, 4U));
    uint16_t expected[] = {0U, 4095U, 2048U, 1024U};
    for (unsigned i = 0U; i < 4U; ++i) {
        generator.phase = i * 0x40000000U;
        CHECK(abs((int)awg_generator_next(&generator) - (int)expected[i]) <= 1);
    }
    CHECK(!awg_generator_init(&generator, &settings, NULL, 4U));
    CHECK(!awg_generator_init(&generator, &settings, table, 1U));
    return 0;
}

static int test_arbitrary_refill(void)
{
    uint16_t table[256], samples[AWG_DMA_HALF_SAMPLES];
    for (unsigned i = 0U; i < 256U; ++i) {
        table[i] = (uint16_t)((i * 997U) & 4095U);
    }
    const uint16_t lengths[] = {2U, 3U, 17U, 255U, 256U};
    for (unsigned n = 0U; n < sizeof(lengths) / sizeof(lengths[0]); ++n) {
        awg_config_t settings = config(AWG_ARBITRARY);
        settings.frequency_millihz = 19999125U;
        settings.phase_decidegrees = 3599U;
        settings.amplitude_permille = (uint16_t)(n * 250U);
        awg_generator_t rendered, reference;
        CHECK(awg_generator_init(&rendered, &settings, table, lengths[n]));
        CHECK(awg_generator_init(&reference, &settings, table, lengths[n]));
        for (unsigned block = 0U; block < 8U; ++block) {
            awg_generator_render(&rendered, samples, AWG_DMA_HALF_SAMPLES);
            for (unsigned i = 0U; i < AWG_DMA_HALF_SAMPLES; ++i) {
                CHECK(samples[i] == awg_generator_next(&reference));
            }
            CHECK(rendered.phase == reference.phase);
        }
    }
    return 0;
}

int main(void)
{
    CHECK(test_frequency() == 0);
    CHECK(test_shapes() == 0);
    CHECK(test_scaling_and_phase() == 0);
    CHECK(test_arbitrary() == 0);
    CHECK(test_arbitrary_refill() == 0);
    puts("DDS frequency, waveforms, scaling, phase and arbitrary playback passed.");
    return 0;
}
