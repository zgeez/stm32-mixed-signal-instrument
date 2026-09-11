#ifndef COMMANDS_H
#define COMMANDS_H

#include "protocol.h"

void command_execute(const protocol_frame_t *request, protocol_frame_t *reply);

#endif
