#include "awg_waveform.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            fprintf(stderr, "Check failed at line %d: %s\n", __LINE__, #condition); \
            return 1; \
        } \
    } while (0)

int main(void)
{
    uint16_t samples[AWG_SAMPLE_COUNT];
    for (int shape = AWG_SINE; shape <= AWG_SQUARE; ++shape) {
        CHECK(awg_build_lut((awg_waveform_t)shape, samples));
        unsigned high_count = 0U;
        unsigned transitions = 0U;
        for (unsigned i = 0; i < AWG_SAMPLE_COUNT; ++i) {
            CHECK(samples[i] >= AWG_LOW_CODE && samples[i] <= AWG_HIGH_CODE);
            if (shape == AWG_SQUARE) {
                CHECK(samples[i] == AWG_LOW_CODE || samples[i] == AWG_HIGH_CODE);
                high_count += samples[i] == AWG_HIGH_CODE;
                transitions += samples[i] != samples[(i + 1U) % AWG_SAMPLE_COUNT];
            } else {
                int sum = samples[i] + samples[(i + AWG_SAMPLE_COUNT / 2U) % AWG_SAMPLE_COUNT];
                CHECK(sum >= 4095 && sum <= 4097);
                int delta = (int)samples[i] - samples[(i + 1U) % AWG_SAMPLE_COUNT];
                CHECK(delta >= -97 && delta <= 97);
            }
        }
        if (shape == AWG_SINE) {
            CHECK(samples[0] == 2048 && samples[25] == AWG_HIGH_CODE);
            CHECK(samples[50] == 2048 && samples[75] == AWG_LOW_CODE);
        } else if (shape == AWG_TRIANGLE) {
            CHECK(samples[0] == AWG_LOW_CODE && samples[50] == AWG_HIGH_CODE);
            for (unsigned i = 1; i <= 50; ++i) {
                CHECK(samples[i] > samples[i - 1]);
            }
            for (unsigned i = 51; i < 100; ++i) {
                CHECK(samples[i] < samples[i - 1]);
            }
        } else {
            CHECK(high_count == 50 && transitions == 2);
        }
    }
    uint16_t saved[AWG_SAMPLE_COUNT];
    memcpy(saved, samples, sizeof samples);
    CHECK(!awg_build_lut((awg_waveform_t)-1, samples));
    CHECK(!awg_build_lut((awg_waveform_t)3, samples));
    CHECK(memcmp(saved, samples, sizeof samples) == 0);
    CHECK(!awg_build_lut(AWG_SINE, NULL));

    awg_timing_t timing;
    for (uint32_t hz = AWG_MIN_HZ; hz <= AWG_MAX_HZ; ++hz) {
        CHECK(awg_calculate_timing(84000000, hz, &timing));
        double actual =
            84000000.0 / ((timing.prescaler + 1.0) * (timing.period + 1.0) * AWG_SAMPLE_COUNT);
        CHECK(fabs(actual - hz) / hz < 0.001);
        CHECK(fabs(timing.actual_millihz - actual * 1000.0) <= 0.501);
    }
    CHECK(timing.prescaler == 0 && timing.period == 839);
    CHECK(timing.actual_millihz == 1000000);
    CHECK(!awg_calculate_timing(84000000, 0, &timing));
    CHECK(!awg_calculate_timing(84000000, 1001, &timing));
    CHECK(!awg_calculate_timing(84000000, UINT32_MAX, &timing));
    CHECK(!awg_calculate_timing(99, 1, &timing));
    CHECK(!awg_calculate_timing(84000000, 1, NULL));
    CHECK(awg_calculate_timing(UINT32_MAX, 1, &timing));
    puts("Waveforms, invalid inputs and 1..1000 Hz timing sweep passed.");
    return 0;
}
