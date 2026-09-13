#ifndef OWNERSHIP_H
#define OWNERSHIP_H

#include <stdbool.h>
#include <stdint.h>

/* The scope and the logic analyzer use different DMA streams but both master DMA2 and
 * compete for the same bus. Running them together would perturb sample timing in a way
 * neither can detect, so exactly one may hold the acquisition hardware at a time and the
 * loser is told so rather than silently interfering.
 *
 * These functions carry no locking of their own. Callers span the control and
 * acquisition tasks, so every call must be made inside a critical section. */

typedef enum {
    ACQUISITION_NONE,
    ACQUISITION_SCOPE,
    ACQUISITION_LOGIC
} acquisition_owner_t;

typedef struct {
    acquisition_owner_t owner;
    uint32_t conflicts;
} ownership_t;

/* Re-arming the current owner succeeds; a different claimant is rejected and counted. */
bool ownership_claim(ownership_t *state, acquisition_owner_t claimant);
bool ownership_release(ownership_t *state, acquisition_owner_t holder);
acquisition_owner_t ownership_current(const ownership_t *state);
uint32_t ownership_conflicts(const ownership_t *state);

/* The single instrument-wide arbiter shared by the scope and the analyzer. */
extern ownership_t acquisition_ownership;

#endif
