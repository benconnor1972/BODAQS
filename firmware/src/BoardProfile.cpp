// BoardProfile.cpp
#include "BoardProfile.h"
#include <string.h> // strcmp

namespace board {

// Helper for defining CS list
static SPIProfile MakeSPI(bool present, int8_t sck, int8_t miso, int8_t mosi,
                          const int8_t* cs_list, uint8_t cs_count,
                          uint32_t hz = 20000000) {
  SPIProfile p;
  p.present = present;
  p.sck = sck; p.miso = miso; p.mosi = mosi;
  p.hz_default = hz;
  p.cs_count = (cs_count > 8) ? 8 : cs_count;
  for (uint8_t i = 0; i < 8; ++i) p.cs_pins[i] = -1;
  for (uint8_t i = 0; i < p.cs_count; ++i) p.cs_pins[i] = cs_list[i];
  return p;
}

// -----------------------------------------------------------------------------
// Board: SparkFun ESP32 Thing Plus S3 on BODAQS 4 Prototype D
// -----------------------------------------------------------------------------
static const BoardProfile THING_PLUS_S3_BODAQS_4_D = {
  .name = "SparkFun ESP32 Thing Plus S3 on BODAQS 4 Proto D",

  .storage = {
    // Choose one. If you’re using microSD over SPI breakout / socket on carrier:
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
      // button0.id=nav_up,   pin=6, mode=poll
      { "nav_up",    true, 6, 1, true,  true },

      // button1.id=nav_down, pin=7, mode=poll
      { "nav_down",  true, 7, 1, true,  true },

      // button2.id=nav_left, pin=5, mode=poll
      { "nav_left",  true, 5, 1, true,  true },

      // button3.id=nav_right, pin=4, mode=poll
      { "nav_right", true, 4, 1, true,  true },

      // button4.id=nav_enter, pin=21, mode=interrupt
      { "nav_enter", true, 21, 0, true,  true },

      // button5.id=mark, pin=2, mode=interrupt
      { "mark",      true, 2, 0, false, true },
    },
    .count = 6,
  },

  .fuel = {
    // Thing Plus S3 fuel gauge support (MAX17048)
    .type = FuelGaugeType::MAX17048,
    .i2c_addr = 0x36,
    .bus_index = 0
  },

  .analog = {
    // PLACEHOLDERS — set to the analog input GPIOs on YOUR design.
    // These are numbered inputs (AIN0..).
    .pins  = { 15, 17, 18, 10, -1, -1, -1, -1 },
    .count = 4,

    .adc_max = 4095,
    .vref = 3.3f
  },

  .i2c = {
    {
      // If you have I2C available, set present=true and pins above.
      .present = true,
      .sda = 8,
      .scl = 9,
      .hz  = 400000
    }
  },
  .i2c_count = 1,

  .spi = MakeSPI(
    /*present*/ true,
    /*sck*/  -1,
    /*miso*/ -1,
    /*mosi*/ -1,
    /*cs_list*/ (const int8_t[]){ -1 }, // placeholder list
    /*cs_count*/ 0,
    /*hz*/ 20000000
  ),

  .indicators = {
    // PLACEHOLDERS
    .has_led = true,
    .led_pin = 1,
    .led_active_high = true,

    .has_buzzer = false,
    .buzzer_pin = -1,
    .buzzer_active_high = true
  },

  .perf = {
    // Reasonable defaults; tweak per board / PSRAM availability / SD speed.
    .queue_depth = 256,
    .ring_buffer_bytes = 32768
  }
};

// -----------------------------------------------------------------------------
// Board: SparkFun ESP32 Thing Plus 
// -----------------------------------------------------------------------------
static const BoardProfile THING_PLUS_A = {
  .name = "SparkFun ESP32 Thing Plus (Stripboard proto A)",

  .storage = {
    .type = StorageType::SPI_SdFat,
    .spi_host = 2,

    // Example placeholders — replace with your carrier's microSD SPI wiring.
    .sck = 18, .miso = 19, .mosi = -23,
    .cs  = 5,
    .spi_hz = 25000000,

    .sdmmc_1bit = true
  },

  .display = {
    // Maybe you omit the OLED on this variant:
    .type = DisplayType::None,

    .addr_primary = 0x3C,
    .addr_alt     = 0x3D,
    .bus_index    = 0,
    .rst = -1
  },

    .buttons = {
    .btn = {
      // button0.id=nav_up,   pin=32, mode=poll
      { "nav_up",    true, 32, 1, true, true },

      // button1.id=nav_down, pin=15, mode=poll
      { "nav_down",  true, 15, 1, true, true },

      // button2.id=nav_left, pin=12, mode=poll
      { "nav_left",  true, 12, 1, true, true },

      // button3.id=nav_right, pin=33, mode=poll
      { "nav_right", true, 33, 1, true, true },

      // button4.id=nav_enter, pin=13, mode=interrupt
      { "nav_enter", true, 13, 0, true, true },

      // button5.id=mark, pin=14, mode=interrupt
      { "mark",      true, 14, 0, true, true },
    },
    .count = 6,
  },

  .fuel = {
    // Keep MAX17048 unless your board lacks it.
    .type = FuelGaugeType::MAX17048,
    .i2c_addr = 0x36,
    .bus_index = 0
  },

  .analog = {
    .pins  = { 34, 39, -1, -1, -1, -1, -1, -1 },
    .count = 2,

    .adc_max = 4095,
    .vref = 3.3f
  },

  .i2c = {
    {
      .present = true,
      .sda = 21,
      .scl = 22,
      .hz  = 400000
    }
  },
  .i2c_count = 1,

  .spi = MakeSPI(
    /*present*/ true,
    /*sck*/  -1,
    /*miso*/ -1,
    /*mosi*/ -1,
    /*cs_list*/ (const int8_t[]){ -1, -1, -1 }, // e.g. SD CS + IMU CS + ADC CS
    /*cs_count*/ 0,
    /*hz*/ 25000000
  ),

  .indicators = {
    .has_led = true,
    .led_pin = -1,
    .led_active_high = true,

    .has_buzzer = true,
    .buzzer_pin = -1,
    .buzzer_active_high = true
  },

  .perf = {
    // Slightly larger for “better” storage / PSRAM builds
    .queue_depth = 256,
    .ring_buffer_bytes = 65536
  }
};

// -----------------------------------------------------------------------------
// Public API
// -----------------------------------------------------------------------------
const BoardProfile& GetBoardProfile(BoardID id) {
  switch (id) {
    case BoardID::ThingPlusS3_BODAQS_4_D:   return THING_PLUS_S3_BODAQS_4_D;
    case BoardID::ThingPlus_A: return THING_PLUS_A;
    default:                          return THING_PLUS_S3_BODAQS_4_D;
  }
}

const BoardProfile& GetBoardProfileByName(const char* name) {
  if (!name) return THING_PLUS_S3_BODAQS_4_D;

  if (strcmp(name, THING_PLUS_S3_BODAQS_4_D.name) == 0)   return THING_PLUS_S3_BODAQS_4_D;
  if (strcmp(name, THING_PLUS_A.name) == 0) return THING_PLUS_A;

  return THING_PLUS_S3_BODAQS_4_D;
}

} // namespace board
