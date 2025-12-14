// BoardProfile.cpp
#include "BoardProfile.h"
#include <string.h> // strcmp

namespace bodaqs {

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

    // PLACEHOLDERS — set to your actual wiring / pins.
    .spi_host = 2,         // VSPI
    .sck = -1, .miso = -1, .mosi = -1,
    .cs = -1,
    .spi_hz = 20000000,

    // If you later use SDMMC (SD_MMC), flip type and set sdmmc_1bit accordingly.
    .sdmmc_1bit = true
  },

  .display = {
    .type = DisplayType::OLED_SSD1306,

    // PLACEHOLDERS — set to the Thing Plus S3 I2C pins you’re actually using.
    .sda = -1,
    .scl = -1,
    .i2c_hz = 400000,

    .addr_primary = 0x3C,
    .addr_alt     = 0x3D,
    .rst = -1
  },

  .fuel = {
    // Thing Plus S3 fuel gauge support (MAX17048)
    .type = FuelGaugeType::MAX17048,
    .i2c_addr = 0x36
  },

  .analog = {
    // PLACEHOLDERS — set to the analog input GPIOs on YOUR design.
    // These are numbered inputs (AIN0..).
    .pins  = { -1, -1, -1, -1, -1, -1, -1, -1 },
    .count = 0,

    .adc_max = 4095,
    .vref = 3.3f
  },

  .i2c = {
    // If you have I2C available, set present=true and pins above.
    .present = true,
    .sda = -1,
    .scl = -1,
    .hz  = 400000
  },

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
    .led_pin = -1,
    .led_active_high = true,

    .has_buzzer = false,
    .buzzer_pin = -1,
    .buzzer_active_high = true
  },

  .perf = {
    // Reasonable defaults; tweak per board / PSRAM availability / SD speed.
    .queue_depth = 128,
    .ring_buffer_bytes = 16384
  }
};

// -----------------------------------------------------------------------------
// Board: SparkFun ESP32 Thing Plus S3 (Clone A)
// (Use this as your “logger carrier / new PCB” profile and tweak freely.)
// -----------------------------------------------------------------------------
static const BoardProfile THING_PLUS_S3_CLONE_A = {
  .name = "SparkFun ESP32 Thing Plus S3 (Clone A)",

  .storage = {
    .type = StorageType::SPI_SdFat,
    .spi_host = 2,

    // Example placeholders — replace with your carrier's microSD SPI wiring.
    .sck = -1, .miso = -1, .mosi = -1,
    .cs  = -1,
    .spi_hz = 25000000,

    .sdmmc_1bit = true
  },

  .display = {
    // Maybe you omit the OLED on this variant:
    .type = DisplayType::None,

    // Still keep pins in case you later enable an OLED.
    .sda = -1, .scl = -1,
    .i2c_hz = 400000,

    .addr_primary = 0x3C,
    .addr_alt     = 0x3D,
    .rst = -1
  },

  .fuel = {
    // Keep MAX17048 unless your board lacks it.
    .type = FuelGaugeType::MAX17048,
    .i2c_addr = 0x36
  },

  .analog = {
    // Example: 4 analog inputs mapped to AIN0..AIN3
    // Replace with real GPIOs for your ADC inputs.
    .pins  = { -1, -1, -1, -1, -1, -1, -1, -1 },
    .count = 4,

    .adc_max = 4095,
    .vref = 3.3f
  },

  .i2c = {
    .present = true,
    .sda = -1,
    .scl = -1,
    .hz  = 400000
  },

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
    .queue_depth = 192,
    .ring_buffer_bytes = 32768
  }
};

// -----------------------------------------------------------------------------
// Public API
// -----------------------------------------------------------------------------
const BoardProfile& GetBoardProfile(BoardID id) {
  switch (id) {
    case BoardID::ThingPlusS3_Base:   return THING_PLUS_S3_BASE;
    case BoardID::ThingPlusS3_CloneA: return THING_PLUS_S3_CLONE_A;
    default:                          return THING_PLUS_S3_BASE;
  }
}

const BoardProfile& GetBoardProfileByName(const char* name) {
  if (!name) return THING_PLUS_S3_BASE;

  if (strcmp(name, THING_PLUS_S3_BASE.name) == 0)   return THING_PLUS_S3_BASE;
  if (strcmp(name, THING_PLUS_S3_CLONE_A.name) == 0) return THING_PLUS_S3_CLONE_A;

  return THING_PLUS_S3_BASE;
}

} // namespace bodaqs
