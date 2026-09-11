#ifndef USB_CONTROL_H
#define USB_CONTROL_H

#include <stdbool.h>
#include <stdint.h>

void usb_control_poll(void);
/* Called by CDC callbacks. RX remains unarmed until foreground consumes the packet. */
void usb_control_session(bool connected);
void usb_control_receive(const uint8_t *data, uint32_t length);

#endif
