#include <Arduino.h>
#include "BoardProfile.h"
#include <string.h>

namespace board {

static SPIProfile MakeSPI(bool present, int8_t sck, int8_t miso, int8_t mosi,
                          const int8_t* cs_list, uint8_t cs_count,
                          uint32_t hz = 20000000) {
  SPIProfile p;
  p.present = present;
  p.sck = sck;
  p.miso = miso;
  p.mosi = mosi;
  p.hz_default = hz;
  p.cs_count = (cs_count > 8) ? 8 : cs_count;
  for (uint8_t i = 0; i < 8; ++i) p.cs_pins[i] = -1;
  for (uint8_t i = 0; i < p.cs_count; ++i) p.cs_pins[i] = cs_list[i];
  return p;
}

static const BoardProfile THING_PLUS_S3_BODAQS_4_D = {
  .name = "SparkFun ESP32 Thing Plus S3 on BODAQS 4 Proto D",

  .storage = {
    .type = StorageType::SDMMC,
    .sdmmc_1bit = true,
    .sdmmc_clk = 38,
    .sdmmc_cmd = 34,
    .sdmmc_d0  = 39,
  },

  .display = {
    .type = DisplayType::OLED_SSD1306,
    .addr_primary = 0x3C,
    .addr_alt     = 0x3D,
    .bus_index    = 0,
    .rst = -1
  },

  .buttons = {
    .btn = {
      { "nav_up",    true, 6, 1, true,  true },
      { "nav_down",  true, 7, 1, true,  true },
      { "nav_left",  true, 5, 1, true,  true },
      { "nav_right", true, 4, 1, true,  true },
      { "nav_enter", true, 21, 0, true,  true },
      { "mark",      true, 2, 0, false, true },
    },
    .count = 6,
  },

  .fuel = {
    .type = FuelGaugeType::MAX17048,
    .i2c_addr = 0x36,
    .bus_index = 0
  },

  .analog = {
    .pins  = { 15, 17, 18, 10, -1, -1, -1, -1 },
    .count = 4,
    .adc_max = 4095,
    .vref = 3.3f,
    .attenuation = AdcAttenuation::Db11
  },

  .i2c = {
    {
      .present = true,
      .sda = 8,
      .scl = 9,
      .hz  = 400000
    }
  },
  .i2c_count = 1,

  .spi = MakeSPI(
    true,
    -1,
    -1,
    -1,
    (const int8_t[]){ -1 },
    0,
    20000000
  ),

  .indicators = {
    .has_led = true,
    .led_pin = 1,
    .led_active_high = true,
    .has_buzzer = false,
    .buzzer_pin = -1,
    .buzzer_active_high = true
  },

  .perf = {
    .queue_depth = 256,
    .ring_buffer_bytes = 32768
  }
};

static const BoardProfile THING_PLUS_S3_BODAQS_4_D_UART_I2C1 = [] {
  BoardProfile p = THING_PLUS_S3_BODAQS_4_D;
  p.name = "SparkFun ESP32 Thing Plus S3 on BODAQS 4 Proto D (UART TX/RX as I2C1)";
  p.i2c[1] = {
    .present = true,
    .sda = TX,
    .scl = RX,
    .hz  = 400000
  };
  p.i2c_count = 2;
  return p;
}();

static const BoardProfile THING_PLUS_S3_BODAQS_4_F = [] {
  BoardProfile p = THING_PLUS_S3_BODAQS_4_D;
  p.name = "SparkFun ESP32 Thing Plus S3 on BODAQS 4F";

  p.buttons.btn[0] = ButtonHW{ "nav_up",    true, 6,  1, true, true };
  p.buttons.btn[1] = ButtonHW{ "nav_down",  true, 5,  1, true, true };
  p.buttons.btn[2] = ButtonHW{ "nav_left",  true, 7,  1, true, true };
  p.buttons.btn[3] = ButtonHW{ "nav_right", true, 21, 1, true, true };
  p.buttons.btn[4] = ButtonHW{ "nav_enter", true, 4,  0, true, true };

  p.i2c[0] = {
    .present = true,
    .sda = 8,
    .scl = 9,
    .hz  = 400000
  };
  p.i2c[1] = {
    .present = true,
    .sda = 14,
    .scl = 16,
    .hz  = 400000
  };
  p.i2c_count = 2;
  p.analog.attenuation = AdcAttenuation::Db6;
  p.analog.enable_pin = 42;
  p.analog.enable_active_high = true;
  p.analog.enable_default_on = true;

  return p;
}();

const BoardProfile& GetBoardProfile(BoardID id) {
  switch (id) {
    case BoardID::ThingPlusS3_BODAQS_4_D: return THING_PLUS_S3_BODAQS_4_D;
    case BoardID::ThingPlusS3_BODAQS_4_D_UartI2C1: return THING_PLUS_S3_BODAQS_4_D_UART_I2C1;
    case BoardID::ThingPlusS3_BODAQS_4_F: return THING_PLUS_S3_BODAQS_4_F;
    default: return THING_PLUS_S3_BODAQS_4_D;
  }
}

const BoardProfile& GetBoardProfileByName(const char* name) {
  if (!name) return THING_PLUS_S3_BODAQS_4_D;

  if (strcmp(name, THING_PLUS_S3_BODAQS_4_D.name) == 0) return THING_PLUS_S3_BODAQS_4_D;
  if (strcmp(name, THING_PLUS_S3_BODAQS_4_D_UART_I2C1.name) == 0) return THING_PLUS_S3_BODAQS_4_D_UART_I2C1;
  if (strcmp(name, THING_PLUS_S3_BODAQS_4_F.name) == 0) return THING_PLUS_S3_BODAQS_4_F;

  return THING_PLUS_S3_BODAQS_4_D;
}

} // namespace board
