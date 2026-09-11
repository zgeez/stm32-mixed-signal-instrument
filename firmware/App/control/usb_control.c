#include "usb_control.h"

#include "commands.h"
#include "usbd_cdc_if.h"
#include <string.h>

extern USBD_HandleTypeDef hUsbDeviceFS;

static uint8_t rx[64], tx[PROTOCOL_FRAME_MAX];
static volatile uint32_t epoch;
static volatile bool connected, received;
static volatile uint32_t rx_size;
static uint32_t rx_at;

void usb_control_session(bool active)
{
    connected = active;
    received = false;
    rx_size = 0U;
    ++epoch;
}

void usb_control_receive(const uint8_t *data, uint32_t length)
{
    if (length <= sizeof rx && !received) {
        memcpy(rx, data, length);
        rx_size = length;
        __DMB();
        received = true;
    }
}

void usb_control_poll(void)
{
    static protocol_parser_t parser;
    static uint32_t seen_epoch, last_byte;
    static uint8_t pending;
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    if (seen_epoch != epoch) {
        seen_epoch = epoch;
        parser = (protocol_parser_t){0};
        pending = 0U;
        rx_at = 0U;
    }
    USBD_CDC_HandleTypeDef *cdc = hUsbDeviceFS.pClassData;
    if (!connected || hUsbDeviceFS.dev_state != USBD_STATE_CONFIGURED || cdc == NULL) {
        __set_PRIMASK(mask);
        return;
    }
    /* Keep tx unchanged until the middleware releases its pointer. */
    if (cdc->TxState != 0U) {
        __set_PRIMASK(mask);
        return;
    }
    if (pending != 0U) {
        if (CDC_Transmit_FS(tx, pending) == USBD_OK) {
            pending = 0U;
        }
        __set_PRIMASK(mask);
        return;
    }
    uint32_t now = HAL_GetTick();
    if ((uint32_t)(now - last_byte) > 500U) {
        parser = (protocol_parser_t){0};
    }
    if (!received) {
        __set_PRIMASK(mask);
        return;
    }
    if (rx_at == rx_size) {
        rx_at = 0U;
        received = false;
        USBD_CDC_ReceivePacket(&hUsbDeviceFS);
        __set_PRIMASK(mask);
        return;
    }
    uint8_t byte = rx[rx_at++];
    uint32_t request_epoch = epoch;
    __set_PRIMASK(mask);
    last_byte = now;
    protocol_frame_t request, reply;
    if (protocol_feed(&parser, byte, &request)) {
        command_execute(&request, &reply);
        mask = __get_PRIMASK();
        __disable_irq();
        if (request_epoch == epoch) {
            pending = protocol_encode(&reply, tx);
        }
        __set_PRIMASK(mask);
    }
}
