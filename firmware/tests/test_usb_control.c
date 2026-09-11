#include "usb_control.h"
#include "commands.h"
#include "usbd_cdc_if.h"

#include <stdio.h>
#include <string.h>

#define CHECK(x) \
    do { \
        if (!(x)) { \
            fprintf(stderr, "Failed line %d: %s\n", __LINE__, #x); \
            return 1; \
        } \
    } while (0)

static USBD_CDC_HandleTypeDef cdc;
USBD_HandleTypeDef hUsbDeviceFS = {&cdc, USBD_STATE_CONFIGURED};
static uint32_t tick, executed, transmitted, rearmed;
static uint8_t *active_tx;
static uint16_t active_size;
static bool force_busy, reset_during_command;

uint32_t HAL_GetTick(void)
{
    return tick;
}
uint8_t USBD_CDC_ReceivePacket(USBD_HandleTypeDef *device)
{
    (void)device;
    ++rearmed;
    return USBD_OK;
}
uint8_t CDC_Transmit_FS(uint8_t *data, uint16_t size)
{
    if (force_busy) {
        return USBD_BUSY;
    }
    ++transmitted;
    active_tx = data;
    active_size = size;
    cdc.TxState = 1;
    return USBD_OK;
}
void command_execute(const protocol_frame_t *request, protocol_frame_t *reply)
{
    ++executed;
    *reply = *request;
    reply->command |= 0x80U;
    reply->length = 1U;
    reply->payload[0] = 0U;
    if (reset_during_command) {
        usb_control_session(false);
    }
}
static void poll_many(void)
{
    for (unsigned i = 0; i < 100; ++i) {
        usb_control_poll();
    }
}

int main(void)
{
    protocol_frame_t request = {.version = 1, .command = CMD_HELLO, .sequence = 1};
    uint8_t wire[PROTOCOL_FRAME_MAX], packet[64], saved[PROTOCOL_FRAME_MAX];
    uint8_t size = protocol_encode(&request, wire);
    memcpy(packet, wire, size);
    memcpy(packet + size, wire, size);
    usb_control_session(true);
    usb_control_receive(packet, 2U * size);
    poll_many();
    CHECK(executed == 1 && transmitted == 1 && rearmed == 0);
    memcpy(saved, active_tx, active_size);
    poll_many();
    CHECK(executed == 1 && memcmp(saved, active_tx, active_size) == 0);
    cdc.TxState = 0;
    force_busy = true;
    poll_many();
    CHECK(executed == 2 && transmitted == 1 && rearmed == 0);
    force_busy = false;
    poll_many();
    CHECK(transmitted == 2);
    cdc.TxState = 0;
    poll_many();
    CHECK(rearmed == 1);

    usb_control_receive(wire, size - 1U);
    poll_many();
    tick += 501;
    usb_control_receive(wire + size - 1U, 1U);
    poll_many();
    CHECK(executed == 2);
    usb_control_receive(wire, size - 1U);
    poll_many();
    usb_control_session(false);
    usb_control_session(true);
    usb_control_receive(wire, size);
    poll_many();
    CHECK(executed == 3 && transmitted == 3);
    cdc.TxState = 0;
    poll_many();
    reset_during_command = true;
    usb_control_receive(wire, size);
    poll_many();
    CHECK(executed == 4 && transmitted == 3);
    puts("USB backpressure, TX lifetime, partial timeout and session reset passed.");
    return 0;
}
