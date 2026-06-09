#ifndef Pins_Arduino_h
#define Pins_Arduino_h

#include <stdint.h>

#define USB_VID          0x303A
#define USB_PID          0x1001
#define USB_MANUFACTURER "BODAQS"
#define USB_PRODUCT      "BODAQS V1RC3"
#define USB_SERIAL       ""

static const uint8_t TX = 43;
static const uint8_t RX = 44;
#define TX1 TX
#define RX1 RX

static const uint8_t SDA = 1;
static const uint8_t SCL = 2;

#define WIRE1_PIN_DEFINED 1
static const uint8_t SDA1 = 4;
static const uint8_t SCL1 = 5;

static const uint8_t SS   = 47;
static const uint8_t MOSI = 38;
static const uint8_t MISO = 39;
static const uint8_t SCK  = 37;

static const uint8_t CS0 = 47;
static const uint8_t CS1 = 21;
static const uint8_t CS2 = 40;

static const uint8_t SDIO_DET = 6;
static const uint8_t SDIO2    = 7;
static const uint8_t SDIO3    = 8;
static const uint8_t SDIO_CMD = 9;
static const uint8_t SDIO_CLK = 10;
static const uint8_t SDIO0    = 11;
static const uint8_t SDIO1    = 12;

static const uint8_t BTN_DOWN  = 13;
static const uint8_t BTN_LEFT  = 14;
static const uint8_t BTN_RIGHT = 15;
static const uint8_t BTN_ENTER = 16;
static const uint8_t BTN_UP    = 17;
static const uint8_t BTN_MARK  = 42;

static const uint8_t DRDY0 = 36;
static const uint8_t DRDY1 = 18;

static const uint8_t ANALOG_ENABLE = 35;
static const uint8_t MAX17048_ALRT = 33;
static const uint8_t TPS2553_A_FLT = 34;

#endif /* Pins_Arduino_h */
