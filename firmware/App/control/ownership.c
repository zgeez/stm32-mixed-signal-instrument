#include "ownership.h"
#include <stddef.h>

ownership_t acquisition_ownership;

static bool valid(acquisition_owner_t who)
{
    return who == ACQUISITION_SCOPE || who == ACQUISITION_LOGIC;
}

bool ownership_claim(ownership_t *state, acquisition_owner_t claimant)
{
    if (state == NULL || !valid(claimant)) {
        return false;
    }
    if (state->owner != ACQUISITION_NONE && state->owner != claimant) {
        ++state->conflicts;
        return false;
    }
    state->owner = claimant;
    return true;
}

bool ownership_release(ownership_t *state, acquisition_owner_t holder)
{
    if (state == NULL || !valid(holder) || state->owner != holder) {
        return false;
    }
    state->owner = ACQUISITION_NONE;
    return true;
}

acquisition_owner_t ownership_current(const ownership_t *state)
{
    return state == NULL ? ACQUISITION_NONE : state->owner;
}

uint32_t ownership_conflicts(const ownership_t *state)
{
    return state == NULL ? 0U : state->conflicts;
}
