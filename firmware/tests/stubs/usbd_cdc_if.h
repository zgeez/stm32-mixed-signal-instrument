#ifndef TEST_USBD_CDC_IF_H
#define TEST_USBD_CDC_IF_H

#include <stdint.h>

#define USBD_OK 0U
#define USBD_BUSY 1U
#define USBD_STATE_CONFIGURED 3U
typedef struct {
    uint32_t TxState;
} USBD_CDC_HandleTypeDef;
typedef struct {
    void *pClassData;
    uint8_t dev_state;
} USBD_HandleTypeDef;

static inline void __DMB(void)
{
}
static inline uint32_t __get_PRIMASK(void)
{
    return 0;
}
static inline void __disable_irq(void)
{
}
static inline void __set_PRIMASK(uint32_t mask)
{
    (void)mask;
}
uint32_t HAL_GetTick(void);
uint8_t CDC_Transmit_FS(uint8_t *data, uint16_t size);
uint8_t USBD_CDC_ReceivePacket(USBD_HandleTypeDef *device);

#endif
