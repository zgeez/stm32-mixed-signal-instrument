#ifndef AWG_WAVEFORM_H
#define AWG_WAVEFORM_H

#include <stdbool.h>
#include <stdint.h>

#define AWG_CHANNEL_COUNT 2U
#define AWG_SAMPLE_RATE_HZ 400000U
#define AWG_DMA_SAMPLE_COUNT 1024U
#define AWG_DMA_HALF_SAMPLES (AWG_DMA_SAMPLE_COUNT / 2U)
#define AWG_ARBITRARY_MAX_SAMPLES 256U
#define AWG_MIN_MILLIHZ 1000U
#define AWG_MAX_MILLIHZ 20000000U
#define AWG_DAC_MAX_CODE 4095U

typedef enum {
    AWG_SINE,
    AWG_TRIANGLE,
    AWG_SQUARE,
    AWG_SAWTOOTH,
    AWG_DC,
    AWG_ARBITRARY,
    AWG_WAVEFORM_COUNT
} awg_waveform_t;

typedef struct {
    awg_waveform_t waveform;
    uint32_t frequency_millihz;
    uint16_t amplitude_permille;
    uint16_t offset_permille;
    uint16_t phase_decidegrees;
} awg_config_t;

typedef struct {
    awg_config_t config;
    uint32_t phase;
    uint32_t phase_increment;
    uint16_t span;
    uint16_t low;
    const uint16_t *arbitrary;
    uint16_t arbitrary_length;
    uint16_t arbitrary_codes[AWG_ARBITRARY_MAX_SAMPLES];
} awg_generator_t;

bool awg_config_valid(const awg_config_t *config, uint16_t arbitrary_length);
bool awg_generator_init(awg_generator_t *generator, const awg_config_t *config,
                        const uint16_t *arbitrary, uint16_t arbitrary_length);
uint32_t awg_actual_millihz(const awg_generator_t *generator);
uint16_t awg_generator_next(awg_generator_t *generator);
void awg_generator_render(awg_generator_t *generator, uint16_t *samples, uint16_t count);

#endif
