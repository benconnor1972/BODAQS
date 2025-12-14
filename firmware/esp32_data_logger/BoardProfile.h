// BoardProfile.h
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace bodaqs {

// ---------- IDs / Types ----------
enum class BoardID : uint8_t {
  ThingPlusS3_Base = 0,
  ThingPlusS3_CloneA,
  // Add more here...
};

enum class StorageType : uint8_t { None, SPI_SdFat, SDMMC };
enum class DisplayType : uint8_t { None, OLED_SSD1306 };
enum class FuelGaugeType : uint8_t { None, MAX17048, Other };
enum class ButtonID : uint8_t { BTN0=0, BTN1, BTN2, BTN3, BTN4, BTN5, Count };

// ---------- Sub-profiles ----------

struct StorageProfile {
  StorageType type = StorageType::None;

  // SPI SD (SdFat-style) configuration
  int8_t spi_host = 2;             // VSPI=2, HSPI=1 (your convention)
  int8_t sck = -1, miso = -1, mosi = -1;
  int8_t cs  = -1;
  uint32_t spi_hz = 20000000;

  // SDMMC configuration
  bool sdmmc_1bit = true;          // if you use SD_MMC 1-bit mode
};

struct ButtonHW {
  bool present = false;
  int8_t pin = -1;
  bool active_low = true;
  bool use_internal_pullup = true;
};

struct ButtonsProfile {
  ButtonHW btn[6];     // fixed max, easy on embedded
  uint8_t count = 0;   // number actually present
};

struct DisplayProfile {
  DisplayType type = DisplayType::None;

  // If using I2C OLED
  int8_t sda = -1, scl = -1;
  uint32_t i2c_hz = 400000;

  uint8_t addr_primary = 0x3C;
  uint8_t addr_alt     = 0x3D;

  // Optional reset pin for the display (if wired)
  int8_t rst = -1;                 // -1 = not used
};

struct FuelGaugeProfile {
  FuelGaugeType type = FuelGaugeType::None;
  uint8_t i2c_addr = 0x36;         // MAX17048 default
};

struct I2CProfile {
  bool present = false;
  int8_t sda = -1, scl = -1;
  uint32_t hz = 400000;
};

struct SPIProfile {
  bool present = false;
  int8_t sck = -1, miso = -1, mosi = -1;
  uint32_t hz_default = 20000000;

  // “available CS pins” for other SPI devices (IMUs, ADCs, etc.)
  int8_t cs_pins[8] = {-1,-1,-1,-1,-1,-1,-1,-1};
  uint8_t cs_count = 0;
};

struct AnalogInputsProfile {
  // Numbered analog inputs AIN0..AIN(N-1)
  int8_t pins[8] = {-1,-1,-1,-1,-1,-1,-1,-1};
  uint8_t count = 0;

  // Optional hints
  uint16_t adc_max = 4095;
  float vref = 3.3f;
};

struct IndicatorsProfile {
  bool has_led = false;
  int8_t led_pin = -1;
  bool led_active_high = true;

  bool has_buzzer = false;
  int8_t buzzer_pin = -1;
  bool buzzer_active_high = true;
};

struct LoggerPerfProfile {
  uint16_t queue_depth = 64;
  uint32_t ring_buffer_bytes = 8192;
};

// ---------- BoardProfile ----------
struct BoardProfile {
  const char* name = "Unknown";

  StorageProfile storage;
  DisplayProfile display;
  ButtonsProfile buttons;
  FuelGaugeProfile fuel;

  AnalogInputsProfile analog;
  I2CProfile i2c;
  SPIProfile spi;

  IndicatorsProfile indicators;
  LoggerPerfProfile perf;
};

// ---------- API ----------
const BoardProfile& GetBoardProfile(BoardID id);
const BoardProfile& GetBoardProfileByName(const char* name); // exact match (case-sensitive)

} // namespace bodaqs
